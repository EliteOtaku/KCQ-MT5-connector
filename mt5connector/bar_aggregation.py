# K 线聚合模式：协议枚举及其领域语义的单一事实来源。

from __future__ import annotations

from typing import Literal, TypeAlias

ORIGINAL_BAR_AGGREGATION = "original"
ALIGNED_BAR_AGGREGATION = "aligned"
EUROPE_TRADITIONAL_BAR_AGGREGATION = "europe-traditional"
BAR_AGGREGATIONS = (
    ORIGINAL_BAR_AGGREGATION,
    ALIGNED_BAR_AGGREGATION,
    EUROPE_TRADITIONAL_BAR_AGGREGATION,
)

BarAggregation: TypeAlias = Literal["original", "aligned", "europe-traditional"]
