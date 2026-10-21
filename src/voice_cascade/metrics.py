"""Percentiles on the simulated clock. Method is NumPy inclusive linear (type 7)."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass


def percentile(values: Sequence[int] | Sequence[float], p: float) -> float:
    if not values:
        raise ValueError("percentile of empty sample")
    if p < 0 or p > 100:
        raise ValueError("percentile out of range")
    ordered = sorted(float(item) for item in values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (p / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
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


def bootstrap_interval(
    values: Sequence[int],
    p: float,
    *,
    seed: int,
    resamples: int = 2000,
) -> tuple[float, float]:
    """Seeded percentile bootstrap. The interval is part of a SIMULATED report."""

    if not values:
        raise ValueError("bootstrap of empty sample")
    rng = random.Random(seed)
    n = len(values)
    drawn = [percentile([values[rng.randrange(n)] for _ in range(n)], p) for _ in range(resamples)]
    low = percentile(drawn, 2.5)
    high = percentile(drawn, 97.5)
    return low, high


def assert_uniform_provenance(rows: Sequence[dict[str, object]]) -> None:
    """Refuse a table that mixes SIMULATED and MEASURED, or omits the label."""

    labels = {str(row.get("provenance", "")) for row in rows}
    if labels not in ({"SIMULATED"}, {"MEASURED"}):
        raise ValueError(f"mixed or missing provenance: {sorted(labels)}")
