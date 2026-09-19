# V1 路由测试：probe/搜索/bars 的 envelope 形状、对齐重采样映射、错误码与 SSE 首帧。

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.frames import Bar
from app.main import create_app
from conftest import FakeGateway
from fastapi.testclient import TestClient

UTC = timezone.utc


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _h1(start: datetime, hours: int) -> list[Bar]:
    return [
        Bar(_ms(start + timedelta(hours=i)), 1.0 + i, 2.0 + i, 0.5, 1.5 + i, 100, 0.0)
        for i in range(hours)
    ]


def test_probe_reports_online_with_alignment(client: TestClient):
    resp = client.get("/api/v1/market-data/sources/mt5/probe")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "online"
    assert body["data"]["alignment"]["enabled"] is True  # 默认对齐开启（UTC）
    assert body["data"]["alignment"]["anchor"] == "UTC"
    assert body["data"]["capabilities"]["bars"]["periods"][0] == "1min"
    assert "requestId" in body


def test_probe_offline_when_terminal_unavailable(fake_gateway: FakeGateway):
    fake_gateway.connected = False
    app = create_app(settings=Settings(), gateway=fake_gateway)
    with TestClient(app) as offline_client:
        resp = offline_client.get("/api/v1/market-data/sources/mt5/probe")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["status"] == "offline"
    assert body["data"]["alignment"]["enabled"] is False


def test_search_returns_instrument_descriptors(client: TestClient):
    resp = client.post(
        "/api/v1/market-data/instruments/search",
        json={"sourceId": "mt5", "keyword": "gold", "limit": 10},
    )

    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert len(items) == 1
    item = items[0]
    assert item["symbol"] == "XAUUSD"
    assert item["sourceId"] == "mt5"
    assert item["sessionId"] == "MT5"
    assert item["assetClass"] == "forex"
    assert item["providerRef"] == {"symbol": "XAUUSD"}
    assert "4h" in item["capabilities"]["bars"]["periods"]


