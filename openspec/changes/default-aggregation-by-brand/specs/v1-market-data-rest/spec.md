## MODIFIED Requirements

### Requirement: K 线请求显式声明聚合模式

`barAggregation` SHALL 改为可选：缺省时按终端品牌解析默认口径——Exness 终端（company/server
判定）缺省 `europe-traditional`，其余缺省 `original`。显式传值 SHALL 覆盖品牌默认。
响应 SHALL 回显实际生效口径。

probe SHALL 新增 `defaultBarAggregation` 字段，取值与上述缺省解析一致。

#### Scenario: Exness 终端缺省修正口径

- **WHEN** 请求 `period=daily` 且未携带 `barAggregation`，终端为 Exness
- **THEN** 实际口径 SHALL 为 `europe-traditional`（周日短棒并入周一）
- **THEN** 响应回显 `barAggregation=europe-traditional`，序列中 SHALL 无 UTC 周日 bar

#### Scenario: 非 Exness 终端缺省原生口径

- **WHEN** 请求未携带 `barAggregation`，终端非 Exness
- **THEN** 实际口径 SHALL 为 `original`，序列原样透传

#### Scenario: 显式传值覆盖默认

- **WHEN** Exness 终端请求携带 `barAggregation=original`
- **THEN** SHALL 返回未修正的原生序列

#### Scenario: probe 上报缺省口径

- **WHEN** 请求 probe
- **THEN** 响应 SHALL 含 `defaultBarAggregation` 字段，取值符合上述品牌规则
