# V1 行情协议路由：probe / instruments/search / bars + SSE 实时帧端点。
# 响应统一 {data, requestId} envelope；错误统一 {error:{code,message}, requestId}。

from __future__ import annotations

import asyncio
import json
import math
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import align
from .aggregator import Aggregator
from .bar_aggregation import (
    ALIGNED_BAR_AGGREGATION,
    BarAggregation,
    BAR_AGGREGATIONS,
    EUROPE_TRADITIONAL_BAR_AGGREGATION,
    ORIGINAL_BAR_AGGREGATION,
)
from .clock import ServerClock
from .config import Settings
from .frames import Bar, frame_payload
from .gateway import Mt5Gateway
from .hub import RingEntry, StreamHub
from .symbols import ASSET_CLASSES, guess_asset_class, search_symbols
from .ticks import TickAggregator, tick_stream_key

SOURCE_ID = "mt5"
SUPPORTED_PERIODS = ("1min", "5min", "15min", "30min", "60min", "4h", "daily", "weekly", "monthly")
SUPPORTED_ADJUSTMENTS = ("none",)
MAX_BAR_LIMIT = 1000
# 请求窗口在服务器时间轴上的前置余量（毫秒）：覆盖周末缺口与重采样桶跨度
RANGE_MARGIN_MS = 48 * 3600 * 1000
# exhausted 判定的窗口覆盖占比阈值：实际根数覆盖时间 < 名义跨度的 50% 才认为见底。
# 24/5 市场周末闭市占 28%、日内低流动性缺口约 2%、节假日约 5%，正常连续数据
# 的覆盖占比约 70%；取 0.5 留足余量，兼顾 24/7（占比 ~100%）与节假日密集市场。
MIN_WINDOW_COVERAGE_RATIO = 0.5

_PERIOD_SECONDS = {
    "1min": 60, "5min": 300, "15min": 900, "30min": 1800,
    "60min": 3600, "4h": 14400, "daily": 86400, "weekly": 604800, "monthly": 2592000,
}

router = APIRouter(prefix="/api/v1/market-data")


def _request_id() -> str:
    """生成短请求追踪 ID。"""
    return uuid.uuid4().hex[:12]


def _ok(data: dict) -> dict:
    """成功 envelope。"""
    return {"data": data, "requestId": _request_id()}


def _error(code: str, message: str, status_code: int) -> JSONResponse:
    """错误 envelope（HTTP 状态码与协议错误码对齐 V1 约定）。"""
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}, "requestId": _request_id()},
    )


def _alignment_enabled(settings: Settings) -> bool:
    """对齐开关（与 aggregator 同一规则）：off 关，其余对齐到 UTC。"""
    return settings.align_mode != "off"


# ── 请求模型 ──


class SearchRequest(BaseModel):
    """品种搜索请求体。"""

    sourceId: str
    keyword: str = Field(min_length=1, max_length=128)
    limit: int = Field(ge=1, le=100)
    assetClasses: list[str] | None = None


class InstrumentReference(BaseModel):
    """品种身份引用（客户端原样带回）。"""

    id: str
    symbol: str
    exchange: str | None = None
    providerRef: dict[str, str | float | bool] | None = None


class BarRequest(BaseModel):
    """K 线请求体（游标分页）。"""

    sourceId: str
    instrument: InstrumentReference
    period: str
    adjustment: str = "none"
    limit: int = Field(default=300, ge=1, le=MAX_BAR_LIMIT)
    beforeTimestamp: int | None = None
    barAggregation: BarAggregation | None = None


class TradingCalendarRequest(BaseModel):
    """未来交易日历请求体（V1 协议：未来槽位时间戳的唯一权威来源）。"""

    sourceId: str
    instrument: InstrumentReference
    period: str
    adjustment: str = "none"
    barAggregation: BarAggregation | None = None
    anchorTimestamp: int = Field(ge=0)
    count: int = Field(ge=1, le=1000)


# ── probe ──


