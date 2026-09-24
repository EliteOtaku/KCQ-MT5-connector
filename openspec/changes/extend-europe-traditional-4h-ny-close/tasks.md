# Tasks

## 1. 纯函数

- [x] 1.1 `align.py`：`resample` 加 `anchor` 参数（默认 `"utc"`），NY-close 锚 4h 分桶
      （`America/New_York` 17:00 日界，tz-aware 域运算，跟随美国 DST）
- [x] 1.2 `RESAMPLE_NY_CLOSE_TARGETS = {"4h"}`；非 4h 目标 + ny_close 锚显式拒绝

## 2. 接入

- [x] 2.1 REST `fetch_bars`：`europe-traditional`+`4h` 走 H1 NY-close 聚合；
      周日合并收窄为仅 `daily`（修复日内序列误合并）
- [x] 2.2 SSE `Aggregator._poll`：europe-traditional 4h 轮询计划 h1 + ny_close 锚；
      周日合并仅 daily
- [x] 2.3 `_load_series` 参数化 `resample_mode`（none/utc/ny_close）

## 3. 验证

- [x] 3.1 `test_align.py`：冬令时/夏令时桶边界、周日开市并入首槽、日界前样本归属
      前一交易日、DST 切换日 sanity、非 4h 目标拒绝
- [x] 3.2 `test_routes.py`：4h NY-close 边界聚合（冬令时断言）、日内序列周日棒保留
- [x] 3.3 pytest 全量 53 passed；openspec validate --all --strict
