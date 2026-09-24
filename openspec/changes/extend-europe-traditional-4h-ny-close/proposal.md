# extend-europe-traditional-4h-ny-close

## Why

Exness 服务器时间为 UTC+0（官方文档 + 实测偏移 +0h 双重确认），其原生 4h 边界为
UTC {00,04,08,12,16,20}；而主流外汇经纪商（IC Markets/Pepperstone 等）服务器时间为
GMT+2/+3（New York close），4h 边界为 UTC {22,02,...}（冬令时）/{21,01,...}（夏令时），
随美国夏令时浮动。同一套 4h 收线策略跨平台结果不同——europe-traditional 口径当前
仅覆盖日级周日短棒合并，4h 仍是品牌原生 UTC 边界，口径名下日级对齐而 4h 不对齐，
语义不自洽。

同时修复：`merge_sunday_bars` 此前对全部周期无差别应用——该函数按日线语义设计
（周日棒+周一棒合并），对日内周期（1h/4h/30min 等）会把周日-周一交界的相邻棒错误
并入，破坏日内时间轴。Exness 缺省口径即 europe-traditional，影响所有日内取数。

## What Changes

- `align.py`：`resample` 新增 `anchor` 参数（默认 `"utc"` 不变）；新增 NY-close 锚
  4h 分桶——纽约 17:00 为日界（`America/New_York`，跟随美国 DST），全程 tz-aware
  域运算；`RESAMPLE_NY_CLOSE_TARGETS = {"4h"}`
- REST `fetch_bars`：`europe-traditional` + `period=4h` 改为自 H1 按 NY-close 聚合；
  周日合并（`merge_sunday_bars`）收窄为仅 `period=daily` 应用（修复日内误合并）
- SSE `Aggregator._poll`：同构——europe-traditional 4h 轮询计划改走 h1 + ny_close
  锚；周日合并同样仅 daily
- NY-close 聚合天然把周日 22:00 UTC 起的开市数据并入首个交易槽（纽约 17:00 日界后
  即新交易日），4h 层面无独立周日短棒

## Impact

- specs: v1-market-data-rest（europe-traditional 4h 语义 + 周日合并范围收窄）
- 代码：app/align.py、app/routes.py、app/aggregator.py
- 测试：tests/test_align.py（NY-close 冬/夏令时边界、周日并入、DST 切换 sanity、
  非 4h 拒绝）、tests/test_routes.py（4h NY-close 边界、日内序列不合并）
- 兼容性：`aligned`/`original` 语义不变；SSE 流身份三元组不变；
  europe-traditional 4h 序列内容变化（UTC 边界 → NY-close 边界）即本变更目的

## Non-goals

- daily/weekly/monthly 保持既有语义（透传 + 日线周日合并），NY 日界日线不在本期
- 不处理非 Exness 经纪商（口径由客户端按需选择）
