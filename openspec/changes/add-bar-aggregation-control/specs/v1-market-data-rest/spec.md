## ADDED Requirements

### Requirement: K 线请求显式声明聚合模式

`POST /api/v1/market-data/bars` 请求 SHALL 携带 `barAggregation`，取值只能为
`original` 或 `aligned`。响应 SHALL 回显相同字段。请求缺失或取值非法时 SHALL 被拒绝；
连接器不得按旧的全局默认静默选择模式。

`original` SHALL 读取 MT5 原生请求周期，并始终把服务器伪 UTC 转换为真 UTC；它不得执行
高周期锚时区重采样。`aligned` SHALL 在连接器对齐配置允许时，按既有高周期锚时区规则重采样；
配置不允许时 SHALL 返回 `UNSUPPORTED_CAPABILITY`，不得返回 `original` 数据冒充 `aligned`。

#### Scenario: 原生周期仍校正 UTC

- **WHEN** 请求 `period=daily` 且 `barAggregation=original`
- **THEN** 系统从 MT5 D1 周期读取数据
- **THEN** 响应时间戳为服务器伪 UTC 经偏移校正后的真 UTC
- **THEN** 响应 `barAggregation` 为 `original`

#### Scenario: 对齐周期重采样

- **WHEN** 请求 `period=daily`、`barAggregation=aligned` 且对齐配置允许
- **THEN** 系统从 MT5 H1 周期读取并按既有锚时区规则重采样
- **THEN** 响应 `barAggregation` 为 `aligned`

#### Scenario: 对齐模式不可用

- **WHEN** 请求 `barAggregation=aligned` 且 ALIGN_TZ 配置不允许对齐
- **THEN** 系统返回 400 `UNSUPPORTED_CAPABILITY`
