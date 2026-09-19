# StreamHub：订阅扇出 + 每流环形缓冲 + 单调 seq。
# SSE 连接经 register/unregister 挂队列；断线重连凭 Last-Event-ID 从环形缓冲补帧。

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass

from .frames import Frame

# 流身份：(symbol, period, barAggregation)。不同聚合边界不可共用帧序号或环形缓冲。
StreamKey = tuple[str, str, str]


@dataclass(frozen=True, slots=True)
class RingEntry:
    """环形缓冲条目：帧 + 该流内单调递增序号。"""

    seq: int
    frame: Frame


class StreamHub:
    """实时帧分发中心；纯内存、单事件循环内使用。"""

    def __init__(self, ring_size: int = 500):
        self._ring_size = ring_size
        self._rings: dict[StreamKey, deque[RingEntry]] = {}
        self._seqs: dict[StreamKey, int] = {}
        self._subscribers: dict[StreamKey, set[asyncio.Queue[RingEntry]]] = {}

    def publish(self, key: StreamKey, frame: Frame) -> int:
        """发布一帧：分配 seq、入环形缓冲、扇出到全部订阅队列；返回 seq。"""
        seq = self._seqs.get(key, 0) + 1
        self._seqs[key] = seq
        entry = RingEntry(seq, frame)

        ring = self._rings.get(key)
        if ring is None:
            ring = deque(maxlen=self._ring_size)
            self._rings[key] = ring
        ring.append(entry)

        for queue in self._subscribers.get(key, ()):
            queue.put_nowait(entry)
        return seq

    def register(self, key: StreamKey) -> asyncio.Queue[RingEntry]:
        """登记一个订阅者队列（SSE 连接建立时调用）。"""
        queue: asyncio.Queue[RingEntry] = asyncio.Queue()
        self._subscribers.setdefault(key, set()).add(queue)
        return queue

    def unregister(self, key: StreamKey, queue: asyncio.Queue[RingEntry]) -> None:
        """移除订阅者队列（SSE 连接断开时调用，幂等）。"""
        queues = self._subscribers.get(key)
        if queues is not None:
            queues.discard(queue)
            if not queues:
                self._subscribers.pop(key, None)

    def subscriber_count(self, key: StreamKey) -> int:
        """当前订阅者数量（aggregator 分级轮询用）。"""
        return len(self._subscribers.get(key, ()))

    def replay(self, key: StreamKey, after_seq: int | None) -> list[RingEntry]:
        """读取 seq 大于 after_seq 的缓冲帧（Last-Event-ID 补帧）。

        after_seq=None 视为从当前位置开始（不重放）；流不存在时返回 []。
        """
        ring = self._rings.get(key)
        if ring is None:
            return []
        floor = after_seq if after_seq is not None else self._seqs.get(key, 0)
        return [entry for entry in ring if entry.seq > floor]

    def last_seq(self, key: StreamKey) -> int:
        """当前流最大 seq。"""
        return self._seqs.get(key, 0)
