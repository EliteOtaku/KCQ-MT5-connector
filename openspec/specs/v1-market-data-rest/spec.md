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
（含 ≥48h 前置余量，覆盖周末缺口与重采样桶跨度）。响应 `olderData` SHALL 按
「窗口覆盖占比」判定 available/exhausted：返回根数达到 limit，或最早返回 bar 与
`beforeTimestamp` 的覆盖时间超过名义窗口跨度（limit × 周期 + 48h 余量）的 50%
（`MIN_WINDOW_COVERAGE_RATIO`，吸收周末闭市约 28%、日内低流动性缺口约 2%、节假日
约 5% 的占比折损）时为 available；覆盖占比不足或返回为空才为 exhausted。
周末/节假日缺口是市场休市所致而非历史见底，SHALL NOT 因缺口导致的根数不足
而误判 exhausted。`timezone` 恒为 `UTC`。

#### Scenario: 最新一页

- **WHEN** 请求不含 beforeTimestamp
- **THEN** 返回升序、末位为最新一根的序列，条数 ≤ limit

#### Scenario: 向前翻页

- **WHEN** 请求携带 beforeTimestamp
- **THEN** 返回时间戳严格小于该值的最后 limit 根

#### Scenario: 周末缺口不误判见底

- **WHEN** beforeTimestamp 翻页窗口（名义 1000 × 周期）因周末闭市与日内缺口
  实际只返回约 70% 的根数（如 XAUUSD H1 约 730 根），且最早 bar 距游标的覆盖
  时间超过名义跨度的 50%
- **THEN** olderData 为 available，下游可继续向前翻页

#### Scenario: 覆盖不足判定见底

- **WHEN** beforeTimestamp 翻页返回的最早 bar 距游标的覆盖时间不足名义跨度的 50%
  （数据确实稀疏或终端历史到底）
- **THEN** olderData 为 exhausted

#### Scenario: 不支持的能力

- **WHEN** period 为 `quarterly` 或 adjustment 为 `qfq`
- **THEN** 返回 400 UNSUPPORTED_CAPABILITY

### Requirement: 交易日历端点提供未来槽位时间戳

系统 SHALL 提供 `POST /api/v1/market-data/trading-calendar`：以 `anchorTimestamp`
（末根 UTC 毫秒）为起点、按 `period` 步长外推至多 `count` 个未来槽位时间戳，
响应 `{anchorTimestamp, futureTimestamps}` 且 `futureTimestamps` 恒 ≤ count
（引擎对超长响应整包丢弃）。crypto 品种 24/7 线性外推；传统资产跳周六/周日
（UTC 判定，周五收/周一开的精确时刻不建模——轴显示粒度足够，且与下游
"周日短棒不入状态机"口径一致）。period 不支持时返回 400；sourceId 不匹配
返回 400 INVALID_REQUEST。源级 capabilities 与品种级 capabilities 均 SHALL
声明 `tradingCalendar: true`（引擎三重 capability 门）。

#### Scenario: crypto 线性外推

- **WHEN** BTCUSD 自周五 12:00 UTC 请求 48 个槽位
- **THEN** 返回 48 个连续小时槽（含周六，无缺口）

#### Scenario: 传统资产跳周末

- **WHEN** XAUUSD 自周五 12:00 UTC 请求跨周末的 120 个槽位
- **THEN** 任一槽位都不落在周六/周日（UTC weekday 5/6）

#### Scenario: 能力声明

- **WHEN** probe 或 instruments/search
- **THEN** capabilities.tradingCalendar 为 true
