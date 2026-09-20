# MT5 IPC 网关：MetaTrader5 Python 包的唯一持有者。
# MetaTrader5 无异步接口且不可多线程并发调用——全部调用经单工作线程串行执行；
# initialize 必须传终端全路径（裸调用会拉起 Windows 默认终端），失败快速抛错。

from __future__ import annotations

import asyncio
import concurrent.futures
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .frames import Bar, Tick

# Exness 平台已知安装路径（未显式指定终端时按序探测）
EXNESS_TERMINAL_PATHS = (
    r"C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe",
    r"C:\Program Files (x86)\MetaTrader 5 EXNESS\terminal64.exe",
)

# 协议周期 → MetaTrader5 常量名（native 档位）
TF_CONSTANTS = {
    "1min": "TIMEFRAME_M1",
    "5min": "TIMEFRAME_M5",
    "15min": "TIMEFRAME_M15",
    "30min": "TIMEFRAME_M30",
    "60min": "TIMEFRAME_H1",
    "4h": "TIMEFRAME_H4",
    "daily": "TIMEFRAME_D1",
    "weekly": "TIMEFRAME_W1",
    "monthly": "TIMEFRAME_MN1",
}

SYMBOL_CACHE_TTL_SECONDS = 60.0
REINITIALIZE_MIN_INTERVAL_SECONDS = 10.0


@dataclass(frozen=True, slots=True)
class SymbolMeta:
    """品种目录条目（symbols_get 的精简投影）。"""

    name: str
    description: str
    currency: str
    point: float
    volume_min: float


@dataclass(frozen=True, slots=True)
class TickProbe:
    """轻量 tick 探针结果（聚合轮询用）。"""

    time_seconds: float
    bid: float
    ask: float


