# ChangeDetector 语义测试：内容去重、收线判定（openTime 前移）、终端缓存滞后修订、休市 gap。

from __future__ import annotations

from mt5connector.aggregator import ChangeDetector
from mt5connector.frames import Bar, ClosedFrame, FormingFrame, SnapshotFrame


def bar(ts: int, close: float = 1.5, volume: float = 100) -> Bar:
    return Bar(ts, 1.0, 2.0, 0.5, close, volume, 0.0)


def test_first_sample_emits_snapshot():
    detector = ChangeDetector("XAUUSD", "4h")
    frames = detector.sample([bar(1000), bar(2000, close=2.0)])

    assert len(frames) == 1
    assert isinstance(frames[0], SnapshotFrame)
    assert frames[0].bars == (bar(1000), bar(2000, close=2.0))


def test_unchanged_tail_emits_nothing():
    detector = ChangeDetector("XAUUSD", "4h")
    detector.sample([bar(1000), bar(2000, close=2.0)])

    assert detector.sample([bar(1000), bar(2000, close=2.0)]) == []


def test_forming_content_change_emits_single_forming():
    detector = ChangeDetector("XAUUSD", "4h")
    detector.sample([bar(1000), bar(2000, close=2.0)])

    frames = detector.sample([bar(1000), bar(2000, close=2.5)])

    assert len(frames) == 1
    assert isinstance(frames[0], FormingFrame)
    assert frames[0].bar.close == 2.5


def test_close_advance_emits_closed_then_forming():
    detector = ChangeDetector("XAUUSD", "4h")
    detector.sample([bar(1000), bar(2000, close=2.0)])

    frames = detector.sample([bar(2000, close=2.2), bar(3000, close=3.0)])

    assert len(frames) == 2
    closed, forming = frames
    assert isinstance(closed, ClosedFrame)
    assert closed.bar.time_ms == 2000
    assert closed.bar.close == 2.2  # 收线帧带新采样中的终值（容忍滞后修订）
    assert isinstance(forming, FormingFrame)
    assert forming.bar.time_ms == 3000


def test_terminal_lag_revision_after_close_still_published():
    detector = ChangeDetector("XAUUSD", "4h")
    detector.sample([bar(1000), bar(2000, close=2.0)])
    detector.sample([bar(2000, close=2.2), bar(3000, close=3.0)])

    # 下一轮采样中已收线根又被终端修订（volume 补齐）
    frames = detector.sample([bar(2000, close=2.2, volume=150), bar(3000, close=3.0)])

    assert len(frames) == 1
    assert isinstance(frames[0], FormingFrame)
    assert frames[0].bar.time_ms == 2000
    assert frames[0].bar.volume == 150


def test_weekend_gap_skips_missing_bars():
    detector = ChangeDetector("XAUUSD", "4h")
    detector.sample([bar(1000), bar(2000, close=2.0)])

    # 休市 gap：2000 与 5000 之间的根缺失，只发可见根
    frames = detector.sample([bar(5000, close=5.0), bar(6000, close=6.0)])

    assert [type(f) for f in frames] == [ClosedFrame, FormingFrame, FormingFrame]
    assert frames[0].bar.time_ms == 2000
    assert [f.bar.time_ms for f in frames[1:]] == [5000, 6000]


def test_empty_sample_keeps_previous_tail_visible():
    detector = ChangeDetector("XAUUSD", "4h")
    detector.sample([bar(1000), bar(2000)])

    # 终端偶发返回空（品种暂无数据）：不发帧，不丢状态
    assert detector.sample([]) == []
    # 恢复后正常检测
    frames = detector.sample([bar(1000), bar(2000, close=1.8)])
    assert len(frames) == 1
