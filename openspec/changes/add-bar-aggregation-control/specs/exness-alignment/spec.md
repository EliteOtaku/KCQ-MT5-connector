## ADDED Requirements

### Requirement: 聚合模式不影响 UTC 校正

服务器伪 UTC 到真 UTC 的偏移校正 SHALL 对 `original` 与 `aligned` 两种聚合模式均执行。
`barAggregation=original` 仅表示保留 MT5 原生周期边界；它不得被解释为关闭 UTC 校正。

#### Scenario: original 日线

- **WHEN** 请求或订阅 `barAggregation=original` 的日线
- **THEN** 输出时间戳已完成服务器偏移校正
- **THEN** 输出不经过 H1 重采样

