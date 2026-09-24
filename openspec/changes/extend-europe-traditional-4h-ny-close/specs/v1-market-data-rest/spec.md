## MODIFIED Requirements

### Requirement: K 线请求显式声明聚合模式

`POST /api/v1/market-data/bars` 请求携带的 `barAggregation` SHALL 支持
`original`、`aligned`、`europe-traditional` 三种取值。响应 SHALL 回显相同字段。

`europe-traditional` SHALL 按周期分派：

- `period=4h`：SHALL 自 H1 按 NY-close 日界（纽约 17:00，`America/New_York`，
  跟随美国夏令时）聚合 4h 桶，与主流外汇经纪商（GMT+2/+3 New York close）的
  4h 收线时间对齐；周日开市数据 SHALL 天然并入首个交易槽，不产生独立周日桶
- `period=daily`：SHALL 读取 MT5 原生日线并把 UTC 周日的 bar 并入下一根周一
  （open 取周日 open，high 取两者最大，low 取两者最小，close 取周一 close，
  volume/turnover 相加）
- 其余周期（1h 及以下、weekly/monthly）：SHALL 等同 `original`；
  周日合并 SHALL NOT 应用于非日线序列（日内周期周日/周一交界的相邻棒并入
  会破坏时间轴）

所有周期 SHALL 始终把服务器伪 UTC 转换为真 UTC。

#### Scenario: 4h 按 NY-close 边界聚合（冬令时）

- **WHEN** 请求 `period=4h` 且 `barAggregation=europe-traditional`（服务器 UTC+0，
  美国冬令时期间）
- **THEN** 4h 桶边界 SHALL 为 UTC {22,02,06,10,14,18}，而非 aligned 口径的
  {00,04,08,12,16,20}

#### Scenario: 4h 按 NY-close 边界聚合（夏令时）

- **WHEN** 美国夏令时期间请求同上
- **THEN** 4h 桶边界 SHALL 为 UTC {21,01,05,09,13,17}

#### Scenario: 4h 周日开市并入首个交易槽

- **WHEN** 周日 22:00 UTC（Exness 周开盘）后的 H1 数据参与 4h 聚合
- **THEN** SHALL 归入 NY-close 交易日首个 4h 桶，不产生独立的周日 4h 桶

#### Scenario: 日线周日短棒并入周一

- **WHEN** 请求 `period=daily` 且 `barAggregation=europe-traditional`
- **THEN** 序列中 UTC 周日的 bar SHALL 与下一根周一合并为单根
  （open=周日 open、high=max、low=min、close=周一 close、volume/turnover 相加）

#### Scenario: 日内周期不应用周日合并

- **WHEN** 请求 `period=60min`（或其他 1h 及以下周期）且序列含周日 23:00 与周一
  00:00 的相邻 bar、`barAggregation=europe-traditional`
- **THEN** 两根 bar SHALL 原样保留，SHALL NOT 被并入单根

#### Scenario: SSE 流按聚合口径独立

- **WHEN** SSE 订阅 `barAggregation=europe-traditional`
- **THEN** 流身份 SHALL 为独立的 `(symbol, period, europe-traditional)`，
  `period=4h` 的实时尾部 SHALL 与 REST 同样走 H1 NY-close 聚合，
  周日合并 SHALL 仅在 `period=daily` 应用
