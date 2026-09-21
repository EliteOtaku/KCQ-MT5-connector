# 逐笔 tick 流测试：帧协议形状、SSE 首帧、服务器偏移换算与参数校验。
# SSE 用裸 ASGI 消费（TestClient 不支持无限流），receive 桩必须挂起避免饿死事件循环。

from __future__ import annotations

import asyncio
import json
import time

from app.config import Settings
from app.frames import Tick, TicksFrame, frame_payload, frame_type
from app.main import create_app
from conftest import FakeGateway
from fastapi.testclient import TestClient

_TICKS_PATH = "/api/v1/market-data/sources/mt5/ticks/stream"


def test_tick_frame_payload_shape():
    frame = TicksFrame("XAUUSD", (Tick(1000, 1.0, 1.1, 1.05, 2.0),))

    assert frame_type(frame) == "ticks"
    assert frame_payload(frame) == {
        "type": "ticks",
        "symbol": "XAUUSD",
        "ticks": [{"timestamp": 1000, "bid": 1.0, "ask": 1.1, "last": 1.05, "volume": 2.0}],
    }


def test_ticks_stream_emits_ticks_frame(fake_gateway: FakeGateway):
    server_ms = int(time.time() * 1000) + 2000
    fake_gateway.ticks["XAUUSD"] = [Tick(server_ms, 2000.5, 2001.0, 2000.75, 3.0)]
    app = create_app(settings=Settings(tick_poll_seconds=0.01), gateway=fake_gateway)

    start_msg, body = asyncio.run(_first_sse_chunk(app, b"symbol=XAUUSD", '"ticks"'))

    headers = {k.decode().lower(): v.decode() for k, v in start_msg["headers"]}
    assert headers["x-accel-buffering"] == "no"
    assert headers["content-type"].startswith("text/event-stream")
    payload = _payload(body)
    assert payload["type"] == "ticks"
    assert payload["symbol"] == "XAUUSD"
    assert payload["ticks"][0] == {
        "timestamp": server_ms,
        "bid": 2000.5,
        "ask": 2001.0,
        "last": 2000.75,
        "volume": 3.0,
    }


def test_ticks_stream_applies_measured_server_offset(fake_gateway: FakeGateway):
    # 服务器领先 UTC 2h：fake 的 tick 时间按服务器时间轴构造
    offset_hours = 2
    server_ms = int((time.time() + offset_hours * 3600) * 1000) + 2000
    fake_gateway.ticks["XAUUSD"] = [Tick(server_ms, 1.0, 1.1, 1.05, 1.0)]
    app = create_app(
        settings=Settings(tick_poll_seconds=0.01, server_utc_offset_override=offset_hours),
        gateway=fake_gateway,
    )

    _, body = asyncio.run(_first_sse_chunk(app, b"symbol=XAUUSD", '"ticks"'))

    payload = _payload(body)
    assert payload["ticks"][0]["timestamp"] == server_ms - offset_hours * 3600 * 1000


def test_ticks_stream_rejects_empty_symbol(client: TestClient):
    resp = client.get(_TICKS_PATH, params={"symbol": "  "})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "INVALID_REQUEST"


def _payload(body: str) -> dict:
    """解析 SSE 数据块为 JSON（报文形如 `id: N\\ndata: {...}`）。"""
    data_line = next(line for line in body.split("\n") if line.startswith("data: "))
    return json.loads(data_line[len("data: ") :])


async def _first_sse_chunk(app, query: bytes, needle: str):
    """裸 ASGI 消费 SSE 首个含 needle 的数据块后取消连接。"""
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": _TICKS_PATH,
        "raw_path": _TICKS_PATH.encode(),
        "query_string": query,
        "root_path": "",
        "server": ("test", 80),
        "client": ("test", 1234),
        "headers": [(b"host", b"test")],
    }

    async def receive():
        # 真实服务器中 receive 挂起直到断连；立即返回会忙转饿死事件循环。
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    events: list[dict] = []
    found = asyncio.Event()

    async def send(message):
        if message["type"] == "http.response.start":
            events.append(message)
        elif message["type"] == "http.response.body" and message.get("body"):
            events.append(message)
            if needle in message["body"].decode():
                found.set()

    async with app.router.lifespan_context(app):
        task = asyncio.create_task(app(scope, receive, send))
        await asyncio.wait_for(found.wait(), timeout=5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    start_msg = next(m for m in events if m["type"] == "http.response.start")
    body_msg = next(
        m
        for m in events
        if m["type"] == "http.response.body" and needle.encode() in m.get("body", b"")
    )
    return start_msg, body_msg["body"].decode()
