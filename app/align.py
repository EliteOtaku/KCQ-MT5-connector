# 时区对齐纯函数：4h/日线自 H1、周/月自 D1 重采样（无 MT5 依赖，pytest 直接覆盖）。
#
# 锚规则（对齐决策）：
# - aligned 口径锚恒为 UTC，不随品种类别或环境配置变化。
#   券商服务器时区是发布渠道的私有约定，属于需要换算掉的噪声，不是对齐目标。
# - europe-traditional 口径的 4h 使用 NY-close 锚（纽约 17:00 为日界，跟随美国 DST），
#   与主流外汇经纪商（GMT+2/+3 New York close 服务器时间）的 4h 边界对齐；
#   日级仍为「UTC 日线透传 + 周日短棒并入周一」（merge_sunday_bars）。

from __future__ import annotations

import datetime

from datetime import timezone
from zoneinfo import ZoneInfo

import pandas as pd

from .frames import Bar

# 支持对齐重采样的目标周期：4h/日线取自 H1，周/月取自 D1
RESAMPLE_H1_TARGETS = frozenset({"4h", "daily"})
RESAMPLE_D1_TARGETS = frozenset({"weekly", "monthly"})

# NY-close 锚当前支持的目标周期（日界 = 纽约 17:00，跟随美国夏令时）
RESAMPLE_NY_CLOSE_TARGETS = frozenset({"4h"})

_NY_TZ = ZoneInfo("America/New_York")


def server_to_utc_ms(server_ms: int, offset_minutes: int) -> int:
    """服务器伪 UTC 毫秒 → 真 UTC 毫秒（offset 为服务器领先 UTC 的分钟数）。"""
    return int(server_ms) - offset_minutes * 60_000


def _bin_starts(index_utc: pd.DatetimeIndex, target: str) -> pd.DatetimeIndex:
    """计算每个 UTC 样本所属桶的起始时刻（naive UTC）。

    - daily：自然日 00:00；4h：自然日 + hour//4*4 时段
    - weekly：ISO 周锚（周一 00:00）；monthly：自然月 1 日 00:00
    """
    local = index_utc.tz_convert(timezone.utc).tz_localize(None)
    if target == "daily":
        return local.normalize()
    if target == "4h":
        return local.normalize() + pd.to_timedelta(local.hour // 4 * 4, unit="h")
    if target == "weekly":
        return local.normalize() - pd.to_timedelta(local.weekday, unit="D")
    if target == "monthly":
        return local.to_period("M").start_time
    raise ValueError(f"unsupported resample target: {target!r}")


def _ny_close_bin_starts_4h(index_utc: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """NY-close 口径 4h 分桶：纽约 17:00 为日界，自日界起每 4 小时一桶。

    全程 tz-aware 域运算（无 naive localize 歧义）：样本换算纽约墙钟判定日归属
    （17:00 前属前一交易日），锚 + 槽序在绝对时间域计算。槽加法为墙钟语义——
    DST 切换日的 UTC 桶宽自然突变 ±1h，与传统经纪商服务器墙钟行为一致。
    """
    ny = index_utc.tz_convert(_NY_TZ)
    before_anchor = (ny.hour < 17).astype(int)
    anchor = ny.normalize() + pd.Timedelta(hours=17) - pd.to_timedelta(before_anchor, unit="D")
    slot = anchor + pd.to_timedelta(
        ((ny - anchor) // pd.Timedelta(hours=4)).astype(int) * 4, unit="h"
    )
    return slot.tz_convert(timezone.utc).tz_localize(None)


def resample(
    bars: list[Bar], target: str, offset_minutes: int, anchor: str = "utc"
) -> list[Bar]:
    """把服务器时间 H1/D1 序列重采样为 4h/daily/weekly/monthly，输出真 UTC Bar。

    输入必须升序；输出时间戳为桶边界毫秒（naive UTC 墙钟），OHLCV 按桶聚合。
    anchor="utc"（默认）按 UTC 自然边界；anchor="ny_close" 按纽约 17:00 日界
    （仅 4h，europe-traditional 口径对齐主流经纪商 4h 收线时间）。
    """
    if not bars:
        return []
    if anchor == "ny_close":
        if target not in RESAMPLE_NY_CLOSE_TARGETS:
            raise ValueError(f"ny_close anchor unsupported target: {target!r}")
        bin_starts = _ny_close_bin_starts_4h
    elif anchor == "utc":
        bin_starts = lambda idx: _bin_starts(idx, target)  # noqa: E731 — 逐锚点分派
    else:
        raise ValueError(f"unsupported resample anchor: {anchor!r}")

    index_utc = pd.DatetimeIndex(
        pd.to_datetime(
            [server_to_utc_ms(b.time_ms, offset_minutes) for b in bars], unit="ms", utc=True
        )
    )
    frame = pd.DataFrame(
        {
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
            "turnover": [b.turnover for b in bars],
        },
        index=index_utc,
    ).sort_index()

    grouped = frame.groupby(bin_starts(index_utc)).agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        turnover=("turnover", "sum"),
    )
    # 桶起始已是 UTC 墙钟（naive）；UTC 无 DST，不存在边界落在切换窗的问题。
    # pandas 2.x：tz-aware 索引不能直接 astype 数值/naive，先去 tz 再统一 ns 精度取整。
    starts_utc_ns = (
        grouped.index.tz_localize("UTC").tz_convert("UTC").tz_localize(None)
    ).astype("datetime64[ns]").astype("int64")
    out_ms = starts_utc_ns // 10**6
    return [
        Bar(
            time_ms=int(out_ms[i]),
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            turnover=float(row["turnover"]),
        )
        for i, (_, row) in enumerate(grouped.iterrows())
    ]


def merge_sunday_bars(bars: list[Bar]) -> list[Bar]:
    """把 UTC 周日的日线短棒并入下一根周一（传统欧洲券商口径），其余序列原样。

    Exness 服务器时间恰为 UTC 时，周开盘（周日 22:00 UTC）之后的 2 小时数据
    会形成一根独立的周日日线（成交量仅为正常日线的约 5%），凭空占据一个 K 线位。
    传统欧洲券商口径下这 2 小时并入周一日线。非周日 bar 与序列末尾的孤立周日 bar
    保持原样；对不含周日 bar 的序列是 no-op。
    """
    if not bars:
        return []
    out: list[Bar] = []
    i = 0
    while i < len(bars):
        bar = bars[i]
        dt = datetime.datetime.fromtimestamp(bar.time_ms / 1000, tz=datetime.timezone.utc)
        if dt.weekday() == 6 and i + 1 < len(bars):
            nxt = bars[i + 1]
            ndt = datetime.datetime.fromtimestamp(nxt.time_ms / 1000, tz=datetime.timezone.utc)
            if ndt.weekday() == 0:
                out.append(
                    Bar(
                        time_ms=nxt.time_ms,
                        open=bar.open,
                        high=max(bar.high, nxt.high),
                        low=min(bar.low, nxt.low),
                        close=nxt.close,
                        volume=bar.volume + nxt.volume,
                        turnover=bar.turnover + nxt.turnover,
                    )
                )
                i += 2
                continue
        out.append(bar)
        i += 1
    return out
