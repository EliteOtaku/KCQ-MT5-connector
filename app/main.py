# FastAPI 应用工厂：组装 gateway/clock/hub/aggregator 并管理生命周期。
# 终端初始化失败不阻断启动——probe 会如实上报 offline，REST 数据端点返回 502。

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .aggregator import Aggregator
from .clock import ServerClock
from .config import Settings, load_settings
from .gateway import Mt5Gateway
from .hub import StreamHub
from .routes import router
from .ticks import TickAggregator

logger = logging.getLogger("mt5.app")


def create_app(
    settings: Settings | None = None,
    gateway: Mt5Gateway | None = None,
) -> FastAPI:
    """构建应用；gateway 可注入替身（测试），缺省构造真实 MT5 网关。"""
    resolved = settings or load_settings()
    resolved_gateway = gateway or Mt5Gateway(resolved)
    clock = ServerClock(resolved_gateway, resolved, resolved.clock_recheck_seconds)
    hub = StreamHub(resolved.ring_buffer_frames)
    aggregator = Aggregator(resolved_gateway, clock, hub, resolved)
    tick_aggregator = TickAggregator(resolved_gateway, clock, hub, resolved)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop = asyncio.Event()
        tasks = [
            asyncio.create_task(_heartbeat_loop(resolved_gateway, resolved, stop)),
            asyncio.create_task(clock.run_forever(stop)),
        ]
        try:
            summary = await resolved_gateway.initialize()
            logger.info("MT5 connected: %s (server=%s)", summary.get("company"), summary.get("server"))
            await clock.refresh()
        except Exception as exc:  # noqa: BLE001 — 初始化失败保持服务在线供 probe 诊断
            logger.error("MT5 initialize failed: %s", exc)
        try:
            yield
        finally:
            stop.set()
            aggregator.stop_all()
            tick_aggregator.stop_all()
            for task in tasks:
                task.cancel()
            await resolved_gateway.shutdown()

    app = FastAPI(title="KCQ-MT5-connector", version="0.1.0", lifespan=lifespan)
    # 本地连接器被前端 dev server（5273 等端口）跨源直连，放开 CORS
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    app.state.settings = resolved
    app.state.gateway = resolved_gateway
    app.state.clock = clock
    app.state.hub = hub
    app.state.aggregator = aggregator
    app.state.tick_aggregator = tick_aggregator
    app.include_router(router)
    return app


async def _heartbeat_loop(gateway: Mt5Gateway, settings: Settings, stop: asyncio.Event) -> None:
    """终端连接心跳：断连时限流重连（间隔由 gateway 内部节流，无 re-initialize 风暴）。"""
    while not stop.is_set():
        try:
            await gateway.reinitialize_if_disconnected()
        except Exception:  # noqa: BLE001 — 心跳异常不退出
            logger.exception("heartbeat error")
        try:
            await asyncio.wait_for(stop.wait(), timeout=settings.heartbeat_seconds)
        except asyncio.TimeoutError:
            continue
