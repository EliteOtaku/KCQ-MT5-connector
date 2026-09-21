# KCQ-MT5-connector — Agent Guide

KCQ 的 MT5 本地终端行情连接器（Exness）：MetaTrader5 Python 包 IPC 读本机终端，
FastAPI 实现 KCQ market-data V1 协议 + SSE 实时 K 线流。消费方为同级仓库
KCQ-NexusAI 的 core 行情层。

## OpenSpec（规格驱动）

- **规格即契约**：`openspec/specs/<capability>/spec.md` 是各能力的当前真相
  （v1-market-data-rest / realtime-bars-stream / exness-alignment / terminal-gateway / symbol-catalog）。
- 改行为前先改规格：用 `openspec` 工作流（`/opsx:propose` 等）建 change（proposal.md +
  tasks.md + delta spec），实施完成后 archive。
- 校验命令：`npx @fission-ai/openspec validate --all --strict` 必须全绿。
- 项目上下文与约定写在 `openspec/config.yaml` 的 `context:` 字段。

## 代码要求

- 拒绝治标不治本的最小修复；不做复杂化架构。
- MetaTrader5 调用必须经 `app/gateway.py` 单工作线程串行执行；其他模块禁止直接 import MetaTrader5。
- 全部可调参数集中在 `app/config.py`（env → Settings），禁止散落 `os.environ`。
- 注释正文中文、技术用语保留英文；每文件头部注释说明用途，每函数注释说明职责。

## Commands

| Command | What |
|---------|------|
| `uv sync` | 安装依赖（首次） |
| `uv run python ./server.py` | 启动连接器（:8090，需 Windows + 已登录 MT5 终端） |
| `uv run pytest` | 全量测试（FakeGateway 替身，无需终端） |
| `npx @fission-ai/openspec validate --all --strict` | 校验 OpenSpec 规格 |

## Testing

- 测试禁止依赖真实 MT5 终端：`tests/conftest.py` 的 FakeGateway 实现网关异步接口。
- SSE 流测试用裸 ASGI send/receive（TestClient/httpx ASGITransport 不支持无限流消费）；
  receive 桩必须阻塞挂起（立即返回会饿死事件循环）。
- 对齐用例为行为基准：UTC 4h/日线/周/月边界、跨月跨周归属、偏移换算——改对齐实现不得改断言。

## Domain Invariants

- MT5 时间戳是伪 UTC（服务器墙钟），出网关前必须经实测偏移转真 UTC。
- 周日短棒不剔除：日内原生保留；4h/日/周/月经 UTC 边界重采样自然并入周一首根。
- 对齐锚恒为 UTC（4h 边界 {00,04,08,12,16,20}，日线 UTC 00:00）；`ALIGN_UTC=off` 关闭对齐走原生边界。
- Exness 检测（company/server 判定）→ 缺省 `barAggregation` 默认 `europe-traditional`：UTC 周日的
  日线短棒并入下一根周一（成交量仅为正常日线约 5% 的开盘噪声，不并入会扭曲窗口指标）；
  非 Exness 缺省 `original`；显式传值总是覆盖默认。

## Committing

- Conventional Commits（无前缀）；一次提交只做一件事。
- 仅在用户明确要求时 commit/push。
