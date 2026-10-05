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

## 职责边界（最重要——AI 编码前必读）

**connector 是唯一允许知晓「经纪商数据缺陷及其修正」的组件。**

所有下游消费方（KCQ 指标引擎、绘图、Agent 工具、宿主脚本）只消费本服务输出的
修正后序列，禁止各自再做品牌特判、周日棒处理或 4h 边界换算。原因：Exness 等经纪商
的数据缺陷（周日短棒、4h 收线偏移）具有品牌特异性，若修正逻辑散落到 N 个消费方，
每新增一个指标/消费方就要重复处理一次，且口径极易漂移。

**AI 编码时的硬性约束：**

- 禁止在下游代码里直接 import MetaTrader5 或直连 :8090 之外的 MT5 API 绕过本服务
  ——绕过 = 拿到未修正的周日短棒/错位 4h，指标结果错误且难以察觉。
- 下游需要历史 K 线时，调 `POST /api/v1/market-data/bars`（深历史用
  `beforeTimestamp` 翻页），不要猜测 MT5 终端的 limit/深度语义。
- 新增经纪商数据缺陷（如某平台假日历异常）时，修正收敛在本服务内部实现，
  下游无感知；必要时先改 `openspec/specs/exness-alignment/` 规格再动代码。

## Committing

- Conventional Commits（无前缀）；一次提交只做一件事。
- 仅在用户明确要求时 commit/push。
