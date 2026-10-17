"""Seeded lognormal draws for the simulated clock.

Parameters are [EST]. They are not a measurement of a speech, language, or
synthesis service. The median of each provider stage is the old fixed stage
time. The VAD charge uses the profile's end-silence as its median. Sigma
spreads the draws so a percentile gate can fail.

Draws use Box-Muller on random.Random.random(). random.gauss is not used,
because its algorithm is not stable across Python versions. The same seed and
scenario id always return the same milliseconds. Samples are not capped at
the budget. The floor is 1 ms.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

# [EST] Not measured on a provider. See docs/PROVENANCE.md and the README.
STT_MEDIAN_MS = 160.0
STT_SIGMA = 0.20
LLM_MEDIAN_MS = 140.0
LLM_SIGMA = 0.20
TTS_MEDIAN_MS = 70.0
TTS_SIGMA = 0.25
TOOL_MEDIAN_MS = 90.0
TOOL_SIGMA = 0.18
REPLAY_MEDIAN_MS = 15.0
REPLAY_SIGMA = 0.12
VAD_SIGMA = 0.03


def standard_normal(rng: random.Random) -> float:
    """One standard normal from two uniform draws (Box-Muller, cosine form)."""

    uniform = max(rng.random(), 1e-12)
    angle = rng.random()
    return math.sqrt(-2.0 * math.log(uniform)) * math.cos(math.tau * angle)


def sample_lognormal_ms(rng: random.Random, median_ms: float, sigma: float) -> int:
    if median_ms <= 0:
        raise ValueError("median_ms must be positive")
    if sigma < 0:
        raise ValueError("sigma must be non-negative")
    drawn = median_ms if sigma == 0 else median_ms * math.exp(sigma * standard_normal(rng))
    return max(1, round(drawn))


@dataclass(frozen=True)
class LatencyLaw:
    """[EST] parameters. Override with VOICE_CASCADE_*_MEDIAN_MS and *_SIGMA."""

    stt_median_ms: float = STT_MEDIAN_MS
    stt_sigma: float = STT_SIGMA
    llm_median_ms: float = LLM_MEDIAN_MS
    llm_sigma: float = LLM_SIGMA
    tts_median_ms: float = TTS_MEDIAN_MS
    tts_sigma: float = TTS_SIGMA
    tool_median_ms: float = TOOL_MEDIAN_MS
    tool_sigma: float = TOOL_SIGMA
    replay_median_ms: float = REPLAY_MEDIAN_MS
    replay_sigma: float = REPLAY_SIGMA
    vad_sigma: float = VAD_SIGMA

    def median_and_sigma(self, stage: str, median_override: float | None) -> tuple[float, float]:
        table: dict[str, tuple[float, float]] = {
            "stt": (self.stt_median_ms, self.stt_sigma),
            "llm": (self.llm_median_ms, self.llm_sigma),
            "tts": (self.tts_median_ms, self.tts_sigma),
            "tool": (self.tool_median_ms, self.tool_sigma),
            "replay": (self.replay_median_ms, self.replay_sigma),
            "vad": (0.0, self.vad_sigma),
        }
        try:
            median, sigma = table[stage]
        except KeyError as exc:
            known = ", ".join(sorted(table))
            raise KeyError(f"unknown latency stage {stage!r}; expected one of {known}") from exc
        if median_override is not None:
            median = median_override
        if stage == "vad" and median_override is None:
            raise ValueError("vad draws require the profile end-silence as the median")
        return median, sigma


class LatencySampler:
    """Independent stream per stage, indexed in call order, seeded by scenario."""

    def __init__(self, seed: int, scenario_id: str, law: LatencyLaw | None = None) -> None:
        self.seed = seed
        self.scenario_id = scenario_id
        self.law = law or LatencyLaw()
        self._counts: dict[str, int] = {}

    def draw(self, stage: str, *, median_ms: float | None = None) -> int:
        index = self._counts.get(stage, 0)
        self._counts[stage] = index + 1
        median, sigma = self.law.median_and_sigma(stage, median_ms)
        rng = random.Random(f"{self.seed}:{self.scenario_id}:{stage}:{index}")
        return sample_lognormal_ms(rng, median, sigma)
