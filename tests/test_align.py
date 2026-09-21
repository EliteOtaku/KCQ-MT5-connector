# 对齐重采样语义测试：UTC 4h/日线/周/月桶边界、跨月跨周归属、偏移校正。
# 锚恒为 UTC，不随品种类别或环境配置变化。

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.align import merge_sunday_bars, resample, server_to_utc_ms
from app.frames import Bar

UTC = timezone.utc


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _h1(start: datetime, hours: int) -> list[Bar]:
    """从 start 起的连续 H1 服务器时间 Bar（offset=0 时服务器时间即 UTC）。"""
    return [
        Bar(_ms(start + timedelta(hours=i)), 1.0 + i, 2.0 + i, 0.5, 1.5 + i, 100, 0.0)
        for i in range(hours)
    ]


def test_daily_buckets_on_utc_midnight():
    start = datetime(2026, 1, 12, 0, 0, tzinfo=UTC)
    daily = resample(_h1(start, 72), "daily", 0)

    assert [b.time_ms for b in daily] == [_ms(start + timedelta(days=d)) for d in range(3)]
    assert daily[0].volume == 24 * 100


def test_4h_buckets_on_utc_quarter_boundaries():
    start = datetime(2026, 8, 16, 0, 0, tzinfo=UTC)
    bars = resample(_h1(start, 48), "4h", 0)

    expected = [start + timedelta(hours=h) for h in range(0, 48, 4)]
    assert [b.time_ms for b in bars] == [_ms(t) for t in expected]
    assert bars[0].volume == 4 * 100


def test_4h_boundaries_are_lineup_across_dst_dates():
    # UTC 无 DST：3 月与 8 月同一批 H1 分桶边界结构完全一致（00/04/08/12/16/20）
    for start in (
        datetime(2026, 3, 28, 0, 0, tzinfo=UTC),
        datetime(2026, 8, 16, 0, 0, tzinfo=UTC),
    ):
        bars = resample(_h1(start, 24), "4h", 0)
        assert [b.time_ms for b in bars] == [
            _ms(start + timedelta(hours=h)) for h in (0, 4, 8, 12, 16, 20)
        ]


def test_daily_volume_covers_full_utc_day():
    start = datetime(2026, 1, 11, 22, 0, tzinfo=UTC)
    daily = resample(_h1(start, 48), "daily", 0)

    # 前两根各含 2 小时 / 24 小时；末根只有 22 小时（序列未到当日 24:00）
    assert daily[0].volume == 2 * 100
    assert daily[0].time_ms == _ms(datetime(2026, 1, 11, 0, 0, tzinfo=UTC))
    assert daily[1].time_ms == _ms(datetime(2026, 1, 12, 0, 0, tzinfo=UTC))
    assert daily[1].volume == 24 * 100


def test_weekly_buckets_on_monday_utc():
    first_monday = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    daily_bars = [
        Bar(_ms(first_monday + timedelta(days=d)), 1.0, 2.0, 0.5, 1.5, 100, 0.0)
        for d in range(21)
    ]
    weekly = resample(daily_bars, "weekly", 0)

    assert [b.time_ms for b in weekly] == [
        _ms(first_monday + timedelta(weeks=w)) for w in range(3)
    ]
    assert weekly[0].volume == 700


def test_monthly_buckets_on_first_utc_day():
    jan = datetime(2026, 1, 15, 0, 0, tzinfo=UTC)
    feb = datetime(2026, 2, 15, 0, 0, tzinfo=UTC)
    monthly = resample(
        [
            Bar(_ms(jan), 1, 2, 0.5, 1.5, 10, 0),
            Bar(_ms(feb), 1, 2, 0.5, 1.5, 20, 0),
        ],
        "monthly",
        0,
    )

    assert len(monthly) == 2
    assert monthly[0].time_ms == _ms(datetime(2026, 1, 1, 0, 0, tzinfo=UTC))
    assert monthly[1].time_ms == _ms(datetime(2026, 2, 1, 0, 0, tzinfo=UTC))
    assert monthly[0].volume == 10
    assert monthly[1].volume == 20


def test_server_offset_shifts_output_to_utc():
    # 服务器领先 UTC 120 分钟：服务器 00:00 → UTC 前一日 22:00，落入前一日 UTC 桶
    server_midnight = datetime(2026, 8, 17, 0, 0, tzinfo=UTC)
    bars = [Bar(_ms(server_midnight), 1, 2, 0.5, 1.5, 100, 0)]
    daily = resample(bars, "daily", 120)

    assert daily[0].time_ms == _ms(datetime(2026, 8, 16, 0, 0, tzinfo=UTC))


def test_server_to_utc_ms_negative_offset():
    assert server_to_utc_ms(1_000, 0) == 1_000
    assert server_to_utc_ms(1_000, 120) == 1_000 - 120 * 60_000
    assert server_to_utc_ms(1_000, -60) == 1_000 + 60 * 60_000


# ── merge_sunday_bars：Exness 周日短棒并入周一（传统欧洲口径）──


def _daily(ts: datetime, o: float, c: float, volume: float = 100.0) -> Bar:
    return Bar(_ms(ts), o, max(o, c) + 5, min(o, c) - 5, c, volume, 0.0)


class TestMergeSundayBars:
    def _sunday(self, day: int, month: int = 3, o: float = 10.0, c: float = 10.5, volume: float = 5.0) -> Bar:
        # 2026-03 的周日均为 UTC 周日
        return _daily(datetime(2026, 3, day, 0, 0, tzinfo=UTC), o, c, volume=5.0)

    def test_sunday_merges_into_next_monday(self):
        bars = [
            self._sunday(8, o=10.0, c=10.5, volume=5.0),   # UTC 周日短棒
            _daily(datetime(2026, 3, 9, 0, 0, tzinfo=UTC), 11.0, 12.0, volume=300.0),  # 周一
        ]
        merged = merge_sunday_bars(bars)
        assert len(merged) == 1
        assert merged[0].time_ms == bars[1].time_ms
        assert merged[0].open == 10.0      # 周日 open 为合并后 open
        assert merged[0].high == 17.0      # max(10+5, 12+5)
        assert merged[0].low == 5.0        # min(10-5, 12-5)
        assert merged[0].close == 12.0     # 周一 close 为合并后 close
        assert merged[0].volume == 305.0   # volume 相加

    def test_sequence_without_sunday_is_noop(self):
        bars = [
            _daily(datetime(2026, 3, 9, 0, 0, tzinfo=UTC), 11.0, 12.0),
            _daily(datetime(2026, 3, 10, 0, 0, tzinfo=UTC), 12.0, 13.0),
        ]
        assert merge_sunday_bars(bars) == bars

    def test_trailing_sunday_is_preserved(self):
        # 末尾孤立周日（周一尚未产生）：保留原样，不丢弃
        bars = [
            _daily(datetime(2026, 3, 9, 0, 0, tzinfo=UTC), 11.0, 12.0),
            self._sunday(15, o=10.0, c=10.5),
        ]
        merged = merge_sunday_bars(bars)
        assert len(merged) == 2
        assert merged[1] == bars[1]

    def test_weekly_series_sunday_followed_by_next_week_is_noop(self):
        # 周线序列：周日 bar 的下一根是下周 bar（非周一），不合并
        bars = [
            _daily(datetime(2026, 3, 8, 0, 0, tzinfo=UTC), 10.0, 10.5),   # 周日
            _daily(datetime(2026, 3, 15, 0, 0, tzinfo=UTC), 11.0, 12.0),  # 下周日
        ]
        assert merge_sunday_bars(bars) == bars
