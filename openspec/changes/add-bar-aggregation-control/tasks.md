## 1. Specification

- [x] 1.1 定义 REST 的 `barAggregation` 请求和响应语义。
- [x] 1.2 定义 SSE 的 `barAggregation` 订阅与流身份语义。
- [x] 1.3 定义 original/aligned 与 UTC 校正、全局对齐配置的关系。

## 2. Implementation

- [x] 2.1 新建聚合模式领域常量，并让 REST、SSE 共用。
- [x] 2.2 按请求执行 REST 聚合模式并回显响应。
- [x] 2.3 将 SSE 聚合模式纳入订阅、Hub 和 Aggregator 流身份。
- [x] 2.4 更新测试替身和行为覆盖。

## 3. Validation

- [x] 3.1 运行 OpenSpec 严格校验。
- [x] 3.2 运行 pytest。
