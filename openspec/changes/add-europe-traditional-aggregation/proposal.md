# Add Europe-Traditional Bar Aggregation

## Why

Exness 服务器时间与 UTC 重合（实测 offset=0），周开盘（周日 22:00 UTC）落在 UTC 周日桶内，
形成一根独立的周日日线短棒：实测 XAUUSD 最近 120 根日线中 20 根为周日 bar（每个周日一根），
成交量仅为正常日线的 4.9%。UTC 边界重采样（`aligned`）无法消除它（周日 22:00-24:00 UTC 仍在
UTC 周日桶），`original` 透传同样保留。这根短棒会扭曲窗口指标：MA(5) 实测偏差 0.41%。

传统欧洲券商口径（服务器时区 EET/GMT+2..3 日界，周开盘恰为周一 00:00 服务器时间）将周日成交
并入周一，是该品类的行业惯例口径。

## What Changes

- `barAggregation` 新增第三种取值 `europe-traditional`：
  - 日线/周线/月线：读取 MT5 原生周期（服务器日界即传统欧洲日界），并把 UTC 周日的短棒
    并入下一根周一（OHLC 合并：open=周日 open，high=max，low=min，close=周一 close，
    volume/turnover 相加）。
  - 4h 及以下日内周期：等同 `original`（EET 4h 边界由服务器原生切分，不存在周日独立桶）。
  - 不引入 H1/D1 额外拉取——周日合并是对原生序列的 O(n) 后处理，保持 PR #2 的取数性能。
- SSE 流身份仍为 `(symbol, period, barAggregation)`，`europe-traditional` 作为独立流，
  轮询计划等同 `native`（实时尾部同样应用周日合并）。
- probe `capabilities.bars` 新增 `barAggregations` 数组，上报三种取值。

## Non-goals

- 不改变 `original`/`aligned` 的既有语义。
- 不改变服务器伪 UTC 到真 UTC 的偏移校正。
- 不处理非 Exness 经纪商的同类问题（口径由客户端按需选择）。