@router.get("/sources/mt5/probe")
async def probe(request: Request) -> dict:
    """探测数据源：终端连接状态 + 对齐状态 + 源级能力。"""
    state = request.app.state
    gateway: Mt5Gateway = state.gateway
    clock: ServerClock = state.clock
    settings: Settings = state.settings
    started = time.monotonic()

    try:
        summary = await gateway.terminal_summary()
        status = "online" if summary.get("connected") else "degraded"
        message = ""
    except Exception as exc:  # noqa: BLE001 — probe 失败即离线，不抛 500
        summary = {}
        status = "offline"
        message = str(exc)

    aligned = _alignment_enabled(settings) if status != "offline" else False
    anchor_label = "UTC"

    # 状态补充说明：离线时是诊断原因，在线时是对齐摘要（前端聚合源管理直接展示）
    if status == "offline":
        pass
    elif not aligned:
        message = "对齐关闭（原生周期）"
    else:
        offset = clock.offset_minutes()
        source_kind = "实测" if clock.is_measured() else "默认"
        if settings.server_utc_offset_override is not None:
            source_kind = "配置"
        offset_hours = offset / 60
        offset_text = f"{offset_hours:+g}h" if offset % 60 == 0 else f"{offset}min"
        message = f"对齐 {anchor_label} · 偏移 {offset_text}（{source_kind}）"

    return _ok(
        {
            "status": status,
            "checkedAt": int(time.time() * 1000),
            "latencyMs": round((time.monotonic() - started) * 1000, 1),
            "message": message,
            "alignment": {
                "enabled": aligned,
                "anchor": anchor_label if aligned else "off",
                "serverOffsetMinutes": clock.offset_minutes() if status != "offline" else None,
                "offsetMeasured": clock.is_measured() if status != "offline" else False,
            },
            # 品牌默认口径：Exness 终端默认修正周日短棒，下游不传 barAggregation 即得修正后序列
            "defaultBarAggregation": (
                EUROPE_TRADITIONAL_BAR_AGGREGATION
                if getattr(gateway, "is_exness", False)
                else ORIGINAL_BAR_AGGREGATION
            ),
            # capabilities 是前端 SourceRouter 的流转筛选依据，必须随 probe 上报
            "capabilities": {
                "assetClasses": list(ASSET_CLASSES),
                "bars": {"periods": list(SUPPORTED_PERIODS), "adjustments": list(SUPPORTED_ADJUSTMENTS), "barAggregations": list(BAR_AGGREGATIONS)},
                # 实时 K 线能力：/stream 对全部已声明周期提供 SSE 推送，供前端精确判定，
                # 不再用 marketTicks 等相邻能力推断
                "liveBars": True,
                # 未来槽位时间戳：/trading-calendar 端点提供（crypto 24/7 线性、
                # 传统资产跳周末），引擎据此渲染未来区真实时刻取代 T+n 相对标签
                "tradingCalendar": True,
            },
        }
    )


# ── instruments/search ──


@router.post("/instruments/search")
async def search_instruments(body: SearchRequest, request: Request):
    """搜索终端品种目录：代码/描述子串匹配。"""
    gateway: Mt5Gateway = request.app.state.gateway
    if body.sourceId != SOURCE_ID:
        return _error("INVALID_REQUEST", f"unknown sourceId: {body.sourceId}", 400)
    invalid = [cls for cls in (body.assetClasses or []) if cls not in ASSET_CLASSES]
    if invalid:
        return _error("INVALID_REQUEST", f"unknown assetClasses: {invalid}", 400)
    try:
        catalog = await gateway.symbols()
    except Exception as exc:  # noqa: BLE001 — 终端不可用统一 502
        return _error("UPSTREAM_UNAVAILABLE", str(exc), 502)

    matched = search_symbols(catalog, body.keyword, body.limit, body.assetClasses)
    items = [_descriptor(meta) for meta in matched]
    return _ok({"items": items})


def _descriptor(meta) -> dict:
    """SymbolMeta → V1 InstrumentDescriptor。"""
    item: dict = {
        "id": f"{SOURCE_ID}:{meta.name}",
        "sourceId": SOURCE_ID,
        "symbol": meta.name,
        "name": meta.description or meta.name,
        "assetClass": guess_asset_class(meta.name),
        "exchange": "MT5",
        "sessionId": "MT5",
        "providerRef": {"symbol": meta.name},
        "capabilities": {
            "bars": {"periods": list(SUPPORTED_PERIODS), "adjustments": list(SUPPORTED_ADJUSTMENTS)},
            "tradingCalendar": True,
        },
    }
    if meta.currency:
        item["currency"] = meta.currency
    if meta.point > 0:
        item["tickSize"] = meta.point
    if meta.volume_min > 0:
        item["lotSize"] = meta.volume_min
    return item


# ── trading-calendar ──


def _is_trading_slot(ts_ms: int, crypto: bool) -> bool:
    """槽位是否为交易时段：crypto 24/7 全周；传统资产跳周六/周日（UTC 判定，
    轴显示口径与对齐锚一致；Exness 周日短棒按用户口径不建模）。"""
    if crypto:
        return True
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).weekday() < 5


