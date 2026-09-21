# KCQ-MT5-connector

KCQ 的 MT5 本地终端行情连接器（Exness）：实现 [KCQ-NexusAI](https://github.com/EliteOtaku/KCQ-NexusAI) 的 market-data V1 协议（probe / instruments/search / bars）+ SSE 实时 K 线流。

## 架构

```
MetaTrader5 Python 包（IPC 读本机终端，仅 Windows）
        │  单工作线程串行队列（app/gateway.py）
        ▼
FastAPI（app/routes.py）
  ├─ GET  /api/v1/market-data/sources/mt5/probe        探测 + 对齐状态上报
  ├─ POST /api/v1/market-data/instruments/search        品种目录搜索
  ├─ POST /api/v1/market-data/bars                      历史 K 线（游标分页）
  └─ GET  /api/v1/market-data/sources/mt5/stream        SSE 实时帧（snapshot/forming/closed/status）
```

- **实时链路**：连接器单采样循环轮询 MT5 → SSE 单连接推帧。无 WebSocket、无浏览器轮询。
- **时区对齐**：日内（1m-1h）原生序列仅做服务器偏移校正；4h/日线自 H1、周/月自 D1 按 UTC 自然边界重采样，周日短棒自然并入周一首根。锚恒为 UTC，不随券商平台或品种类别变化。
- **Exness 周日短棒自动修正**：Exness 终端的服务器时间与 UTC 重合，周开盘（周日 22:00 UTC）会形成一根独立的周日日线短棒（成交量仅为正常日线约 5%），凭空占据 K 线位并扭曲 MA/RSI/ATR 等窗口指标。连接器检测到 Exness 终端时，**缺省口径自动为 `europe-traditional`**——把这根短棒并入下一根周一（传统欧洲券商口径），K 线图表与历史数据入库拿到的即是无短棒序列。
- **三种聚合口径**：`europe-traditional`（Exness 缺省，上述修正）/ `original`（MT5 原生边界透传，**需要 Exness 原始未修正数据时显式传此值**）/ `aligned`（UTC 边界重采样，`ALIGN_UTC=off` 时不可用）。请求缺省 `barAggregation` 时按上述品牌规则取默认；非 Exness 终端缺省 `original`。
- **服务器偏移**：MT5 时间戳是"服务器墙钟按 UTC epoch 解释"的伪 UTC，连接器用最后 tick 时间实测偏移（模 24h 归一 ±12h），`EXNESS_SERVER_UTC_OFFSET` 可覆盖。

规范文档见 [openspec/](openspec/)（OpenSpec 规格：REST 协议 / SSE 流 / 对齐 / 终端网关 / 品种目录）。

## 前提

- Windows + 已安装并登录的 MT5 终端（Exness 账户）
- Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)

## 启动

```bash
uv run python ./server.py          # 默认 http://127.0.0.1:8090
```

KCQ-NexusAI 侧：`pnpm setup`（克隆本仓库到同级目录）→ `pnpm connecter mt5`。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `MT5_TERMINAL_PATH` | 自动探测 | 终端 `terminal64.exe` 全路径（如 `C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe`） |
| `EXNESS_ONLY` | `1` | 仅允许 Exness 平台（company/server 校验）；`0` 放开 |
| `ALIGN_UTC` | `on` | 对齐开关：`on`=高周期按 UTC 自然边界重采样 / `off`=取原生周期边界 |
| `EXNESS_SERVER_UTC_OFFSET` | 实测 | 服务器 UTC 偏移覆盖（小时，如 `0`/`2`/`3`） |
| `MT5_PORT` | `8090` | HTTP 端口 |

## 测试

```bash
uv run pytest            # 对齐/去重/收线判定/路由测试，无需 MT5 终端
```

## License

[MIT](LICENSE)

