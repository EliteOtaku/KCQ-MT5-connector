# 对齐重采样语义测试：UTC 4h/日线/周/月桶边界、跨月跨周归属、偏移校正。
# 锚恒为 UTC，不随品种类别或环境配置变化。

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.align import resample, server_to_utc_ms
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
