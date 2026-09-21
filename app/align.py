# 时区对齐纯函数：4h/日线自 H1、周/月自 D1 按 UTC 自然边界重采样（无 MT5 依赖，pytest 直接覆盖）。
#
# 锚规则（对齐决策）：锚恒为 UTC，不随品种类别或环境配置变化。
# 券商服务器时区是发布渠道的私有约定，属于需要换算掉的噪声，不是对齐目标。

from __future__ import annotations

import datetime

from datetime import timezone

import pandas as pd

from .frames import Bar

# 支持对齐重采样的目标周期：4h/日线取自 H1，周/月取自 D1
RESAMPLE_H1_TARGETS = frozenset({"4h", "daily"})
RESAMPLE_D1_TARGETS = frozenset({"weekly", "monthly"})


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


def resample(bars: list[Bar], target: str, offset_minutes: int) -> list[Bar]:
    """把服务器时间 H1/D1 序列重采样为 4h/daily/weekly/monthly，输出真 UTC Bar。

    输入必须升序；输出时间戳为 UTC 桶边界毫秒，OHLCV 按桶聚合。
    """
    if not bars:
        return []

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

    grouped = frame.groupby(_bin_starts(index_utc, target)).agg(
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