@router.post("/trading-calendar")
async def trading_calendar(body: TradingCalendarRequest, request: Request):
    """未来槽位交易日历：从 anchor 起按周期步长外推 count 个未来时间戳。

    crypto 24/7 线性外推；传统资产跳周六/周日（周五收/周一开的精确时刻不
    建模——轴显示粒度足够，且与下游"周日短棒不入状态机"口径一致）。
    futureTimestamps 恒 ≤ count（引擎对超长响应整包丢弃）。
    """
    if body.sourceId != SOURCE_ID:
        return _error("INVALID_REQUEST", f"unknown sourceId: {body.sourceId}", 400)
    if body.period not in SUPPORTED_PERIODS:
        return _error("INVALID_REQUEST", f"unsupported period: {body.period}", 400)
    step_ms = _PERIOD_SECONDS[body.period] * 1000
    crypto = guess_asset_class(body.instrument.symbol) == "crypto"

    future: list[int] = []
    cursor = body.anchorTimestamp
    # 步进上限兜底：传统资产周末密度下 4×count 步内必凑满（防死循环）
    max_steps = body.count * 4 + 7
    steps = 0
    while len(future) < body.count and steps < max_steps:
        cursor += step_ms
        steps += 1
        if _is_trading_slot(cursor, crypto):
            future.append(cursor)
    return _ok({"anchorTimestamp": body.anchorTimestamp, "futureTimestamps": future})


# ── bars ──


@router.post("/bars")
async def fetch_bars(body: BarRequest, request: Request):
    """拉取 K 线：日内原生 + 偏移校正；4h/日/周/月对齐开启时重采样（H1/D1 源）。"""
    state = request.app.state
    gateway: Mt5Gateway = state.gateway
    clock: ServerClock = state.clock
    settings: Settings = state.settings

    if body.sourceId != SOURCE_ID:
        return _error("INVALID_REQUEST", f"unknown sourceId: {body.sourceId}", 400)
    if body.period not in SUPPORTED_PERIODS:
        return _error("UNSUPPORTED_CAPABILITY", f"unsupported period: {body.period}", 400)
    if body.adjustment not in SUPPORTED_ADJUSTMENTS:
        return _error("UNSUPPORTED_CAPABILITY", f"unsupported adjustment: {body.adjustment}", 400)

    try:
        offset = await clock.ensure_fresh()
        aggregation = _resolve_aggregation(gateway, body.barAggregation)
        if aggregation == ALIGNED_BAR_AGGREGATION and not _alignment_enabled(settings):
            return _error("UNSUPPORTED_CAPABILITY", "aligned bar aggregation is unavailable", 400)
        # europe-traditional：4h 自 H1 按 NY-close 日界聚合（对齐主流经纪商 4h 收线时间）；
        # daily 保留「原生透传 + 周日短棒并入周一」；其余周期原生透传不修正。
        # merge_sunday_bars 仅适用于日线序列——日内周期（1h/4h 等）周日/周一交界的
        # 相邻棒并入会破坏时间轴，禁止无差别套用。
        if aggregation == EUROPE_TRADITIONAL_BAR_AGGREGATION and body.period == "4h":
            bars = await _load_series(gateway, body, "ny_close", offset)
        else:
            mode = "utc" if aggregation == ALIGNED_BAR_AGGREGATION else "none"
            bars = await _load_series(gateway, body, mode, offset)
            if aggregation == EUROPE_TRADITIONAL_BAR_AGGREGATION and body.period == "daily":
                bars = align.merge_sunday_bars(bars)
    except Exception as exc:  # noqa: BLE001 — 终端/品种错误统一 502
        return _error("UPSTREAM_UNAVAILABLE", str(exc), 502)

    older = _resolve_older_status(bars, body)
    return _ok(
        {
            "instrumentId": body.instrument.id,
            "period": body.period,
            "adjustment": body.adjustment,
            "barAggregation": aggregation,
            "timezone": "UTC",
            "items": [
                {
                    "timestamp": bar.time_ms,
                    "open": bar.open,
                    "high": bar.high,
                    "low": bar.low,
                    "close": bar.close,
                    "volume": bar.volume,
                    "turnover": bar.turnover,
                }
                for bar in bars
            ],
            "olderData": older,
        }
    )


