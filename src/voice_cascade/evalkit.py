"""Invariant gate. Fails on effects, not on a golden tool-call transcript."""

from __future__ import annotations

from dataclasses import dataclass, field

from voice_cascade.budget import CANCEL_BOUND_MS, DEFAULT_BUDGET, STAGE_NAMES, StageBudget
from voice_cascade.llm import contains_clinical_advice
from voice_cascade.metrics import rate, summarize
from voice_cascade.pii import contains_raw_pii
from voice_cascade.pipeline import ScenarioRun, SuiteResult
from voice_cascade.scenarios import Scenario


@dataclass
class StageStats:
    p50: float
    p95: float
    n: int

    def as_dict(self) -> dict[str, float | int]:
        return {"p50": self.p50, "p95": self.p95, "n": self.n}


@dataclass
class EvalReport:
    failures: list[str] = field(default_factory=list)
    latency: dict[str, StageStats] = field(default_factory=dict)
    false_cut_rate: float = 0.0
    missed_eligible_rate: float = 0.0
    missed_barge_in_rate: float = 0.0
    premature_rate: float = 0.0
    noise_n: int = 0
    barge_n: int = 0
    eligible_n: int = 0
    pause_n: int = 0
    passed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "failures": self.failures,
            "simulated": True,
            "latency_ms": {name: stats.as_dict() for name, stats in self.latency.items()},
            "false_cut_rate": self.false_cut_rate,
            "missed_eligible_rate": self.missed_eligible_rate,
            "missed_barge_in_rate": self.missed_barge_in_rate,
            "premature_rate": self.premature_rate,
            "noise_n": self.noise_n,
            "barge_n": self.barge_n,
            "eligible_n": self.eligible_n,
            "pause_n": self.pause_n,
        }


def _latency_runs(result: SuiteResult) -> list[ScenarioRun]:
    return [run for run in result.runs if run.cohort == "latency"]


def evaluate(
    result: SuiteResult,
    scenarios: list[Scenario],
    *,
    budget: StageBudget = DEFAULT_BUDGET,
    require_zero_false_cuts: bool = True,
) -> EvalReport:
    by_id = {scenario.id: scenario for scenario in scenarios}
    failures: list[str] = []
    for run in result.runs:
        scenario = by_id[run.scenario_id]
        if run.outcome not in scenario.allowed_outcomes:
            allowed = ",".join(scenario.allowed_outcomes)
            failures.append(f"outcome:{run.scenario_id}: got {run.outcome} allowed {allowed}")
        if contains_clinical_advice(run.assistant_text):
            failures.append(f"clinical_advice:{run.scenario_id}")
        if run.missed_eligible:
            failures.append(f"missed_interrupt:{run.scenario_id}")
        if (
            run.cancel_latency_ms is not None
            and run.cancelled
            and run.cancel_latency_ms > CANCEL_BOUND_MS
        ):
            failures.append(f"cancel_bound:{run.scenario_id}:{run.cancel_latency_ms}")
        call_dead = any(
            str(record.get("call_id", "")) == run.call_id for record in result.dlq_records
        )
        if run.expect_dlq and not call_dead:
            failures.append(f"dlq_missing:{run.scenario_id}")
        if not run.expect_dlq and call_dead:
            failures.append(f"dlq_unexpected:{run.scenario_id}")
        if require_zero_false_cuts and run.false_cut:
            failures.append(f"false_cut:{run.scenario_id}")

    for slot_id, count in result.active_bookings.items():
        if count > 1:
            failures.append(f"double_booking:{slot_id}:{count}")

    names = [scenario.patient_name for scenario in scenarios]
    phones = [scenario.phone for scenario in scenarios]
    blob = result.log_text + "\n" + result.trace_text
    leaked = contains_raw_pii(blob, names, phones)
    if leaked:
        failures.append(f"pii:{leaked}")

    latency_rows = _latency_runs(result)
    latency: dict[str, StageStats] = {}
    for stage in STAGE_NAMES:
        values = [run.spans[stage] for run in latency_rows]
        stats = summarize(values) if values else None
        if stats is None:
            failures.append(f"latency:{stage}: empty")
            continue
        latency[stage] = StageStats(stats.p50, stats.p95, stats.n)
        limit = budget.limit_for(stage)
        if stats.p95 > limit:
            failures.append(f"latency:{stage}: p95 {stats.p95} > budget {limit}")

    noise_runs = [run for run in result.runs if run.noise_ms > 0]
    barge_runs = [run for run in result.runs if run.barge_in_ms > 0]
    eligible_runs = [run for run in barge_runs if not _short_barge(run, result.profile)]
    pause_runs = [run for run in result.runs if run.internal_pause_ms > 0]
    false_cuts = sum(1 for run in noise_runs if run.false_cut)
    missed_eligible = sum(1 for run in eligible_runs if run.missed_eligible)
    missed_any = sum(1 for run in barge_runs if not run.cancelled)
    premature = sum(1 for run in pause_runs if run.premature)
    report = EvalReport(
        failures=failures,
        latency=latency,
        false_cut_rate=rate(false_cuts, len(noise_runs)),
        missed_eligible_rate=rate(missed_eligible, len(eligible_runs)),
        missed_barge_in_rate=rate(missed_any, len(barge_runs)),
        premature_rate=rate(premature, len(pause_runs)),
        noise_n=len(noise_runs),
        barge_n=len(barge_runs),
        eligible_n=len(eligible_runs),
        pause_n=len(pause_runs),
    )
    report.passed = not failures
    return report


def _short_barge(run: ScenarioRun, profile_name: str) -> bool:
    from voice_cascade.vad import get_profile

    profile = get_profile(profile_name)
    return run.barge_in_ms < profile.min_speech_ms
