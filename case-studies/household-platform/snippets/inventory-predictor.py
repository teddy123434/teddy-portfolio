# snippet: 庫存消耗速率預測與信心水準計算
# 節錄自庫存管理模組，未經修改（純演算法邏輯，不含任何使用者或商品資料）

from __future__ import annotations
from datetime import timedelta, date
from enum import Enum
from typing import List, Optional, Sequence
from app.inventory.models import Count, Restock


WINDOW_SIZE = 4
COUNT_STALE_DAYS = 30
CV_HIGH_THRESHOLD = 0.5
MIN_COUNTS_FOR_HIGH_CONFIDENCE = 3


class Confidence(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _interval_rates(counts: Sequence[Count], restocks: Sequence[Restock]) -> tuple[List[float], List[float]]:
    if len(counts) < 2:
        return [], []
    sorted_counts = sorted(counts, key=lambda c: c.timestamp)
    intervals = sorted_counts[-(WINDOW_SIZE + 1):]
    rates: List[float] = []
    weights: List[float] = []
    for i in range(1, len(intervals)):
        prev, curr = intervals[i - 1], intervals[i]
        days = (curr.timestamp - prev.timestamp).total_seconds() / 86400
        if days <= 0:
            continue
        restock_qty = sum(
            r.quantity for r in restocks
            if prev.timestamp < r.timestamp <= curr.timestamp
        )
        consumed = max(0.0, prev.quantity + restock_qty - curr.quantity)
        rates.append(consumed / days)
        weights.append(float(i))
    return rates, weights


def consumption_per_day(counts: Sequence[Count], restocks: Sequence[Restock]) -> float:
    """Weighted average daily consumption. Newer intervals get higher weight."""
    rates, weights = _interval_rates(counts, restocks)
    if not rates:
        return 0.0
    return sum(r * w for r, w in zip(rates, weights)) / sum(weights)


def interval_rates_for_confidence(counts: Sequence[Count], restocks: Sequence[Restock]) -> List[float]:
    rates, _ = _interval_rates(counts, restocks)
    return rates


def predicted_finish_date(last_count: Count, rate_per_day: float) -> Optional[date]:
    if rate_per_day <= 0:
        return None
    return (last_count.timestamp + timedelta(days=last_count.quantity / rate_per_day)).date()


def coefficient_of_variation(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    if mean == 0:
        return 0.0
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    return (variance ** 0.5) / mean


def confidence_level(num_counts: int, cv: float, days_since_last_count: int) -> Confidence:
    if num_counts < MIN_COUNTS_FOR_HIGH_CONFIDENCE or days_since_last_count > COUNT_STALE_DAYS:
        return Confidence.LOW
    if cv > CV_HIGH_THRESHOLD:
        return Confidence.MEDIUM
    return Confidence.HIGH
