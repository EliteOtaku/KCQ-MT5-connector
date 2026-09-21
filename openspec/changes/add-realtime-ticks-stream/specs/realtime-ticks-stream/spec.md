## ADDED Requirements

### Requirement: Tick SSE 订阅

系统 SHALL 提供 `GET /api/v1/market-data/sources/mt5/ticks/stream?symbol=<SYMBOL>`，
流身份 SHALL 仅由 symbol 决定（tick 与 period / barAggregation 无关）。响应 SHALL 携带
`X-Accel-Buffering: no` 与 no-cache 头，并复用与 Bar 流一致的 seq、环形缓冲、
Last-Event-ID 与 keepalive 语义。symbol 为空时 SHALL 返回 400 INVALID_REQUEST。

#### Scenario: 新订阅

- **WHEN** 不带 Last-Event-ID 建立连接
- **THEN** 只推送连接建立之后产生的 tick，不回放建立之前的历史 tick

#### Scenario: 断线重连补帧

- **WHEN** 客户端带 Last-Event-ID 重连
- **THEN** 立即收到环形缓冲中 seq 大于该值的 tick 帧，随后无缝衔接实时帧

### Requirement: Tick 帧协议

帧载荷 SHALL 为 JSON 对象，`type` 为 `ticks`，携带 `symbol` 与 `ticks` 数组；
每个 tick SHALL 含 `timestamp`（真 UTC 毫秒）、`bid`、`ask`、`last`、`volume`。
两次采样之间无新 tick 时 SHALL NOT 发布空帧。

#### Scenario: 采样间隔内多笔

- **WHEN** 两次采样之间 MT5 产生多笔 tick
- **THEN** 这些 tick 按时间升序合并为一帧 `ticks` 推送，且不丢失中间 tick

### Requirement: tick 时间戳校正

tick 的 `timestamp` SHALL 由 MT5 `time_msc`（服务器伪 UTC）经实测服务器偏移换算为
真 UTC 毫秒，禁止直接透传服务器时间。

#### Scenario: 服务器偏移换算

- **WHEN** 实测服务器领先 UTC 2h
- **THEN** tick 的 `timestamp` 等于 MT5 `time_msc` 减去 2h

### Requirement: 逐笔增量拉取

系统 SHALL 以网关 `copy_ticks_from` 按 `time_msc` 增量拉取逐笔 tick，
SHALL NOT 以 `symbol_info_tick` 的「最后一笔」轮询替代逐笔流。

#### Scenario: 重复 tick 去重

- **WHEN** 相邻两次增量拉取因时间重叠返回同一 tick
- **THEN** 该 tick 按 `time_msc` 去重，只推送一次
