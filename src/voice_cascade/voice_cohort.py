"""100-call SIMULATED cohort. PCM is synthetic. Provider stages are seeded draws.

Nothing in this module calls a speech, language, or synthesis provider.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

from voice_cascade.latency import LatencySampler
from voice_cascade.logging_setup import ListHandler, log_event
from voice_cascade.metrics import (
    assert_uniform_provenance,
    bootstrap_interval,
    rate,
    summarize,
)
from voice_cascade.synth_audio import CallDraw, draw_calls, render_turn
from voice_cascade.turn_machine import TURN_PROFILES, get_turn_profile
from voice_cascade.turn_session import TurnObservation, run_clip

# [EST] starting gates from the design. Not a claim about real callers.
FALSE_BARGE_MAX = 0.05
MISSED_BARGE_MAX = 0.05
REACTION_P95_MAX = 300
ENDPOINT_P95_MAX = 900
PREMATURE_MAX = 0.05
BOOTSTRAP_RESAMPLES = 2000


@dataclass
class CohortReport:
    profile: str
    seed: int
    n_calls: int
    n_turns: int
    observations: list[TurnObservation] = field(default_factory=list)
    stages: dict[str, list[int]] = field(default_factory=dict)
    cold_stages: dict[str, list[int]] = field(default_factory=dict)
    conditions: list[dict[str, object]] = field(default_factory=list)
    overlaps: list[int] = field(default_factory=list)
    log_lines: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def _stage_row(values: list[int], *, seed: int, stage: str) -> dict[str, object]:
    if not values:
        return {
            "stage": stage,
            "p50": 0,
            "p95": 0,
            "p95_bootstrap_low": 0,
            "p95_bootstrap_high": 0,
            "n": 0,
            "provenance": "SIMULATED",
            "unit": "ms",
            "percentile_method": "inclusive linear (NumPy type 7)",
        }
    stats = summarize(values)
    low, high = bootstrap_interval(values, 95, seed=seed, resamples=BOOTSTRAP_RESAMPLES)
    return {
        "stage": stage,
        "p50": stats.p50,
        "p95": stats.p95,
        "p95_bootstrap_low": low,
        "p95_bootstrap_high": high,
        "n": stats.n,
        "provenance": "SIMULATED",
        "unit": "ms",
        "percentile_method": "inclusive linear (NumPy type 7)",
        "label": "SIMULATED",
    }


def run_cohort(
    *,
    seed: int = 42,
    n_calls: int = 100,
    profile_name: str = "balanced",
    echo_guard: bool = True,
    draws: list[CallDraw] | None = None,
) -> CohortReport:
    profile = get_turn_profile(profile_name)
    chosen = draws if draws is not None else draw_calls(seed, n_calls)
    logger = logging.getLogger("voice_cascade.voice")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = ListHandler()
    logger.addHandler(handler)
    report = CohortReport(profile=profile.name, seed=seed, n_calls=len(chosen), n_turns=0)
    stage_names = (
        "vad_endpoint_ms",
        "stt_final_ms",
        "llm_ttft_ms",
        "tool_ms",
        "tts_ttfb_ms",
        "e2e_ms",
    )
    report.stages = {name: [] for name in stage_names}
    report.cold_stages = {name: [] for name in stage_names}
    for call in chosen:
        for turn_index, event in enumerate(call.events):
            turn_id = f"{call.call_id}:t{turn_index + 1:02d}"
            clip = render_turn(
                seed=seed + turn_index + 1,
                pause_ms=call.pause_ms,
                noise_kind=call.noise_kind,
                agent_event=event,
                trailing_silence_ms=profile.end_silence_ms,
            )
            clip.condition["snr_db_tag"] = call.snr_db
            clip.condition["call_id"] = call.call_id
            clip.condition["turn_id"] = turn_id
            observed = run_clip(clip, profile, echo_guard=echo_guard)
            report.observations.append(observed)
            report.n_turns += 1
            report.conditions.append(dict(clip.condition))
            spans = _spans(seed, turn_id, turn_index, observed)
            for name, value in spans.items():
                if name == "overlap_ms":
                    if value:
                        report.overlaps.append(value)
                    continue
                if name == "tool_ms" and value == 0 and turn_index != 0:
                    continue
                report.stages[name].append(value)
                if turn_index == 0:
                    report.cold_stages[name].append(value)
            log_event(
                logger,
                "turn.scored",
                "synthetic turn scored",
                {
                    "call_id": call.call_id,
                    "turn_id": turn_id,
                    "span_id": f"{turn_id}:vad",
                    "provenance": "SIMULATED",
                    "agent_event": event,
                    "endpoint_delay_ms": observed.endpoint_delay_ms,
                    "false_cancel": observed.false_cancel,
                    "history_ok": observed.history_ok,
                },
            )
    report.log_lines = list(handler.lines)
    report.failures = _failures(report)
    return report


def _spans(seed: int, turn_id: str, turn_index: int, observed: TurnObservation) -> dict[str, int]:
    sampler = LatencySampler(seed, turn_id)
    vad = max(0, observed.endpoint_delay_ms)
    overlap = 0
    # Fourth turn of every 5th call. Kept off the cold-start turn (index 0)
    # so the cold-start table is not an artifact of this rule.
    call_number = int(turn_id.split(":", 1)[0].rsplit("-", 1)[-1])
    if turn_index == 3 and call_number % 5 == 0:
        overlap = sampler.draw("stt")
        stt = 0
    else:
        stt = sampler.draw("stt")
    llm = sampler.draw("llm")
    tool = sampler.draw("tool") if turn_index == 0 else 0
    tts = sampler.draw("tts")
    e2e = vad + stt + llm + tool + tts
    return {
        "vad_endpoint_ms": vad,
        "stt_final_ms": stt,
        "llm_ttft_ms": llm,
        "tool_ms": tool,
        "tts_ttfb_ms": tts,
        "e2e_ms": e2e,
        "overlap_ms": overlap,
    }


def _failures(report: CohortReport) -> list[str]:
    obs = report.observations
    failures: list[str] = []
    distractors = [item for item in obs if item.distractor]
    false_n = sum(1 for item in distractors if item.false_cancel)
    false_rate = rate(false_n, len(distractors))
    barges = [item for item in obs if item.true_barge]
    missed = sum(1 for item in barges if not item.barge_cancelled)
    missed_rate = rate(missed, len(barges))
    reactions = [item.reaction_ms for item in barges if item.reaction_ms is not None]
    pauses = [item for item in obs if item.has_internal_pause]
    premature_n = sum(1 for item in pauses if item.premature)
    premature_rate = rate(premature_n, len(pauses))
    history_bad = sum(1 for item in obs if not item.history_ok)
    if false_rate > FALSE_BARGE_MAX:
        failures.append(f"false_barge_in:{false_rate:.3f}> {FALSE_BARGE_MAX}")
    if missed_rate > MISSED_BARGE_MAX:
        failures.append(f"missed_barge_in:{missed_rate:.3f}> {MISSED_BARGE_MAX}")
    if reactions:
        reaction_p95 = summarize(reactions).p95
        if reaction_p95 > REACTION_P95_MAX:
            failures.append(f"reaction_p95:{reaction_p95}> {REACTION_P95_MAX}")
    else:
        failures.append("reaction:empty")
    endpoint_values = report.stages.get("vad_endpoint_ms", [])
    if endpoint_values:
        endpoint_p95 = summarize(endpoint_values).p95
        if endpoint_p95 > ENDPOINT_P95_MAX:
            failures.append(f"endpoint_p95:{endpoint_p95}> {ENDPOINT_P95_MAX}")
    if premature_rate > PREMATURE_MAX:
        failures.append(f"premature:{premature_rate:.3f}> {PREMATURE_MAX}")
    if history_bad:
        failures.append(f"history_matches_playback:{history_bad}")
    for line in report.log_lines:
        if '"call_id"' not in line or '"turn_id"' not in line:
            failures.append("log_missing_correlation")
            break
    return failures


def cohort_document(report: CohortReport) -> dict[str, object]:
    rows = [
        _stage_row(values, seed=report.seed + index, stage=name)
        for index, (name, values) in enumerate(report.stages.items())
    ]
    cold_rows = [
        _stage_row(values, seed=report.seed + 100 + index, stage=name)
        for index, (name, values) in enumerate(report.cold_stages.items())
    ]
    assert_uniform_provenance(rows)
    assert_uniform_provenance(cold_rows)
    obs = report.observations
    distractors = [item for item in obs if item.distractor]
    false_n = sum(1 for item in distractors if item.false_cancel)
    barges = [item for item in obs if item.true_barge]
    missed = sum(1 for item in barges if not item.barge_cancelled)
    reactions = [item.reaction_ms for item in barges if item.reaction_ms is not None]
    pauses = [item for item in obs if item.has_internal_pause]
    premature_n = sum(1 for item in pauses if item.premature)
    history_bad = sum(1 for item in obs if not item.history_ok)
    reaction_stats = summarize(reactions) if reactions else None
    counts = Counter(str(item.get("agent_event", "")) for item in report.conditions)
    pause_counts: Counter[int] = Counter()
    for item in report.conditions:
        raw_pause = item.get("pause_ms")
        if isinstance(raw_pause, int):
            pause_counts[raw_pause] += 1
    return {
        "title": "SIMULATED latency report",
        "provenance": "SIMULATED",
        "simulated": True,
        "profile": report.profile,
        "seed": report.seed,
        "n_calls": report.n_calls,
        "n_turns": report.n_turns,
        "percentile_method": "inclusive linear (NumPy type 7)",
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "cold_start_rule": "first turn of each call, fixed before the run",
        "stages": rows,
        "cold_start_stages": cold_rows,
        "stt_overlap_n": len(report.overlaps),
        "stt_overlap_note": (
            "When a seeded STT draw is treated as finalizing before the endpoint, "
            "stt_final_ms is 0 and the draw is counted here instead of being hidden."
        ),
        "turn_taking": {
            "provenance": "SIMULATED",
            "false_barge_in_rate": rate(false_n, len(distractors)),
            "false_barge_in_n": false_n,
            "false_barge_in_opportunities": len(distractors),
            "missed_barge_in_rate": rate(missed, len(barges)),
            "missed_barge_in_n": missed,
            "true_barge_n": len(barges),
            "reaction_p50_ms": None if reaction_stats is None else reaction_stats.p50,
            "reaction_p95_ms": None if reaction_stats is None else reaction_stats.p95,
            "endpoint_p95_ms": summarize(report.stages["vad_endpoint_ms"]).p95
            if report.stages["vad_endpoint_ms"]
            else None,
            "premature_endpoint_rate": rate(premature_n, len(pauses)),
            "premature_n": premature_n,
            "pause_n": len(pauses),
            "history_violations": history_bad,
            "gates_est": {
                "false_barge_in_max": FALSE_BARGE_MAX,
                "missed_barge_in_max": MISSED_BARGE_MAX,
                "reaction_p95_max_ms": REACTION_P95_MAX,
                "endpoint_p95_max_ms": ENDPOINT_P95_MAX,
                "premature_max": PREMATURE_MAX,
                "history_violations_max": 0,
            },
        },
        "condition_counts": dict(counts),
        "pause_ms_counts": {str(key): value for key, value in sorted(pause_counts.items())},
        "snr_note": (
            "snr_db is a draw tag only. The energy-floor noise bed does not change with it. "
            "SIMULATED. Not a measured signal-to-noise ratio."
        ),
        "echo_note": "Echo guard is a correlation heuristic, not acoustic echo cancellation.",
        "failures": report.failures,
        "passed": report.passed,
        "profiles_available": sorted(TURN_PROFILES),
    }


def echo_guard_off_rate(*, seed: int = 42, n: int = 20) -> float:
    """False barge-in rate with the echo guard disabled. Used by the forced regression."""

    profile = get_turn_profile("balanced")
    false_n = 0
    for index in range(n):
        clip = render_turn(
            seed=seed + index,
            pause_ms=256,
            agent_event="echo",
            trailing_silence_ms=profile.end_silence_ms,
        )
        observed = run_clip(clip, profile, echo_guard=False)
        if observed.false_cancel:
            false_n += 1
    return rate(false_n, n)
