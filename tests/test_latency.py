from __future__ import annotations

import random

from voice_cascade.budget import DEFAULT_BUDGET
from voice_cascade.config import Settings
from voice_cascade.latency import LatencyLaw, LatencySampler, sample_lognormal_ms


def test_sigma_zero_returns_the_median() -> None:
    law = LatencyLaw(stt_median_ms=160, stt_sigma=0)
    sampler = LatencySampler(7, "L11", law)
    assert sampler.draw("stt") == 160


def test_draws_are_deterministic_and_depend_on_the_scenario() -> None:
    law = LatencyLaw()
    first = LatencySampler(42, "L11", law).draw("stt")
    second = LatencySampler(42, "L11", law).draw("stt")
    other = LatencySampler(42, "L12", law).draw("stt")
    assert first == second
    assert first != other


def test_samples_are_not_capped_at_the_budget() -> None:
    law = LatencyLaw(stt_median_ms=100_000, stt_sigma=0)
    drawn = LatencySampler(1, "over", law).draw("stt")
    assert drawn > DEFAULT_BUDGET.stt_final_ms


def test_tool_draws_advance_an_index() -> None:
    law = LatencyLaw(tool_sigma=0.2)
    sampler = LatencySampler(42, "L11", law)
    first = sampler.draw("tool")
    second = sampler.draw("tool")
    again = LatencySampler(42, "L11", law)
    assert again.draw("tool") == first
    assert again.draw("tool") == second
    assert first != second


def test_vad_median_is_required() -> None:
    try:
        LatencySampler(1, "x").draw("vad")
    except ValueError as exc:
        assert "end-silence" in str(exc)
    else:
        raise AssertionError("vad draw without a median should fail")


def test_box_muller_lognormal_matches_across_calls() -> None:
    left = sample_lognormal_ms(random.Random("seed-a"), 90, 0.18)
    right = sample_lognormal_ms(random.Random("seed-a"), 90, 0.18)
    assert left == right
    assert left >= 1


def test_env_overrides_the_simulated_law() -> None:
    settings = Settings.from_env(
        {"VOICE_CASCADE_STT_MEDIAN_MS": "80", "VOICE_CASCADE_STT_SIGMA": "0"}
    )
    law = settings.latency_law()
    assert law.stt_median_ms == 80
    assert law.stt_sigma == 0
    assert LatencySampler(1, "s", law).draw("stt") == 80
