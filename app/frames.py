# K 线与实时帧的数据模型：aggregator/hub/routes 共用，禁止各处重复定义。

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Bar:
    """单根 K 线；time_ms 语义由调用方约定（网关返回=服务器伪 UTC，对齐输出=真 UTC）。"""

    time_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    turnover: float = 0.0


@dataclass(frozen=True, slots=True)
class SnapshotFrame:
    """订阅建立时的尾部快照（含最后一根收线与当前 forming）。"""

    symbol: str
    period: str
    bars: tuple[Bar, ...]


@dataclass(frozen=True, slots=True)
class FormingFrame:
    """forming bar 内容更新（时间戳不变、OHLCV 变化）。"""

    symbol: str
    period: str
    bar: Bar


@dataclass(frozen=True, slots=True)
class ClosedFrame:
    """一根 bar 收线（openTime 前移后旧根终值，含终端缓存滞后的修订）。"""

    symbol: str
    period: str
    bar: Bar


@dataclass(frozen=True, slots=True)
class StatusFrame:
    """流级状态变化（行情开闭/连接异常），不携带 bar。"""

    symbol: str
    period: str
    status: str
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Tick:
    """单笔逐笔 tick；time_ms 语义由调用方约定（网关返回=服务器伪 UTC，推送=真 UTC）。"""

    time_ms: int
    bid: float
    ask: float
    last: float
    volume: float


@dataclass(frozen=True, slots=True)
class TicksFrame:
    """一批逐笔 tick 推送（同一采样窗口内按时间升序合并，不丢中间 tick）。"""

    symbol: str
    ticks: tuple[Tick, ...]


# 帧联合类型别名
Frame = SnapshotFrame | FormingFrame | ClosedFrame | StatusFrame | TicksFrame


def frame_type(frame: Frame) -> str:
    """返回帧协议类型名（SSE 载荷 type 字段）。"""
    match frame:
        case SnapshotFrame():
            return "snapshot"
        case FormingFrame():
            return "forming"
        case ClosedFrame():
            return "closed"
        case StatusFrame():
            return "status"
        case TicksFrame():
            return "ticks"
    raise TypeError(f"unknown frame: {frame!r}")


def frame_payload(frame: Frame) -> dict[str, object]:
    """把帧序列化为 JSON 载荷（bar 字段展平为 V1 KLineItem 形状）。"""
    match frame:
        case SnapshotFrame(symbol, period, bars):
            return {
                "type": "snapshot",
                "symbol": symbol,
                "period": period,
                "bars": [bar_to_dict(bar) for bar in bars],
            }
        case FormingFrame(symbol, period, bar):
            return {"type": "forming", "symbol": symbol, "period": period, "bar": bar_to_dict(bar)}
        case ClosedFrame(symbol, period, bar):
            return {"type": "closed", "symbol": symbol, "period": period, "bar": bar_to_dict(bar)}
        case StatusFrame(symbol, period, status, detail):
            return {
                "type": "status",
                "symbol": symbol,
                "period": period,
                "status": status,
                "detail": detail,
            }
        case TicksFrame(symbol, ticks):
            return {
                "type": "ticks",
                "symbol": symbol,
                "ticks": [tick_to_dict(tick) for tick in ticks],
            }
    raise TypeError(f"unknown frame: {frame!r}")


def bar_to_dict(bar: Bar) -> dict[str, float | int]:
    """Bar 转 V1 KLineItem 字典（时间戳为 UTC 毫秒）。"""
    return {
        "timestamp": bar.time_ms,
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
        "turnover": bar.turnover,
    }


def tick_to_dict(tick: Tick) -> dict[str, float | int]:
    """Tick 转逐笔字典（timestamp 为真 UTC 毫秒）。"""
    return {
        "timestamp": tick.time_ms,
        "bid": tick.bid,
        "ask": tick.ask,
        "last": tick.last,
        "volume": tick.volume,
    }
