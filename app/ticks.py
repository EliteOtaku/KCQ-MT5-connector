# 逐笔 tick 轮询编排：每 symbol 一条任务，按 time_msc 增量拉取并合并为 ticks 帧发布。
# 与 K 线流身份隔离——tick 与 period / barAggregation 无关，仅由 symbol 决定。

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

from . import align
from .clock import ServerClock
from .config import Settings
from .frames import Tick, TicksFrame
from .gateway import Mt5Gateway
from .hub import StreamHub, StreamKey

logger = logging.getLogger("mt5.ticks")

# tick 流身份的保留字段占位：复用 StreamKey 三元组，但语义上只由 symbol 决定
TICKS_STREAM_PERIOD = "ticks"
TICKS_STREAM_AGGREGATION = "raw"


def tick_stream_key(symbol: str) -> StreamKey:
    """tick 流身份（仅由 symbol 决定，禁止与 K 线流复用序号/环形缓冲）。"""
    return (symbol, TICKS_STREAM_PERIOD, TICKS_STREAM_AGGREGATION)


class TickAggregator:
    """逐笔 tick 订阅编排：订阅增减驱动任务生命周期，帧统一发布到 StreamHub。"""

    def __init__(self, gateway: Mt5Gateway, clock: ServerClock, hub: StreamHub, settings: Settings):
        self._gateway = gateway
        self._clock = clock
        self._hub = hub
        self._settings = settings
        self._tasks: dict[str, asyncio.Task] = {}
        self._viewers: dict[str, int] = {}
        self._background_until: dict[str, float] = {}
        self._wake: dict[str, asyncio.Event] = {}

    # ── 订阅生命周期 ──

    def ensure(self, symbol: str) -> None:
        """确保 symbol 的 tick 轮询任务存在并计为活跃。"""
        self._viewers[symbol] = self._viewers.get(symbol, 0) + 1
        self._background_until.pop(symbol, None)
        if symbol not in self._tasks:
            self._wake[symbol] = asyncio.Event()
            self._tasks[symbol] = asyncio.create_task(
                self._poll(symbol), name=f"mt5-tick:{symbol}"
            )
            return
        self._wake[symbol].set()

    def release(self, symbol: str) -> None:
        """解除一个观察者；无人订阅时进入后台宽限期，超时后停止任务。"""
        viewers = max(0, self._viewers.get(symbol, 0) - 1)
        self._viewers[symbol] = viewers
        if viewers == 0:
            grace = self._settings.background_poll_seconds * 6
            self._background_until[symbol] = asyncio.get_running_loop().time() + grace

    def stop_all(self) -> None:
        """应用关闭时取消全部 tick 轮询任务。"""
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()
        self._viewers.clear()
        self._background_until.clear()
        self._wake.clear()

    # ── 轮询循环 ──

    async def _poll(self, symbol: str) -> None:
        """单 symbol 轮询主循环：首采样只定基线，之后增量拉取并去重发布。"""
        key = tick_stream_key(symbol)
        wake = self._wake[symbol]
        # 服务器时间基线（毫秒，含伪 UTC）：新订阅从当前时刻起，不回放建立前的历史
        baseline_ms: int | None = None
        # 已发布 tick 的指纹窗口：copy_ticks_from 按秒取整会带回上一轮的部分 tick
        seen: set[tuple[int, float, float, float, float]] = set()
        seen_order: deque[tuple[int, float, float, float, float]] = deque()

        while True:
            try:
                interval = self._current_interval(symbol)
                if baseline_ms is not None:
                    try:
                        await asyncio.wait_for(wake.wait(), timeout=interval)
                    except asyncio.TimeoutError:
                        pass
                wake.clear()

                now = asyncio.get_running_loop().time()
                if (
                    self._viewers.get(symbol, 0) == 0
                    and self._background_until.get(symbol, 0.0) < now
                ):
                    break

                offset = await self._clock.ensure_fresh()
                if baseline_ms is None:
                    baseline_ms = int((time.time() + offset * 60) * 1000)
                    continue

                raw = await self._gateway.copy_ticks_from(
                    symbol, baseline_ms // 1000, self._settings.tick_pull_max
                )
                if not raw:
                    continue

                emitted: list[Tick] = []
                for tick in raw:
                    marker = (tick.time_ms, tick.bid, tick.ask, tick.last, tick.volume)
                    if marker in seen:
                        continue
                    seen.add(marker)
                    seen_order.append(marker)
                    while len(seen_order) > self._settings.tick_seen_window:
                        seen.discard(seen_order.popleft())
                    emitted.append(
                        Tick(
                            time_ms=align.server_to_utc_ms(tick.time_ms, offset),
                            bid=tick.bid,
                            ask=tick.ask,
                            last=tick.last,
                            volume=tick.volume,
                        )
                    )
                    if tick.time_ms > baseline_ms:
                        baseline_ms = tick.time_ms

                if emitted:
                    emitted.sort(key=lambda item: item.time_ms)
                    self._hub.publish(key, TicksFrame(symbol, tuple(emitted)))
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — 单流故障不拖垮全局
                logger.warning("tick poll %s failed: %s", symbol, exc)

        self._tasks.pop(symbol, None)
        self._background_until.pop(symbol, None)
        self._wake.pop(symbol, None)

    def _current_interval(self, symbol: str) -> float:
        """当前轮询间隔：活跃用 tick 轮询基线，无观察者回落到后台轮询基线。"""
        if self._viewers.get(symbol, 0) > 0:
            return self._settings.tick_poll_seconds
        return self._settings.background_poll_seconds