def test_search_rejects_unknown_asset_class(client: TestClient):
    resp = client.post(
        "/api/v1/market-data/instruments/search",
        json={"sourceId": "mt5", "keyword": "x", "limit": 5, "assetClasses": ["commodity"]},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_REQUEST"


def test_bars_native_period_applies_measured_offset(fake_gateway: FakeGateway):
    # 服务器领先 UTC 2h：tick 时间 = now-2h → 实测偏移 +120min
    fake_gateway.tick_offset_seconds = 7200
    start = datetime(2026, 8, 17, 0, 0, tzinfo=UTC)
    fake_gateway.rates[("EURUSD", "60min")] = _h1(start, 5)
    app = create_app(settings=Settings(), gateway=fake_gateway)
    with TestClient(app) as offset_client:
        resp = offset_client.post(
            "/api/v1/market-data/bars",
            json={
                "sourceId": "mt5",
                "instrument": {"id": "mt5:EURUSD", "symbol": "EURUSD", "exchange": "MT5"},
                "period": "60min",
                "adjustment": "none",
                "barAggregation": "original",
                "limit": 10,
            },
        )

    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    # 服务器 00:00 → UTC 前日 22:00
    assert items[0]["timestamp"] == _ms(datetime(2026, 8, 16, 22, 0, tzinfo=UTC))
    assert resp.json()["data"]["timezone"] == "UTC"
    assert resp.json()["data"]["olderData"] == "exhausted"


def test_bars_daily_aligned_resamples_on_utc_boundary(fake_gateway: FakeGateway):
    # 对齐开启：daily 自 H1 按 UTC 自然日重采样
    start = datetime(2026, 8, 16, 0, 0, tzinfo=UTC)
    fake_gateway.rates[("XAUUSD", "60min")] = _h1(start, 72)
    app = create_app(settings=Settings(), gateway=fake_gateway)
    with TestClient(app) as daily_client:
        resp = daily_client.post(
            "/api/v1/market-data/bars",
            json={
                "sourceId": "mt5",
                "instrument": {"id": "mt5:XAUUSD", "symbol": "XAUUSD", "exchange": "MT5"},
                "period": "daily",
                "adjustment": "none",
                "barAggregation": "aligned",
                "limit": 10,
            },
        )

    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    assert [item["timestamp"] for item in items] == [
        _ms(start + timedelta(days=d)) for d in range(3)
    ]
    assert items[0]["volume"] == 24 * 100


def test_bars_rejects_aligned_when_alignment_disabled(fake_gateway: FakeGateway):
    app = create_app(settings=Settings(align_mode="off"), gateway=fake_gateway)
    with TestClient(app) as off_client:
        resp = off_client.post(
            "/api/v1/market-data/bars",
            json={
                "sourceId": "mt5",
                "instrument": {"id": "mt5:XAUUSD", "symbol": "XAUUSD", "exchange": "MT5"},
                "period": "daily",
                "adjustment": "none",
                "barAggregation": "aligned",
                "limit": 10,
            },
        )
        probe = off_client.get("/api/v1/market-data/sources/mt5/probe")

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UNSUPPORTED_CAPABILITY"
    assert probe.json()["data"]["alignment"]["anchor"] == "off"


def test_bars_rejects_unsupported_period_and_adjustment(client: TestClient):
    base = {
        "sourceId": "mt5",
        "instrument": {"id": "mt5:XAUUSD", "symbol": "XAUUSD", "exchange": "MT5"},
        "adjustment": "none",
        "barAggregation": "original",
        "limit": 10,
    }
    resp_period = client.post(
        "/api/v1/market-data/bars", json={**base, "period": "quarterly"}
    )
    assert resp_period.status_code == 400
    assert resp_period.json()["error"]["code"] == "UNSUPPORTED_CAPABILITY"

    resp_adj = client.post(
        "/api/v1/market-data/bars", json={**base, "period": "daily", "adjustment": "qfq"}
    )
    assert resp_adj.status_code == 400
    assert resp_adj.json()["error"]["code"] == "UNSUPPORTED_CAPABILITY"


def test_bars_before_timestamp_pagination(fake_gateway: FakeGateway):
    start = datetime(2026, 8, 10, 0, 0, tzinfo=UTC)
    fake_gateway.rates[("EURUSD", "60min")] = _h1(start, 48)
    app = create_app(settings=Settings(align_mode="off"), gateway=fake_gateway)
    with TestClient(app) as page_client:
        resp = page_client.post(
            "/api/v1/market-data/bars",
            json={
                "sourceId": "mt5",
                "instrument": {"id": "mt5:EURUSD", "symbol": "EURUSD", "exchange": "MT5"},
                "period": "60min",
                "adjustment": "none",
                "barAggregation": "original",
                "limit": 2,
                "beforeTimestamp": _ms(datetime(2026, 8, 11, 6, 0, tzinfo=UTC)),
            },
        )

    assert resp.status_code == 200
    items = resp.json()["data"]["items"]
    # 排他上界：最后一根 open < 8/11 06:00，取 2 根
    assert [item["timestamp"] for item in items] == [
        _ms(datetime(2026, 8, 11, 4, 0, tzinfo=UTC)),
        _ms(datetime(2026, 8, 11, 5, 0, tzinfo=UTC)),
    ]


def test_stream_emits_snapshot_frame(fake_gateway: FakeGateway):
    start = datetime(2026, 8, 17, 0, 0, tzinfo=UTC)
    fake_gateway.rates[("XAUUSD", "60min")] = _h1(start, 5)
    app = create_app(settings=Settings(), gateway=fake_gateway)
    start_msg, body = asyncio.run(_first_sse_chunk(app))

    headers = {k.decode().lower(): v.decode() for k, v in start_msg["headers"]}
    assert headers["x-accel-buffering"] == "no"
    assert headers["content-type"].startswith("text/event-stream")
    first_line, data_line = body.split("\n")[:2]
    assert first_line.startswith("id: ")
    payload = json.loads(data_line[len("data: "):])
    assert payload["type"] == "snapshot"
    assert payload["symbol"] == "XAUUSD"
    assert len(payload["bars"]) == 2  # 快照含收线 + forming 尾部两根


async def _first_sse_chunk(app):
    """裸 ASGI 调用消费 SSE 首个数据块后取消连接（TestClient/ASGITransport 不支持无限流）。"""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v1/market-data/sources/mt5/stream",
        "raw_path": b"/api/v1/market-data/sources/mt5/stream",
        "query_string": b"symbol=XAUUSD&period=60min&barAggregation=original",
        "root_path": "",
        "server": ("test", 80),
        "client": ("test", 1234),
        "headers": [(b"host", b"test")],
    }

    async def receive():
        # 真实服务器中 receive 会挂起直到断连；立即返回会让
        # listen_for_disconnect 忙转饿死事件循环（无挂起点）。
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    events: list[dict] = []
    first_body = asyncio.Event()

    async def send(message):
        if message["type"] == "http.response.start":
            events.append(message)
        elif message["type"] == "http.response.body" and message.get("body"):
            events.append(message)
            text = message["body"].decode()
            # 状态帧可能先于快照发出，读到 snapshot 数据行为止
            if '"type": "snapshot"' in text or '"type":"snapshot"' in text:
                first_body.set()

    async with app.router.lifespan_context(app):
        task = asyncio.create_task(app(scope, receive, send))
        await asyncio.wait_for(first_body.wait(), timeout=5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    start_msg = next(m for m in events if m["type"] == "http.response.start")
    snapshot_msg = next(
        m
        for m in events
        if m["type"] == "http.response.body" and b"snapshot" in m.get("body", b"")
    )
    return start_msg, snapshot_msg["body"].decode()


def test_stream_rejects_unsupported_period(client: TestClient):
    resp = client.get(
        "/api/v1/market-data/sources/mt5/stream",
        params={"symbol": "XAUUSD", "period": "yearly", "barAggregation": "original"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UNSUPPORTED_CAPABILITY"
