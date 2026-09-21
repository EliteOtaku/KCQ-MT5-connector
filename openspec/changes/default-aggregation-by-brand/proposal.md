# Default Bar Aggregation by Brand

## Why

`barAggregation` 必填使每个下游客户端都必须理解聚合口径。Exness 终端存在领域特有的周日日线短棒
（实测 120 根中 20 根，成交量仅为正常日线 4.9%），UTC 边界重采样无法消除——下游若缺省透传会把
扭曲数据送进图表与入库。品牌检测基建（company/server 判定）已存在，缺省口径可以按品牌收敛：
Exness 终端缺省 `europe-traditional`，从底层完成修正。

## What Changes

- REST `BarRequest.barAggregation` 与 SSE `barAggregation` query 参数改为可选（缺省 None）。
- 缺省解析：Exness 终端（company/server 判定）→ `europe-traditional`；其余 → `original`。
- 显式传值总是覆盖默认；响应回显实际生效口径。
- probe 新增 `defaultBarAggregation` 字段，供客户端在不发送该参数时得知实际口径。
- README/AGENTS 说明：需要 Exness 原始未修正数据时显式传 `original`。

## Non-goals

- 不改变 `original`/`aligned`/`europe-traditional` 各自的既有语义。
- 不改 OpenSpec 目录外的部署文档结构。
