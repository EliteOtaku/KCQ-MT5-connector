# Add Realtime Tick Stream

## Why

MT5 终端能提供逐笔 tick，但连接器目前只把 `symbol_info_tick` 当作内部轮询探针
（且只用 `time` 字段），前端收不到任何 tick。KMAP 的高频链路需要逐笔行情，
现有 Bar 流（`snapshot`/`forming`/`closed`）无法替代。

## What Changes

- 新增 SSE 端点 `GET /api/v1/market-data/sources/mt5/ticks/stream?symbol=`；
  流身份仅为 symbol（tick 与 period / barAggregation 无关）。
- 新增 `ticks` 帧：`{type:'ticks', symbol, ticks:[{timestamp, bid, ask, last, volume}]}`，
  `timestamp` 为真 UTC 毫秒。
- 网关新增 `copy_ticks_from` 增量拉取（经单工作线程串行执行），返回完整 tick 序列；
  禁止用 `symbol_info_tick` 的「最后一笔」轮询冒充逐笔流（会丢中间 tick）。
- 复用 StreamHub 的 seq / 环形缓冲 / Last-Event-ID / keepalive 语义。
- 新增 tick 轮询间隔等配置，集中收口到 `app/config.py`。

## Non-goals

- 不提供历史 tick 的 REST 查询。
- 不改动现有 Bar 流协议与流身份。
- 不做 tick → K 线聚合（聚合仍由 MT5 原生 rates 提供）。
- 不改变服务器伪 UTC → 真 UTC 的偏移校正规则。
