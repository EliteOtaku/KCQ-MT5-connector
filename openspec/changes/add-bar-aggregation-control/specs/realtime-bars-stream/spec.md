## ADDED Requirements

### Requirement: SSE 订阅显式声明聚合模式

`GET /api/v1/market-data/sources/mt5/stream` SHALL 要求 `barAggregation=original|aligned`
query 参数。流身份 SHALL 为 `(symbol, period, barAggregation)`；不同聚合模式不得复用轮询任务、
环形缓冲或 Last-Event-ID 序号。

`original` 帧 SHALL 使用原生周期边界并始终完成服务器伪 UTC 到真 UTC 的校正。`aligned`
帧 SHALL 使用与 REST 相同的高周期锚时区重采样规则。配置不允许 `aligned` 时，系统 SHALL
在建立流前返回 `UNSUPPORTED_CAPABILITY`。

#### Scenario: 同一品种的两种边界隔离

- **WHEN** 客户端分别订阅相同 symbol 和 period 的 `original` 与 `aligned`
- **THEN** 两个订阅拥有独立的轮询任务、帧环和序号
- **THEN** 任一订阅收到的帧不得来自另一聚合模式
