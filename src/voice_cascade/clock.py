"""Deterministic clock. Tests never sleep on the wall clock."""

from __future__ import annotations


class SimulatedClock:
    def __init__(self) -> None:
        self.now_ms = 0

    def advance(self, ms: int) -> None:
        if ms < 0:
            raise ValueError("clock cannot go backwards")
        self.now_ms += ms
