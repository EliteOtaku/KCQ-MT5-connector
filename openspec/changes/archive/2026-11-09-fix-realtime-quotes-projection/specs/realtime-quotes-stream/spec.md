## ADDED Requirements

### Requirement: Quote SSE 订阅

系统 SHALL 提供 `GET /api/v1/market-data/sources/mt5/quotes?instruments=<列表>`。
流身份 SHALL 为「instruments 列表 + 源默认聚合口径」，多个品种 SHALL 复用同一条连接。
响应 SHALL 携带 `X-Accel-Buffering: no` 与 no-cache 头。
`instruments` 为空或含未知 instrumentId 时 SHALL 返回 400 INVALID_REQUEST。

#### Scenario: 多品种单连接

- **WHEN** 一次订阅携带多个 instrumentId
- **THEN** 同一连接按品种分别推送 quote 帧，不额外建立上游流

#### Scenario: 无效列表

- **WHEN** instruments 为空或包含无法解析的 instrumentId
- **THEN** 返回 400 INVALID_REQUEST

### Requirement: 报价取值

quote 的 `last` SHALL 取最新一根日线的收盘价，`prevClose` SHALL 取前一根日线的收盘价，
`timestamp` SHALL 用最新一根日线的收线时间（真 UTC 毫秒）。
两者与上次推送相同时 SHALL NOT 重复推送。

#### Scenario: 值未变化

- **WHEN** 连续两次采样得到相同的 last 与 prevClose
- **THEN** 不推送 quote 帧

#### Scenario: 新收盘价

- **WHEN** 最新日线收盘价变化
- **THEN** 推送一帧含新 last 与既有 prevClose 的 quote

### Requirement: 基准补齐

当实时流快照不足以构成「最新价 + 昨收」两根日线时，系统 SHALL 通过历史日线查询补齐基准，
SHALL NOT 因快照根数不足而完全不推送报价。

#### Scenario: 对齐口径只剩一根快照

- **WHEN** 源默认口径为 `europe-traditional` 且日线快照只含一根
- **THEN** 系统用合并周日短棒后的历史日线补齐前一根，仍能推送正确的 last 与 prevClose

#### Scenario: 历史查询失败

- **WHEN** 建连时的历史日线查询失败或返回不足两根
- **THEN** 连接 SHALL 保持建立，待后续实时帧补足基准后再推送，不得返回 500
