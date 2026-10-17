"""Percentiles on the simulated clock. Method is NumPy inclusive linear (type 7)."""

from __future__ import annotations

import math
from dataclasses import dataclass


def percentile(values: list[int], p: float) -> float:
    if not values:
        raise ValueError("percentile of empty sample")
    if p < 0 or p > 100:
        raise ValueError("percentile out of range")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (p / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return float(ordered[low])
    fraction = rank - low
    return ordered[low] * (1.0 - fraction) + ordered[high] * fraction


@dataclass(frozen=True)
class PercentilePair:
    p50: float
    p95: float
    n: int

    def as_dict(self) -> dict[str, float | int]:
        return {"p50": self.p50, "p95": self.p95, "n": self.n}


def summarize(values: list[int]) -> PercentilePair:
    return PercentilePair(p50=percentile(values, 50), p95=percentile(values, 95), n=len(values))


def rate(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator
