# V1 Market Data REST Specification

## Purpose

实现 KCQ-NexusAI 的 market-data V1 REST 协议（probe / instruments/search / bars），
让前端 core 行情层把本连接器当作任意 V1 数据源消费。响应统一 `{data, requestId}` envelope，
错误统一 `{error: {code, message}, requestId}`。契约唯一权威是前端
`packages/core/src/data/provider/protocol/types.ts`；本规格描述连接器侧的实现承诺。

## Requirements

### Requirement: 探测端点如实上报连接与对齐状态

系统 SHALL 提供 `GET /api/v1/market-data/sources/mt5/probe`，返回
`status`（online/degraded/offline）、`checkedAt`、`latencyMs`，以及
`alignment`（enabled/anchor/serverOffsetMinutes/offsetMeasured）和 `capabilities`
（assetClasses + bars periods/adjustments + liveBars 实时 K 线能力）。探测失败 SHALL 返回 200 + offline，
而非 5xx——前端依赖 probe 判定可达性。

#### Scenario: 终端在线

- **WHEN** MT5 终端已连接
- **THEN** 响应 `data.status` 为 `online`，`alignment.enabled` 按 `ALIGN_UTC` 开关给出、`alignment.anchor` 为 `UTC` 或 `off`
- **THEN** `capabilities.bars.periods` 覆盖 1min/5min/15min/30min/60min/4h/daily/weekly/monthly
- **THEN** `capabilities.liveBars` 为 true，声明 `/stream` 实时 K 线流对所有已声明周期可用

#### Scenario: 终端离线

- **WHEN** 终端未连接或网关未初始化
- **THEN** 响应 `data.status` 为 `offline`，`alignment.enabled` 为 false，HTTP 状态码仍为 200

### Requirement: 品种目录搜索遵循协议校验

系统 SHALL 提供 `POST /api/v1/market-data/instruments/search`：sourceId 必须为 `mt5`，
assetClasses 必须是协议枚举子集（否则 400 INVALID_REQUEST）；命中项映射为
InstrumentDescriptor（id=`mt5:<SYMBOL>`、sessionId=`MT5`、providerRef=`{symbol}`、
tickSize/lotSize 来自终端元数据）。终端不可用时 SHALL 返回 502 UPSTREAM_UNAVAILABLE。

#### Scenario: 关键字命中

- **WHEN** 关键字匹配品种代码或描述（大小写不敏感）
- **THEN** 返回去重后的描述符列表，assetClass 由命名启发式判定（无法判定为 unknown）

#### Scenario: 非法 assetClasses

- **WHEN** 请求携带协议枚举之外的 assetClass（如 `commodity`）
- **THEN** 返回 400，error.code 为 `INVALID_REQUEST`

### Requirement: K 线端点游标分页与能力校验

系统 SHALL 提供 `POST /api/v1/market-data/bars`：period/adjustment 不支持时返回
400 UNSUPPORTED_CAPABILITY；`beforeTimestamp`（UTC 毫秒，排他上界）为空时返回最新一页
（`copy_rates_from_pos`），非空时经服务器时间轴反向换算取窗口
（含 ≥48h 前置余量，覆盖周末缺口与重采样桶跨度）。响应 `olderData` 按返回根数是否
达到 limit 给出 available/exhausted；`timezone` 恒为 `UTC`。

#### Scenario: 最新一页

- **WHEN** 请求不含 beforeTimestamp
- **THEN** 返回升序、末位为最新一根的序列，条数 ≤ limit

#### Scenario: 向前翻页

- **WHEN** 请求携带 beforeTimestamp
- **THEN** 返回时间戳严格小于该值的最后 limit 根

#### Scenario: 不支持的能力

- **WHEN** period 为 `quarterly` 或 adjustment 为 `qfq`
- **THEN** 返回 400 UNSUPPORTED_CAPABILITY
