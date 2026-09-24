# 聚合器：每 (symbol, period) 一条轮询任务。
# 分级轮询：报价探针先行、变化才取 K 线；无观察者降为后台档；静默退避指数增长封顶。
# ChangeDetector 为纯函数类：openTime+OHLCV 内容去重、收线判定、终端缓存滞后容忍。

from __future__ import annotations

import asyncio
import logging
import time

from . import align
from .bar_aggregation import ALIGNED_BAR_AGGREGATION, EUROPE_TRADITIONAL_BAR_AGGREGATION
from .clock import ServerClock
from .config import Settings
from .frames import Bar, ClosedFrame, FormingFrame, Frame, SnapshotFrame, StatusFrame
from .gateway import Mt5Gateway
from .hub import StreamHub, StreamKey

logger = logging.getLogger("mt5.aggregator")

# 各周期重采样取源根数（覆盖快照尾部 2 根目标桶 + 边界余量）
_H1_FETCH_COUNTS = {"4h": 10, "daily": 54}
_D1_FETCH_COUNTS = {"weekly": 14, "monthly": 62}

# 周期秒数（状态判定/退避参考）
_PERIOD_SECONDS = {
    "1min": 60, "5min": 300, "15min": 900, "30min": 1800,
    "60min": 3600, "4h": 14400, "daily": 86400, "weekly": 604800, "monthly": 2592000,
}


class ChangeDetector:
    """尾部序列变化检测：输入升序尾部（≤ 数根，末位为 forming），输出帧序列。"""

    def __init__(self, symbol: str, period: str):
        self._symbol = symbol
        self._period = period
        self._tail: tuple[Bar, ...] = ()

    def sample(self, bars: list[Bar]) -> list[Frame]:
        """送入最新尾部并返回需要发布的帧；无变化返回空列表。"""
        if not bars:
            return []
        tail = tuple(bars)
        try:
            return self._diff(self._tail, tail)
        finally:
            self._tail = tail

    def _diff(self, prev: tuple[Bar, ...], next_: tuple[Bar, ...]) -> list[Frame]:
        """比较相邻两次尾部采样，产出 snapshot/closed/forming 帧。"""
        if not prev:
            return [SnapshotFrame(self._symbol, self._period, next_)]

        prev_by_time = {bar.time_ms: bar for bar in prev}
        next_by_time = {bar.time_ms: bar for bar in next_}
        prev_forming = prev[-1]
        next_forming = next_[-1]
        frames: list[Frame] = []
        covered_ts: int | None = None

        # 收线判定：forming openTime 前移 → 旧 forming 收线（以新采样中的终值优先，容忍缓存滞后）
        if next_forming.time_ms > prev_forming.time_ms:
            finalized = next_by_time.get(prev_forming.time_ms, prev_forming)
            frames.append(ClosedFrame(self._symbol, self._period, finalized))
            covered_ts = finalized.time_ms  # 终值已随 closed 帧下发，内容环不再重复发

        # 内容变化帧：新出现或 OHLCV 变化的根（含收线后仍被终端修订的旧根）
        for bar in next_:
            if bar.time_ms == covered_ts:
                continue
            old = prev_by_time.get(bar.time_ms)
            if old is None or old != bar:
                frames.append(FormingFrame(self._symbol, self._period, bar))
        return frames


def _aligned_plan(period: str, align_enabled: bool) -> str:
    """解析周期取数方案：native / h1 / d1（对齐开启时 4h 以上走重采样）。"""
    if not align_enabled:
        return "native"
    if period in align.RESAMPLE_H1_TARGETS:
        return "h1"
    if period in align.RESAMPLE_D1_TARGETS:
        return "d1"
    return "native"


