## 1. Specification

- [ ] 1.1 定义 tick SSE 订阅语义与流身份（仅 symbol）。
- [ ] 1.2 定义 `ticks` 帧字段与真 UTC 毫秒时间戳语义。
- [ ] 1.3 定义网关 `copy_ticks_from` 的增量与 `time_msc` 去重语义。

## 2. Implementation

- [ ] 2.1 `app/frames.py` 新增 `Tick` 与 `TicksFrame`，接入 `frame_type`/`frame_payload`。
- [ ] 2.2 `app/gateway.py` 新增 `copy_ticks_from`（单工作线程 + 完整字段投影）。
- [ ] 2.3 `app/config.py` 新增 tick 轮询参数。
- [ ] 2.4 tick 轮询循环与去重接入 `app/aggregator.py`，流身份独立于 Bar 流。
- [ ] 2.5 `app/routes.py` 新增 `GET /sources/mt5/ticks/stream`。

## 3. Validation

- [ ] 3.1 `tests/conftest.py` 的 FakeGateway 扩展 tick 序列，补 SSE 行为测试。
- [ ] 3.2 运行 `npx @fission-ai/openspec validate --all --strict`。
- [ ] 3.3 运行 `uv run pytest`。
