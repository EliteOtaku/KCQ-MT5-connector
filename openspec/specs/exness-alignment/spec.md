# Exness Alignment Specification

## Purpose

把 MT5 的「服务器墙钟按 UTC epoch 解释」伪 UTC 时间轴换算为真 UTC，并把高周期
K 线按 UTC 自然边界重采样，使图表显示、指标计算与存储三层数据同源一致。行为基准：
锚恒为 UTC（4h 边界 {00,04,08,12,16,20}，日线边界 UTC 00:00）。周日短棒不剔除——
日内原生保留，高周期在重采样中自然并入周一首根。

## Requirements

### Requirement: 服务器偏移实测与覆盖

系统 SHALL 以活跃品种最后 tick 时间与本机时钟差实测服务器领先 UTC 的整小时偏移，
取整后模 24h 归一到 [-12h, +12h)（消除周末停市累积天数）；探测品种优先 7x24 的
加密（BTCUSD/ETHUSD），外汇/金属兜底。`EXNESS_SERVER_UTC_OFFSET` env SHALL 覆盖实测；
实测失败回落 0。偏移 SHALL 周期复测（默认 300s）并在 probe 响应上报
`serverOffsetMinutes` 与 `offsetMeasured`。

#### Scenario: 周末停市不偏移

- **WHEN** 最后 tick 距今超过 24h（周末停市）
- **THEN** 实测偏移经模 24h 归一后仍等于服务器真实偏移（如 +180 分钟）

#### Scenario: env 覆盖

- **WHEN** `EXNESS_SERVER_UTC_OFFSET=2`
- **THEN** 偏移取 +120 分钟，跳过实测

### Requirement: 对齐开关语义

`ALIGN_UTC` env SHALL 控制对齐：`on`（默认）开启，锚恒为 UTC；`off` 关闭，取 MT5
原生周期边界（仅做伪 UTC → 真 UTC 偏移校正）。对齐 SHALL NOT 依赖券商平台探测或品种
类别。非法取值 SHALL 回落 `on` 且不中断启动。

对齐状态 SHALL 在 probe 响应的 `alignment.anchor` 上报：开启时为 `UTC`，关闭时为 `off`。

#### Scenario: 关闭对齐走原生周期

- **WHEN** `ALIGN_UTC=off` 且请求 `barAggregation=aligned`
- **THEN** 系统返回 400 `UNSUPPORTED_CAPABILITY`，不返回原生数据冒充对齐

#### Scenario: 开启对齐与券商无关

- **WHEN** `ALIGN_UTC=on` 且终端来自任意券商
- **THEN** 4h/daily/weekly/monthly 按 UTC 自然边界重采样

### Requirement: 高周期 UTC 边界重采样

对齐开启时，4h/daily SHALL 从 H1、weekly/monthly SHALL 从 D1 按 UTC 自然边界重采样：
日线取 UTC 自然日 00:00，4h 再按 hour//4*4 分桶，weekly 取 ISO 周锚（周一 00:00 UTC），
monthly 取自然月首日 00:00 UTC。输出时间戳 SHALL 为 UTC 桶边界毫秒；
OHLCV 按桶聚合（open=first, high=max, low=min, close=last, volume/turnover=sum）。

#### Scenario: 周日短棒并入 UTC 周一

- **WHEN** 输入 H1 序列始于周日 22:00 UTC 且跨 72 小时
- **THEN** daily 重采样输出 3 根，首根开于周日 00:00 UTC、量为 24×H1 量

#### Scenario: 全品种共用同一 UTC 锚

- **WHEN** 分别对齐 XAUUSD（forex）与 BTCUSD（crypto）的同段 H1
- **THEN** 两者 4h 边界均为 {00,04,08,12,16,20} UTC，日线边界均为 00:00 UTC
