# Fix Realtime Quotes Projection

## Why

`GET /api/v1/market-data/sources/mt5/quotes` 在 Exness 环境下不推送任何帧。

报价是日线实时流的投影：`QuoteProjection._quote()` 需要至少两根日线才能算出
「最新价与昨收」，不足两根时返回 `None`、不推送。而源默认口径
`europe-traditional` 会把 UTC 周日短棒并入周一，聚合器日线快照因此只剩一根，
投影恒为空。

实测（2026-11-09，Exness 终端）：

| 口径 | 日线快照根数 | 报价 |
| --- | --- | --- |
| `original` | 2 | 可算出 |
| `europe-traditional`（Exness 默认） | 1 | 算不出 |
| `/quotes` 连接 30 秒 | — | 零帧，连 keepalive 也未出现 |

下游影响：KCQ-NexusAI 自选列表里全部 MT5 品种显示占位符；Binance 品种正常
（其报价走另一套实现）。

## What Changes

- `QuoteProjection` 新增基准注入接口，允许在建连时喂入历史日线尾部。
- `/quotes` 在建连时先按与 `/bars` 相同的口径拉取若干历史日线（合并周日短棒后
  仍有至少两根），注入投影作基准，再进入实时循环。
- 新增 `realtime-quotes-stream` capability 规格：该端点此前完全没有规格覆盖。

## Non-goals

- 不改动 Bar 流的帧协议、订阅参数与流身份。
- 不改动 `europe-traditional` 的周日短棒合并规则。
- 不允许客户端为 quotes 指定聚合口径。
- 不新增第二条上游轮询路径；基准查询复用现有 `_load_series`。
- 不处理 `realtime-bars-stream` 规格中 `?symbol=` 与实现 `?instruments=` 的既有偏差，
  该偏差另行处理。
