# Tasks

## 1. 协议与枚举

- [x] 1.1 `bar_aggregation.py` 新增 `EUROPE_TRADITIONAL_BAR_AGGREGATION`，扩展 `BarAggregation`
- [x] 1.2 `align.py` 新增 `merge_sunday_bars` 纯函数（UTC 周日并入下一根周一，末尾孤立周日保留）

## 2. 接入

- [x] 2.1 REST `fetch_bars`：`europe-traditional` 在透传序列上应用周日合并
- [x] 2.2 SSE `Aggregator._poll`：`europe-traditional` 实时尾部应用周日合并（轮询计划等同 native）
- [x] 2.3 probe `capabilities.bars` 上报 `barAggregations` 三值列表

## 3. 验证

- [x] 3.1 `test_align.py`：周日并入 OHLC 合并、无周日 no-op、末尾孤立周日保留
- [x] 3.2 `test_routes.py`：`europe-traditional` 日线请求回显与合并生效
- [x] 3.3 `openspec validate --all --strict` 通过