class Mt5Gateway:
    """MT5 终端网关：连接生命周期 + 全部数据查询的串行执行点。"""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self._mt5 = None
        self._terminal_path: str | None = None
        self._is_exness = False
        self._last_initialize_attempt = 0.0
        self._symbol_cache: list[SymbolMeta] | None = None
        self._symbol_cache_at = 0.0
        self._init_error: str | None = None

    # ── 生命周期 ──

    async def initialize(self) -> dict:
        """连接终端并完成平台/登录校验；返回终端摘要 dict，失败抛 RuntimeError。"""
        return await asyncio.get_running_loop().run_in_executor(self._executor, self._initialize_sync)

    def _initialize_sync(self) -> dict:
        import MetaTrader5 as mt5  # noqa: PLC0415 — 仅 Windows 可装，延迟导入

        self._mt5 = mt5
        self._last_initialize_attempt = time.monotonic()
        path = self._resolve_terminal_path()
        self._terminal_path = path

        if not mt5.initialize(path=path):
            err = mt5.last_error()
            raise RuntimeError(f"MT5 initialize 失败: {err} (terminal_path={path or '默认'})")

        info = self._terminal_summary_sync()
        if self._settings.exness_only and not self._is_exness:
            mt5.shutdown()
            raise RuntimeError(
                f"平台校验失败：当前终端为 {info.get('company')!r} (server={info.get('server')!r})，"
                f"不是 Exness；可用 MT5_TERMINAL_PATH 指定 Exness 终端，或设 EXNESS_ONLY=0 关闭校验"
            )
        self._init_error = None
        return info

    def _resolve_terminal_path(self) -> str | None:
        """解析终端路径：显式配置优先，其次探测已知 Exness 安装路径。"""
        if self._settings.terminal_path:
            return self._settings.terminal_path
        return next((p for p in EXNESS_TERMINAL_PATHS if Path(p).exists()), None)

    def _terminal_summary_sync(self) -> dict:
        """读取终端/账户摘要并刷新平台判定；不发起重连。"""
        mt5 = self._mt5
        ti = mt5.terminal_info() if mt5 is not None else None
        ai = mt5.account_info() if mt5 is not None else None
        company = getattr(ti, "company", "") or ""
        server = getattr(ai, "server", "") or ""
        login = getattr(ai, "login", None)
        self._is_exness = "exness" in (company + " " + server).lower()
        if login is None:
            raise RuntimeError("MT5 终端未登录账户，请在终端完成登录后重启连接器")
        return {
            "terminal": getattr(ti, "name", "") or "",
            "company": company,
            "connected": bool(getattr(ti, "connected", False)),
            "account": login,
            "server": server,
            "currency": getattr(ai, "currency", "") or "",
        }

    async def reinitialize_if_disconnected(self) -> bool:
        """心跳回调：断连时限流重连（≥REINITIALIZE_MIN_INTERVAL 一次），抑制风暴。"""
        mt5 = self._mt5
        if mt5 is None:
            return False
        if await self.is_connected():
            return False
        if time.monotonic() - self._last_initialize_attempt < REINITIALIZE_MIN_INTERVAL_SECONDS:
            return False
        try:
            await asyncio.get_running_loop().run_in_executor(
                self._executor, self._reinitialize_sync
            )
            return True
        except Exception as exc:  # noqa: BLE001 — 心跳重连失败留待下轮
            self._init_error = str(exc)
            return False

    def _reinitialize_sync(self) -> None:
        mt5 = self._mt5
        self._last_initialize_attempt = time.monotonic()
        mt5.shutdown()
        if not mt5.initialize(path=self._terminal_path):
            raise RuntimeError(f"MT5 re-initialize 失败: {mt5.last_error()}")
        self._terminal_summary_sync()

    async def shutdown(self) -> None:
        """释放终端句柄与工作线程。"""
        mt5 = self._mt5
        if mt5 is not None:
            try:
                await asyncio.get_running_loop().run_in_executor(self._executor, mt5.shutdown)
            except Exception:  # noqa: BLE001
                pass
            self._mt5 = None
        self._executor.shutdown(wait=False)

    async def is_connected(self) -> bool:
        """轻量连接探测（terminal_info().connected）。"""
        mt5 = self._mt5
        if mt5 is None:
            return False
        loop = asyncio.get_running_loop()
        ti = await loop.run_in_executor(self._executor, mt5.terminal_info)
        return bool(ti is not None and getattr(ti, "connected", False))

    async def terminal_summary(self) -> dict:
        """读取终端摘要（probe 端点用）；句柄缺失时抛错。"""
        if self._mt5 is None:
            raise RuntimeError(self._init_error or "MT5 gateway 未初始化")
        return await asyncio.get_running_loop().run_in_executor(
            self._executor, self._terminal_summary_sync
        )

    @property
    def init_error(self) -> str | None:
        """最近一次初始化/重连失败原因。"""
        return self._init_error

    # ── 数据查询 ──

    async def symbols(self) -> list[SymbolMeta]:
        """枚举品种目录（60s 缓存；symbols_get 一次拉全量较重）。"""
        if self._symbol_cache is not None and time.monotonic() - self._symbol_cache_at < SYMBOL_CACHE_TTL_SECONDS:
            return self._symbol_cache
        mt5 = self._mt5
        if mt5 is None:
            raise RuntimeError(self._init_error or "MT5 gateway 未初始化")
        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(self._executor, mt5.symbols_get)
        items: list[SymbolMeta] = []
        if raw is not None:
            for s in raw:
                items.append(
                    SymbolMeta(
                        name=s.name,
                        description=getattr(s, "description", "") or "",
                        currency=getattr(s, "currency_profit", "") or "",
                        point=float(getattr(s, "point", 0.0) or 0.0),
                        volume_min=float(getattr(s, "volume_min", 0.0) or 0.0),
                    )
                )
        items.sort(key=lambda item: item.name)
        self._symbol_cache = items
        self._symbol_cache_at = time.monotonic()
        return items

    def invalidate_symbol_cache(self) -> None:
        """清空品种目录缓存（测试与手动刷新用）。"""
        self._symbol_cache = None
        self._symbol_cache_at = 0.0

    async def symbol_info_tick(self, symbol: str) -> TickProbe | None:
        """读取品种最后 tick（轮询探针/偏移实测共用）。"""
        mt5 = self._mt5
        if mt5 is None:
            return None
        loop = asyncio.get_running_loop()
        tick = await loop.run_in_executor(self._executor, lambda: mt5.symbol_info_tick(symbol))
        if tick is None or not getattr(tick, "time", 0):
            return None
        return TickProbe(
            time_seconds=float(tick.time),
            bid=float(getattr(tick, "bid", 0.0) or 0.0),
            ask=float(getattr(tick, "ask", 0.0) or 0.0),
        )

    async def copy_rates_from_pos(self, symbol: str, period: str, count: int) -> list[Bar]:
        """按位置拉取最新 count 根 K 线（位置 0 = forming bar）；返回服务器时间 Bar。"""
        tf_name = TF_CONSTANTS.get(period)
        if tf_name is None:
            raise ValueError(f"不支持的周期: {period!r}")
        mt5 = self._mt5
        if mt5 is None:
            raise RuntimeError(self._init_error or "MT5 gateway 未初始化")
        tf = getattr(mt5, tf_name)
        loop = asyncio.get_running_loop()
        rates = await loop.run_in_executor(
            self._executor, lambda: mt5.copy_rates_from_pos(symbol, tf, 0, count)
        )
        return _rates_to_bars(rates)

    async def copy_rates_range(
        self, symbol: str, period: str, from_server_ms: int, to_server_ms: int
    ) -> list[Bar]:
        """按服务器时间区间拉取 K 线（闭区间，bar open 落在区间内）；返回服务器时间 Bar。"""
        tf_name = TF_CONSTANTS.get(period)
        if tf_name is None:
            raise ValueError(f"不支持的周期: {period!r}")
        mt5 = self._mt5
        if mt5 is None:
            raise RuntimeError(self._init_error or "MT5 gateway 未初始化")
        tf = getattr(mt5, tf_name)
        loop = asyncio.get_running_loop()
        rates = await loop.run_in_executor(
            self._executor,
            lambda: mt5.copy_rates_range(
                symbol, tf, int(from_server_ms / 1000), int(to_server_ms / 1000)
            ),
        )
        return _rates_to_bars(rates)

    async def copy_ticks_from(
        self, symbol: str, from_server_seconds: int, count: int
    ) -> list[Tick]:
        """拉取自指定服务器时间（秒）起的逐笔 tick（升序、不超过 count）；返回服务器时间 Tick。"""
        mt5 = self._mt5
        if mt5 is None:
            raise RuntimeError(self._init_error or "MT5 gateway 未初始化")
        flags = getattr(mt5, "COPY_TICKS_ALL", 0)
        loop = asyncio.get_running_loop()
        ticks = await loop.run_in_executor(
            self._executor,
            lambda: mt5.copy_ticks_from(symbol, int(from_server_seconds), int(count), flags),
        )
        return _ticks_to_ticks(ticks)


def _rates_to_bars(rates) -> list[Bar]:
    """MT5 rates 结构数组 → Bar 列表（时间秒→毫秒，volume 取 tick_volume）。"""
    if rates is None or len(rates) == 0:
        return []
    return [
        Bar(
            time_ms=int(row["time"]) * 1000,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["tick_volume"]),
        )
        for row in rates
    ]


def _ticks_to_ticks(ticks) -> list[Tick]:
    """MT5 tick 结构数组 → Tick 列表（time_msc 为服务器毫秒）。"""
    if ticks is None or len(ticks) == 0:
        return []
    return [
        Tick(
            time_ms=int(row["time_msc"]),
            bid=float(row["bid"]),
            ask=float(row["ask"]),
            last=float(row["last"]),
            volume=float(row["volume"]),
        )
        for row in ticks
    ]
