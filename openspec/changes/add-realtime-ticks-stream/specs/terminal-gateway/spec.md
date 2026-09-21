## ADDED Requirements

### Requirement: 逐笔 tick 增量查询

网关 SHALL 暴露经单工作线程串行执行的 `copy_ticks_from` async 接口，返回自指定
服务器时间起的逐笔 tick（含 `time_msc`、`bid`、`ask`、`last`、`volume`），
按时间升序且条数不超过调用方给定上限。其余模块 SHALL NOT 直接 import MetaTrader5。

#### Scenario: 按起始时间增量拉取

- **WHEN** 传入起始服务器时间与数量上限
- **THEN** 返回该时间之后的 tick，按时间升序，条数不超过上限

#### Scenario: 无新 tick

- **WHEN** 起始时间之后没有新 tick
- **THEN** 返回空列表，不抛错