def _resolve_older_status(bars: list[Bar], body: BarRequest) -> str:
    """判定向前翻页是否还有更多数据（olderData 协议字段）。

    原实现 `len(bars) >= limit` 有一个市场数据特性缺陷：beforeTimestamp 模式的
    取数窗口跨度按「名义周期 × limit」计算，但周末闭市（24/5 市场每周约 49h）与
    日内低流动性缺口会让窗口内实际根数只约为名义值的 70%（如 XAUUSD H1 名义
    1000 根实际 ~730 根），导致每页都被误判为 exhausted，前端左缘增量加载在
    第一页后就停止，用户只能看到极浅的历史。

    修正语义：用「最早返回 bar 与游标的覆盖时间」占名义窗口跨度的比例判定——
    - 满页（>= limit）：必然 available。
    - 不满页：覆盖占比 > MIN_WINDOW_COVERAGE_RATIO（0.5，留足周末 28% +
      日内缺口 2% + 节假日 5% 的余量）说明窗口整体被真实数据填充、数据连续性
      只是市场休市所致，前方大概率还有更多 → available；
      占比 <= 0.5 或返回为空说明窗口已见底 → exhausted。
    无游标（首次请求）时不做窗口推断，维持原判定（copy_rates_from_pos 给不满
    limit 通常意味着终端历史确实见底）。
    """
    if len(bars) >= body.limit:
        return "available"
    if body.beforeTimestamp is None or not bars:
        return "exhausted"

    period_ms = _PERIOD_SECONDS[body.period] * 1000
    window_span_ms = body.limit * period_ms + RANGE_MARGIN_MS
    # bars 已转为真 UTC（_utc_bars），与 beforeTimestamp 同一时间轴，可直接比较。
    covered_ms = body.beforeTimestamp - bars[0].time_ms
    return "available" if covered_ms > window_span_ms * MIN_WINDOW_COVERAGE_RATIO else "exhausted"


def _utc_bars(raw: list[Bar], offset_minutes: int) -> list[Bar]:
    """服务器时间 Bar → 真 UTC Bar（原生周期仅做偏移平移）。"""
    return [
        Bar(
            time_ms=align.server_to_utc_ms(bar.time_ms, offset_minutes),
            open=bar.open, high=bar.high, low=bar.low,
            close=bar.close, volume=bar.volume, turnover=bar.turnover,
        )
        for bar in raw
    ]


def _resolve_aggregation(gateway: Mt5Gateway, value: BarAggregation | None) -> BarAggregation:
    """解析实际聚合口径：缺省时按品牌默认——Exness 默认 europe-traditional（底层修正周日短棒），其余 original。"""
    if value is not None:
        return value
    return (
        EUROPE_TRADITIONAL_BAR_AGGREGATION
        if getattr(gateway, "is_exness", False)
        else ORIGINAL_BAR_AGGREGATION
    )


async def _load_series(
    gateway: Mt5Gateway,
    body: BarRequest,
    resample_mode: str,
    offset: int,
) -> list[Bar]:
    """按重采样口径与游标组装最终序列（升序、末位为最新，最多 limit 根）。

    resample_mode："none"（原生周期透传）/"utc"（aligned，UTC 自然边界）/
    "ny_close"（europe-traditional 4h，纽约 17:00 日界自 H1 聚合）。
    """
    period = body.period
    limit = body.limit
    period_ms = _PERIOD_SECONDS[period] * 1000
    symbol = body.instrument.providerRef.get("symbol", body.instrument.symbol) if body.instrument.providerRef else body.instrument.symbol

    needs_resample = resample_mode != "none" and (
        period in align.RESAMPLE_H1_TARGETS or period in align.RESAMPLE_D1_TARGETS
    )
    if needs_resample:
        source_period = "60min" if period in align.RESAMPLE_H1_TARGETS else "daily"
        source_ms = _PERIOD_SECONDS[source_period] * 1000
        if body.beforeTimestamp is not None:
            span_ms = limit * period_ms + RANGE_MARGIN_MS
            raw = await gateway.copy_rates_range(
                symbol,
                source_period,
                body.beforeTimestamp + offset * 60_000 - span_ms,
                body.beforeTimestamp + offset * 60_000 - 1,
            )
        else:
            count = min(math.ceil(limit * period_ms / source_ms) + 48, 20_000)
            raw = await gateway.copy_rates_from_pos(symbol, source_period, count)
        series = align.resample(raw, period, offset, anchor=resample_mode)
        if body.beforeTimestamp is not None:
            series = [bar for bar in series if bar.time_ms < body.beforeTimestamp]
    else:
        if body.beforeTimestamp is not None:
            to_server_ms = body.beforeTimestamp + offset * 60_000 - 1
            from_server_ms = to_server_ms - (limit * period_ms + RANGE_MARGIN_MS)
            raw = await gateway.copy_rates_range(symbol, period, from_server_ms, to_server_ms)
        else:
            raw = await gateway.copy_rates_from_pos(symbol, period, limit)
        series = _utc_bars(raw, offset)

    return series[-limit:]


