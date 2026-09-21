# Realtime Bars Stream Specification

## Purpose

SSE 实时 K 线流：连接器单采样循环轮询 MT5，把尾部变化以帧推送给订阅者。
设计约束来自决策：MT5 Python 包无推送回调（轮询不可避免）；单连接固定订阅一个
(symbol, period)，切品种 = 前端断开重连。

## Requirements

### Requirement: 单连接固定订阅

系统 SHALL 提供 `GET /api/v1/market-data/sources/mt5/stream?symbol=&period=`，
每连接固定订阅一个 (symbol, period)。period 不支持时返回 400 UNSUPPORTED_CAPABILITY，
symbol 为空时返回 400 INVALID_REQUEST。响应 SHALL 携带
`X-Accel-Buffering: no` 与 no-cache 头。

#### Scenario: 新订阅

- **WHEN** 不带 Last-Event-ID 的连接建立
- **THEN** 聚合器触发 resnapshot，订阅者收到尾部两根的 `snapshot` 帧（含最后一根收线与当前 forming）

#### Scenario: 品种名按原样透传

- **WHEN** 订阅请求携带含大小写的品种名
- **THEN** 系统按原样向 MT5 查询该品种，不得做大小写归一（MT5 品种名大小写敏感）

### Requirement: 帧协议四类型

帧载荷 SHALL 为 JSON 对象，`type` 字段取值：
`snapshot`（bars 数组）/ `forming`（单根 OHLCV 更新，openTime 不变）/
`closed`（openTime 前移后旧根终值，容忍终端缓存滞后的修订）/
`status`（open/closed/degraded，无 bar）。每帧 SHALL 带 `id: <seq>`，
seq 为流内单调递增整数。

#### Scenario: 收线判定

- **WHEN** 相邻两次采样中末根 openTime 前移
- **THEN** 发布一帧 `closed`（终值取新采样中该时间戳的值）与一帧新根 `forming`，且该终值不再重复以 forming 发出

#### Scenario: 内容去重

- **WHEN** 连续两次采样尾部完全一致
- **THEN** 不发布任何帧

### Requirement: Last-Event-ID 补帧与 keepalive

断线重连时系统 SHALL 按 `Last-Event-ID` 从每流环形缓冲（默认 500 帧）重放
seq 大于该值的帧；重放与实时队列的重叠帧按 seq 去重。空闲超过 15s SHALL 发送
`: keepalive` 注释帧维持连接。新订阅的基准 seq SHALL 在触发快照发布之前捕获，
避免快照帧被去重逻辑吞掉。

#### Scenario: 断线重连补帧

- **WHEN** 客户端带 `Last-Event-ID: N` 重连
- **THEN** 立即收到缓冲中 seq > N 的帧，随后无缝衔接实时帧

#### Scenario: 订阅关闭回收

- **WHEN** 连接断开
- **THEN** 订阅队列被移除、观察者计数递减；最后一个观察者离开后轮询任务进入后台宽限期再退出