class Aggregator:
    """轮询任务编排：订阅增减驱动任务生命周期，帧统一发布到 StreamHub。"""

    def __init__(self, gateway: Mt5Gateway, clock: ServerClock, hub: StreamHub, settings: Settings):
        self._gateway = gateway
        self._clock = clock
        self._hub = hub
        self._settings = settings
        self._tasks: dict[StreamKey, asyncio.Task] = {}
        self._viewers: dict[StreamKey, int] = {}
        self._background_until: dict[StreamKey, float] = {}
        self._wake: dict[StreamKey, asyncio.Event] = {}
        self._resnapshot: set[StreamKey] = set()

    # ── 订阅生命周期 ──

    def ensure(self, key: StreamKey, resnapshot: bool = False) -> None:
        """确保流存在轮询任务并计为活跃。

        resnapshot=True（新 SSE 连接）时复位检测器让任务重发快照帧；
        已有任务经 wake 事件立即唤醒，无任务则创建（首采样天然是快照）。
        """
        self._viewers[key] = self._viewers.get(key, 0) + 1
        self._background_until.pop(key, None)
        if key not in self._tasks:
            self._wake[key] = asyncio.Event()
            self._tasks[key] = asyncio.create_task(self._poll(key), name=f"mt5-poll:{key}")
            return
        if resnapshot:
            self._resnapshot.add(key)
        self._wake[key].set()

    def release(self, key: StreamKey) -> None:
        """解除一个观察者；进入后台宽限期后仍未有人订阅则停止任务。"""
        viewers = max(0, self._viewers.get(key, 0) - 1)
        self._viewers[key] = viewers
        if viewers == 0:
            # 后台宽限期：快速切回同品种时避免冷启动
            grace = self._settings.background_poll_seconds * 6
            self._background_until[key] = asyncio.get_running_loop().time() + grace

    def stop_all(self) -> None:
        """应用关闭时取消全部轮询任务。"""
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
        self._viewers.clear()
        self._background_until.clear()
        self._wake.clear()
        self._resnapshot.clear()

    # ── 轮询循环 ──

    async def _poll(self, key: StreamKey) -> None:
        """单流轮询主循环：首采样出快照，之后报价探针驱动 + 静默退避。"""
        symbol, period, bar_aggregation = key
        detector = ChangeDetector(symbol, period)
        align_enabled = bar_aggregation == ALIGNED_BAR_AGGREGATION
        # europe-traditional 4h 与 aligned 同走 H1 重采样，但用 NY-close 日界
        # （对齐主流经纪商 4h 收线时间）；merge_sunday_bars 仅适用于日线。
        ny_close_4h = (
            bar_aggregation == EUROPE_TRADITIONAL_BAR_AGGREGATION and period == "4h"
        )
        plan = "h1" if ny_close_4h else _aligned_plan(period, align_enabled)
        anchor = "ny_close" if ny_close_4h else "utc"
        merge_sunday = bar_aggregation == EUROPE_TRADITIONAL_BAR_AGGREGATION and period == "daily"
        wake = asyncio.Event()
        self._wake[key] = wake
        quiet = 0
        first_sample = True
        last_quote_tick: float | None = None
        market_open: bool | None = None
        next_interval = 0.0  # 首轮立即采样，让订阅尽快拿到快照

        while True:
            try:
                if next_interval > 0:
                    try:
                        await asyncio.wait_for(wake.wait(), timeout=next_interval)
                    except asyncio.TimeoutError:
                        pass
                woken = wake.is_set()
                wake.clear()
                if key in self._resnapshot:
                    # 新订阅要求快照：复位检测器，本轮采样输出 SnapshotFrame
                    self._resnapshot.discard(key)
                    detector = ChangeDetector(symbol, period)

                now = asyncio.get_running_loop().time()
                if (
                    self._viewers.get(key, 0) == 0
                    and self._background_until.get(key, 0.0) < now
                ):
                    break

                first_sample_done = first_sample
                first_sample = False
                quote_tick = await self._gateway.symbol_info_tick(symbol)
                quote_tick_changed = (
                    quote_tick is not None and quote_tick.time_seconds != last_quote_tick
                )
                if quote_tick is not None:
                    last_quote_tick = quote_tick.time_seconds

                # 状态帧：报价新鲜度判开闭，变化才发
                open_now = self._judge_market_open(quote_tick, period)
                if open_now is not market_open:
                    market_open = open_now
                    if open_now is not None:
                        status = "open" if open_now else "closed"
                        self._hub.publish(key, StatusFrame(symbol, period, status))

                if not first_sample_done and not woken and not quote_tick_changed:
                    quiet += 1
                else:
                    quiet = 0
                    bars = await self._fetch_tail(symbol, period, plan, anchor=anchor)
                    if merge_sunday:
                        bars = align.merge_sunday_bars(bars)
                    for frame in detector.sample(bars):
                        self._hub.publish(key, frame)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — 单流故障不拖垮全局
                logger.warning("poll %s failed: %s", key, exc)
                self._hub.publish(key, StatusFrame(symbol, period, "degraded", str(exc)))
                quiet += 1
            next_interval = self._current_interval(key, quiet)

        self._tasks.pop(key, None)
        self._background_until.pop(key, None)
        self._wake.pop(key, None)

    def _current_interval(self, key: StreamKey, quiet: int) -> float:
        """当前轮询间隔：活跃/后台基线 × 静默指数退避，封顶 quiet_backoff_cap。"""
        base = (
            self._settings.active_poll_seconds
            if self._viewers.get(key, 0) > 0
            else self._settings.background_poll_seconds
        )
        scaled = base * (2 ** min(quiet, 8))
        return min(scaled, self._settings.quiet_backoff_cap_seconds)

    def _judge_market_open(self, quote_tick, period: str) -> bool | None:
        """按最后报价 tick 年龄判定行情开闭；无报价 tick 无法判定。"""
        if quote_tick is None:
            return None
        period_seconds = _PERIOD_SECONDS.get(period, 3600)
        max_age = max(period_seconds * 2, 900)
        return (time.time() - quote_tick.time_seconds) <= max_age

    async def _fetch_tail(self, symbol: str, period: str, plan: str, anchor: str = "utc") -> list[Bar]:
        """按方案拉取尾部序列并统一为真 UTC Bar（升序）。anchor 传入 align.resample。"""
        offset = await self._clock.ensure_fresh()
        if plan == "h1":
            count = _H1_FETCH_COUNTS[period]
            raw = await self._gateway.copy_rates_from_pos(symbol, "60min", count)
            aligned = align.resample(raw, period, offset, anchor=anchor)
        elif plan == "d1":
            count = _D1_FETCH_COUNTS[period]
            raw = await self._gateway.copy_rates_from_pos(symbol, "daily", count)
            aligned = align.resample(raw, period, offset, anchor=anchor)
        else:
            raw = await self._gateway.copy_rates_from_pos(symbol, period, self._settings.snapshot_bars)
            aligned = [
                Bar(
                    time_ms=align.server_to_utc_ms(bar.time_ms, offset),
                    open=bar.open, high=bar.high, low=bar.low,
                    close=bar.close, volume=bar.volume, turnover=bar.turnover,
                )
                for bar in raw
            ]
        keep = self._settings.snapshot_bars
        return aligned[-keep:]
