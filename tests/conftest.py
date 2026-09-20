# 测试夹具：FakeGateway 实现 Mt5Gateway 的异步查询接口，pytest 无需 MT5 终端。

from __future__ import annotations

import time as time_module

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway import SymbolMeta, TickProbe
from app.main import create_app
from app.frames import Bar, Tick


class FakeGateway:
    """内存版 MT5 网关：可配置品种目录、K 线序列与 tick 时间偏移。"""

    def __init__(self, tick_offset_seconds: float = 0.0):
        self.symbols_data: list[SymbolMeta] = [
            SymbolMeta("XAUUSD", "Gold vs US Dollar", "USD", 0.01, 0.01),
            SymbolMeta("BTCUSD", "Bitcoin vs US Dollar", "USD", 0.01, 0.01),
            SymbolMeta("EURUSD", "Euro vs US Dollar", "USD", 0.00001, 0.01),
        ]
        # (symbol, period) → 升序服务器时间 Bar 列表；copy_rates_from_pos 取尾部 count 根
        self.rates: dict[tuple[str, str], list[Bar]] = {}
        # symbol → 升序服务器时间逐笔 Tick 列表；copy_ticks_from 按起始秒过滤
        self.ticks: dict[str, list[Tick]] = {}
        self.tick_offset_seconds = tick_offset_seconds
        self.connected = True

    # ── 生命周期 ──

    async def initialize(self) -> dict:
        return await self.terminal_summary()

    async def shutdown(self) -> None:
        return None

    async def reinitialize_if_disconnected(self) -> bool:
        return False

    async def is_connected(self) -> bool:
        return self.connected

    async def terminal_summary(self) -> dict:
        if not self.connected:
            raise RuntimeError("terminal not connected")
        return {
            "terminal": "FakeTerminal",
            "company": "FakeTerminal",
            "connected": True,
            "account": 123456,
            "server": "Fake-Server",
            "currency": "USD",
        }

    # ── 数据查询 ──

    async def symbols(self) -> list[SymbolMeta]:
        return list(self.symbols_data)

    async def symbol_info_tick(self, symbol: str) -> TickProbe | None:
        if not self.connected:
            return None
        return TickProbe(
            time_seconds=time_module.time() - self.tick_offset_seconds,
            bid=1.0,
            ask=1.0,
        )

    async def copy_rates_from_pos(self, symbol: str, period: str, count: int) -> list[Bar]:
        series = self.rates.get((symbol, period))
        if series is None:
            return []
        return list(series[-count:])

    async def copy_rates_range(
        self, symbol: str, period: str, from_server_ms: int, to_server_ms: int
    ) -> list[Bar]:
        series = self.rates.get((symbol, period))
        if series is None:
            return []
        return [bar for bar in series if from_server_ms <= bar.time_ms <= to_server_ms]

    async def copy_ticks_from(
        self, symbol: str, from_server_seconds: int, count: int
    ) -> list[Tick]:
        if not self.connected:
            return []
        series = self.ticks.get(symbol, [])
        matched = [tick for tick in series if tick.time_ms // 1000 >= from_server_seconds]
        return matched[:count]


@pytest.fixture
def fake_gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def client(fake_gateway: FakeGateway) -> TestClient:
    """默认对齐开启（UTC）的测试应用。"""
    app = create_app(settings=Settings(), gateway=fake_gateway)
    with TestClient(app) as test_client:
        yield test_client