# ── SSE 实时流 ──


@router.get("/sources/mt5/stream")
async def stream(
    symbol: str,
    period: str,
    request: Request,
    barAggregation: BarAggregation | None = None,
):
    """单连接固定订阅一个 (symbol, period, barAggregation)；切换任一维度均断开重连。

    断线重连凭 Last-Event-ID 从环形缓冲补帧；无 ID 视为新订阅（下发快照）。
    """
    state = request.app.state
    if period not in SUPPORTED_PERIODS:
        return _error("UNSUPPORTED_CAPABILITY", f"unsupported period: {period}", 400)
    if not symbol.strip():
        return _error("INVALID_REQUEST", "symbol is required", 400)

    bar_aggregation = _resolve_aggregation(state.gateway, barAggregation)
    if bar_aggregation == ALIGNED_BAR_AGGREGATION and not _alignment_enabled(state.settings):
        return _error("UNSUPPORTED_CAPABILITY", "aligned bar aggregation is unavailable", 400)

    hub: StreamHub = state.hub
    aggregator: Aggregator = state.aggregator
    settings: Settings = state.settings
    # MT5 品种名大小写敏感，直接使用请求的品种名，不做大小写归一
    key = (symbol.strip(), period, bar_aggregation)

    last_id_raw = request.headers.get("last-event-id")
    last_id = int(last_id_raw) if last_id_raw and last_id_raw.isdigit() else None

    queue = hub.register(key)
    # 基准 seq 必须在 ensure()（触发快照发布）之前捕获，否则快照帧会被去重逻辑误跳过
    base_seq = last_id if last_id is not None else hub.last_seq(key)
    aggregator.ensure(key, resnapshot=last_id is None)

    async def event_stream():
        try:
            # 新订阅（无 Last-Event-ID）从当前位置开始，靠 resnapshot 快照同步；
            # 重连订阅凭 Last-Event-ID 补帧，重放与队列重叠按 seq 去重。
            last_sent = base_seq
            for entry in hub.replay(key, last_sent):
                last_sent = entry.seq
                yield _sse_chunk(entry)
            while True:
                try:
                    entry = await asyncio.wait_for(
                        queue.get(), timeout=settings.sse_keepalive_seconds
                    )
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if entry.seq <= last_sent:
                    continue  # 重放与队列重叠去重
                last_sent = entry.seq
                yield _sse_chunk(entry)
        finally:
            hub.unregister(key, queue)
            aggregator.release(key)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


@router.get("/sources/mt5/ticks/stream")
async def ticks_stream(symbol: str, request: Request):
    """单连接固定订阅一个 symbol 的逐笔 tick 流；tick 与 period / barAggregation 无关。

    新订阅只推送建立之后的 tick；断线重连凭 Last-Event-ID 从环形缓冲补帧。
    """
    state = request.app.state
    if not symbol.strip():
        return _error("INVALID_REQUEST", "symbol is required", 400)

    hub: StreamHub = state.hub
    tick_aggregator: TickAggregator = state.tick_aggregator
    settings: Settings = state.settings
    # MT5 品种名大小写敏感，直接使用请求的品种名，不做大小写归一
    normalized = symbol.strip()
    key = tick_stream_key(normalized)

    last_id_raw = request.headers.get("last-event-id")
    last_id = int(last_id_raw) if last_id_raw and last_id_raw.isdigit() else None

    queue = hub.register(key)
    # 新订阅从当前位置开始（tick 无历史快照）；重连凭 Last-Event-ID 补帧
    base_seq = last_id if last_id is not None else hub.last_seq(key)
    tick_aggregator.ensure(normalized)

    async def event_stream():
        try:
            last_sent = base_seq
            for entry in hub.replay(key, last_sent):
                last_sent = entry.seq
                yield _sse_chunk(entry)
            while True:
                try:
                    entry = await asyncio.wait_for(
                        queue.get(), timeout=settings.sse_keepalive_seconds
                    )
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if entry.seq <= last_sent:
                    continue  # 重放与队列重叠去重
                last_sent = entry.seq
                yield _sse_chunk(entry)
        finally:
            hub.unregister(key, queue)
            tick_aggregator.release(normalized)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    }
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)


def _sse_chunk(entry: RingEntry) -> str:
    """帧 → SSE 报文（id 供 Last-Event-ID 重放）。"""
    payload = json.dumps(frame_payload(entry.frame), ensure_ascii=False)
    return f"id: {entry.seq}\ndata: {payload}\n\n"
