## 1. Specification

- [x] 1.1 定义 quotes SSE 的订阅身份（instrumentId 列表 + 源默认聚合口径）。
- [x] 1.2 定义 quote 帧字段与「最新价 / 昨收」的取值来源。
- [x] 1.3 定义基准不足时的补齐行为：必须拉历史补齐，不得空转。

## 2. Implementation

- [x] 2.1 `mt5connector/quotes.py` 新增 `seed`，复用尾部窗口维护逻辑。
- [x] 2.2 `/quotes` 建连时按 `/bars` 同一口径拉历史日线并注入基准。
- [x] 2.3 基准查询失败不得影响连接建立。

## 3. Validation

- [x] 3.1 补测试：快照仅一根时由历史补齐并推送；无基准时返回空且不抛错。
- [x] 3.2 运行 `npx @fission-ai/openspec validate --all --strict`。
- [x] 3.3 运行 `uv run pytest`。
- [x] 3.4 手工验证 `/quotes` 在 `europe-traditional` 下推送 quote 帧。
