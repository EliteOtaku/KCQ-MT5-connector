## MODIFIED Requirements

### Requirement: K 线请求显式声明聚合模式

`POST /api/v1/market-data/bars` 请求携带的 `barAggregation` SHALL 支持
`original`、`aligned`、`europe-traditional` 三种取值。响应 SHALL 回显相同字段。

`europe-traditional` SHALL 读取 MT5 原生请求周期，把 UTC 周日的 bar 并入下一根周一
（open 取周日 open，high 取两者最大，low 取两者最小，close 取周一 close，
volume/turnover 相加），并始终把服务器伪 UTC 转换为真 UTC。对 4h 及以下日内周期，
`europe-traditional` SHALL 等同 `original`（EET 4h 边界由服务器原生切分）。

#### Scenario: 日线周日短棒并入周一

- **WHEN** 请求 `period=daily` 且 `barAggregation=europe-traditional`
- **THEN** 序列中 UTC 周日的 bar SHALL 与下一根周一合并为单根
  （open=周日 open、high=max、low=min、close=周一 close、volume/turnover 相加）
- **THEN** 合并后的序列 SHALL 不再包含 UTC 周日 bar

#### Scenario: 不含周日 bar 的序列为 no-op

- **WHEN** 序列中不存在 UTC 周日 bar 且 `barAggregation=europe-traditional`
- **THEN** 序列 SHALL 原样返回（open/high/low/close/volume/turnover 不变）

#### Scenario: SSE 流按聚合口径独立

- **WHEN** SSE 订阅 `barAggregation=europe-traditional`
- **THEN** 流身份 SHALL 为独立的 `(symbol, period, europe-traditional)`，
  实时尾部的周日合并 SHALL 与 REST 口径一致
