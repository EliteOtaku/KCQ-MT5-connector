# Add Per-Request Bar Aggregation Control

## Why

MT5 高周期对齐会从 H1/D1 重采样。前端目前无法表达单次请求是否需要该重采样，单品种 K 线在向前加载未缓存历史时会无谓放大终端同步负载。

## What Changes

- bars REST 请求新增必填 `barAggregation`：`original` 或 `aligned`。
- SSE 订阅新增同名必填 query 参数，并把它纳入流身份。
- `original` 返回 MT5 原生周期边界，但始终将服务器伪 UTC 矫正为真 UTC。
- `aligned` 在连接器配置允许对齐时，对高周期按既有锚时区重采样；配置不允许时明确拒绝请求，禁止静默降级。
- REST 响应回显实际 `barAggregation`。

## Non-goals

- 不改变 MT5 单工作线程约束。
- 不关闭服务器伪 UTC 到真 UTC 的偏移校正。
- 不改变锚时区、DST 或周日短棒处理规则。
