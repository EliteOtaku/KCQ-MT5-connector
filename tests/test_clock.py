# 服务器时钟偏移：整小时取整的残差判定，以及陈旧 tick 必须被拒绝。
# 偏移的正负号沿用既有实现（与 resample/服务端换算保持同一约定），
# 这里只断言「能否测出」与「整小时量级」，不重新定义符号语义。

from __future__ import annotations

from mt5connector.clock import FRESH_TICK_SECONDS, measure_offset_minutes

# 固定测试时钟：2026-11-15T08:00:00Z
NOW = 1_763_193_600.0


def test_measures_whole_hour_offset_from_fresh_tick() -> None:
    sample = measure_offset_minutes(NOW - 2 * 3600, now_seconds=NOW)
    assert sample.ok is True
    assert abs(sample.offset_minutes) == 120


def test_normalizes_to_twelve_hour_window() -> None:
    # 任何方向都应归一到 ±12 小时之内
    for hours in (-11, -5, 3, 9):
        sample = measure_offset_minutes(NOW - hours * 3600, now_seconds=NOW)
        assert sample.ok is True
        assert -720 <= sample.offset_minutes < 720


def test_rejects_stale_tick() -> None:
    # 周末停市：最后一笔 tick 是两天半前，残差落在整小时之外
    stale = NOW - (2 * 24 * 3600 + 1800)
    sample = measure_offset_minutes(stale, now_seconds=NOW)
    assert sample.ok is False
    assert sample.offset_minutes == 0


def test_accepts_small_clock_skew() -> None:
    # 本机与服务器有 20 秒时钟偏差，仍在可信范围内
    sample = measure_offset_minutes(NOW - 3 * 3600 - 20, now_seconds=NOW)
    assert sample.ok is True
    assert abs(sample.offset_minutes) == 180


def test_rejects_skew_over_freshness_limit() -> None:
    skewed = NOW - 3600 - (FRESH_TICK_SECONDS + 1)
    assert measure_offset_minutes(skewed, now_seconds=NOW).ok is False


def test_rejects_missing_tick() -> None:
    assert measure_offset_minutes(None, now_seconds=NOW).ok is False
    assert measure_offset_minutes(0, now_seconds=NOW).ok is False
