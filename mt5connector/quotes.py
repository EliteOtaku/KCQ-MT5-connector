# 报价投影：把日线实时帧压成最新价与昨收。
# 基准来自建连时的一次性历史查询，实时帧只负责增量；两者共用同一份尾部窗口。

from __future__ import annotations

from collections.abc import Iterable

from .frames import Bar, ClosedFrame, FormingFrame, Frame, SnapshotFrame, quote_payload

# 只保留最近三根：两根用于计算，多留一根给收线后的修订。
_KEEP_BARS = 3


class QuoteProjection:
    """按品种维护日线尾部，输出最新价与昨收；值不变时不重复推送。"""

    def __init__(self) -> None:
        self._bars: dict[str, list[Bar]] = {}
        self._emitted: dict[str, tuple[float, float]] = {}

    def push(self, frame: Frame) -> dict[str, object] | None:
        """送入一帧；产生新的报价才返回载荷，其余帧返回 None。"""
        if isinstance(frame, SnapshotFrame):
            # 快照可能只剩一根（对齐口径压缩尾部）；按时间戳并入而非覆盖，
            # 保留建连时注入的历史基准，否则 seed 会被快照冲掉。
            for bar in frame.bars:
                self._upsert(frame.instrument_id, bar)
        elif isinstance(frame, (FormingFrame, ClosedFrame)):
            self._upsert(frame.instrument_id, frame.bar)
        else:
            return None
        return self._quote(frame.instrument_id)

    def _upsert(self, instrument_id: str, bar: Bar) -> None:
        """按时间戳升序插入或覆盖，只保留尾部窗口。"""
        bars = self._bars.setdefault(instrument_id, [])
        for index, existing in enumerate(bars):
            if existing.time_ms == bar.time_ms:
                bars[index] = bar
                return
            if existing.time_ms > bar.time_ms:
                bars.insert(index, bar)
                break
        else:
            bars.append(bar)
        del bars[:-_KEEP_BARS]

    def _quote(self, instrument_id: str) -> dict[str, object] | None:
        """倒数两根即最新价与昨收；不足两根时没有可比的基准。"""
        bars = self._bars.get(instrument_id, [])
        if len(bars) < 2:
            return None
        last, previous = bars[-1], bars[-2]
        marker = (last.close, previous.close)
        if self._emitted.get(instrument_id) == marker:
            return None
        self._emitted[instrument_id] = marker
        return quote_payload(instrument_id, last.close, previous.close, last.time_ms)

    def seed(self, instrument_id: str, bars: Iterable[Bar]) -> None:
        """注入历史日线补齐基准。

        对齐口径会压缩尾部（Exness 的 europe-traditional 把周日短棒并入周一），
        实时快照可能只剩一根；先注入历史才能凑出「最新价 + 昨收」两根。
        重复注入按时间戳覆盖，不产生重复根。
        """
        for bar in bars:
            self._upsert(instrument_id, bar)
