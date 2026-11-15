# 服务器时间轴偏移实测：MT5 时间戳是"服务器墙钟按 UTC epoch 解释"的伪 UTC，
# 必须实测偏移才能换算真 UTC。优先探测 7x24 加密品种（外汇周末报价 tick 停更）。

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

# 偏移探测品种优先级：加密优先（周末也有报价 tick），外汇/金属兜底
PROBE_SYMBOLS = ("BTCUSD", "ETHUSD", "EURUSD", "XAUUSD")

# 报价 tick 的新鲜度上限（秒）。陈旧 tick 只差了几小时会被取整成错误的整小时偏移，
# 一旦接受就会让全部 K 线整体平移，因此超过这个年龄一律不采信。
FRESH_TICK_SECONDS = 300.0


@dataclass
class OffsetSample:
    """一次实测结果：偏移分钟数与是否成功。"""

    offset_minutes: int
    ok: bool


def measure_offset_minutes(
    last_quote_tick_server_seconds: float | None,
    now_seconds: float | None = None,
) -> OffsetSample:
    """由最后报价 tick 服务器时间推算服务器领先 UTC 的整小时偏移。

    本机时钟与服务器时钟差取整到小时后模 24h 归一到 [-12h, +12h)，
    消除周末停市期间累积的天数偏移。报价 tick 缺失或陈旧时返回 ok=False：
    陈旧 tick 的时间差会落在整小时边界附近，取整后偏差可达数小时。

    @param last_quote_tick_server_seconds 最后报价 tick 的服务器时间（秒）
    @param now_seconds 当前时间（秒）；缺省取系统时间，便于测试固定时钟
    @returns 偏移分钟数与是否可信
    """
    if last_quote_tick_server_seconds is None or last_quote_tick_server_seconds <= 0:
        return OffsetSample(0, False)
    now = time.time() if now_seconds is None else float(now_seconds)
    delta_seconds = now - float(last_quote_tick_server_seconds)
    hours = round(delta_seconds / 3600.0)
    # 新鲜 tick 的残差只有本机与服务器的秒级时钟偏差；残差过大说明 tick 陈旧，
    # 此时整小时取整会把偏差放大到 1 小时以上，宁可判定失败沿用上次成功值。
    if abs(delta_seconds - hours * 3600.0) > FRESH_TICK_SECONDS:
        return OffsetSample(0, False)
    normalized = (hours + 12) % 24 - 12
    return OffsetSample(int(normalized) * 60, True)


class ServerClock:
    """服务器偏移缓存：env 覆盖优先，实测带 TTL 复测。"""

    def __init__(self, gateway, settings, recheck_seconds: float = 300.0):
        self._gateway = gateway
        self._settings = settings
        self._recheck_seconds = recheck_seconds
        self._offset_minutes: int | None = None
        self._last_refresh = 0.0

    async def refresh(self) -> int:
        """复测偏移（探测品种逐一尝试，任一成功即用）；env 覆盖时直接生效。"""
        override = self._settings.server_utc_offset_override
        if override is not None:
            self._offset_minutes = override * 60
            self._last_refresh = time.monotonic()
            return self._offset_minutes

        for symbol in PROBE_SYMBOLS:
            quote_tick = await self._gateway.symbol_info_tick(symbol)
            quote_tick_server_seconds = quote_tick.time_seconds if quote_tick is not None else 0
            sample = measure_offset_minutes(quote_tick_server_seconds or None)
            if sample.ok:
                self._offset_minutes = sample.offset_minutes
                self._last_refresh = time.monotonic()
                return self._offset_minutes
        return self.offset_minutes()

    def offset_minutes(self) -> int:
        """读取当前偏移；从未实测成功时回落 0（Exness 服务器 = GMT+0）。"""
        return self._offset_minutes if self._offset_minutes is not None else 0

    def is_measured(self) -> bool:
        """是否已有实测或 env 覆盖结果。"""
        return self._offset_minutes is not None

    async def ensure_fresh(self) -> int:
        """带 TTL 的惰性复测：过期才真正探测，未过期直接读缓存。"""
        if time.monotonic() - self._last_refresh >= self._recheck_seconds:
            return await self.refresh()
        return self.offset_minutes()

    async def run_forever(self, stop: asyncio.Event) -> None:
        """后台周期复测循环，随应用关闭退出。"""
        while not stop.is_set():
            try:
                await self.refresh()
            except Exception:  # noqa: BLE001 — 后台任务不因单次探测失败退出
                pass
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._recheck_seconds)
            except asyncio.TimeoutError:
                continue
