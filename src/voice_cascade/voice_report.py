"""Markdown for the SIMULATED voice report. Numbers come from the cohort."""

from __future__ import annotations

import json
from pathlib import Path

from voice_cascade import __version__
from voice_cascade.fault_cohort import FaultCase
from voice_cascade.voice_cohort import CohortReport, cohort_document


def _fmt(value: object) -> str:
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return f"{value:.3f}"
    return str(value)


def render_markdown(
    cohort: CohortReport,
    faults: list[FaultCase],
    *,
    decisions_note: str,
) -> str:
    doc = cohort_document(cohort)
    lines = [
        "# SIMULATED voice extension report",
        "",
        "Every latency and turn-taking number on this page is **SIMULATED**.",
        "It was produced by the seeded clock and by synthetic PCM inside this repo.",
        "It is not a measurement of a speech, language, or synthesis provider.",
        "It is not evidence that a live deployment would be faster, safer, or cheaper.",
        "",
        f"Package version `{__version__}`. Profile `{cohort.profile}`. Seed `{cohort.seed}`.",
        f"Calls `{cohort.n_calls}`. Turns `{cohort.n_turns}`.",
        "Percentiles: inclusive linear (NumPy type 7).",
        "p95 bootstrap: 2,000 resamples, seeded. The interval is part of the SIMULATED result.",
        "Cold-start rows are the first turn of each call. That rule is fixed before the run.",
        "",
        decisions_note,
        "",
        "## SIMULATED per-stage latency",
        "",
        "| Stage | p50 (SIMULATED ms) | p95 (SIMULATED ms) | p95 bootstrap low | p95 bootstrap high | n |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    stages = doc["stages"]
    if isinstance(stages, list):
        for row in stages:
            if not isinstance(row, dict):
                continue
            lines.append(
                "| {stage} | {p50} | {p95} | {low} | {high} | {n} |".format(
                    stage=row["stage"],
                    p50=_fmt(row["p50"]),
                    p95=_fmt(row["p95"]),
                    low=_fmt(row["p95_bootstrap_low"]),
                    high=_fmt(row["p95_bootstrap_high"]),
                    n=row["n"],
                )
            )
    lines.extend(
        [
            "",
            "VAD endpoint delay is the state machine's hang time on synthetic audio",
            "(profile end-silence plus window alignment). STT, LLM, tool, and TTS",
            "are seeded lognormal draws with parameters marked [EST]. End to end is",
            "the sum of those stages. Caller audio time is not added on top.",
            f"STT draws treated as overlapping the endpoint: {doc['stt_overlap_n']}.",
            "Those turns record `stt_final_ms` as 0 and keep the draw in the overlap count.",
            "",
            "## SIMULATED cold start (first turn per call)",
            "",
            "| Stage | p50 (SIMULATED ms) | p95 (SIMULATED ms) | n |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    cold = doc["cold_start_stages"]
    if isinstance(cold, list):
        for row in cold:
            if not isinstance(row, dict):
                continue
            lines.append(
                f"| {row['stage']} | {_fmt(row['p50'])} | {_fmt(row['p95'])} | {row['n']} |"
            )
    taking = doc["turn_taking"]
    lines.extend(["", "## SIMULATED turn-taking (balanced gate, [EST] thresholds)", ""])
    if isinstance(taking, dict):
        lines.append(
            "False barge-in "
            f"{_fmt(taking['false_barge_in_rate'])} "
            f"({taking['false_barge_in_n']} / {taking['false_barge_in_opportunities']})."
        )
        lines.append(
            "Missed barge-in "
            f"{_fmt(taking['missed_barge_in_rate'])} "
            f"({taking['missed_barge_in_n']} / {taking['true_barge_n']})."
        )
        lines.append(
            "Reaction p50/p95 (SIMULATED ms) "
            f"{_fmt(taking['reaction_p50_ms'])} / {_fmt(taking['reaction_p95_ms'])}."
        )
        lines.append(f"Endpoint p95 (SIMULATED ms) {_fmt(taking['endpoint_p95_ms'])}.")
        lines.append(
            "Premature endpoint "
            f"{_fmt(taking['premature_endpoint_rate'])} "
            f"({taking['premature_n']} / {taking['pause_n']})."
        )
        lines.append(f"History violations: {taking['history_violations']}.")
    lines.extend(
        [
            "",
            str(doc["echo_note"]),
            str(doc["snr_note"]),
            "",
            "Pause draw (ms) used for the gate, all below the balanced end-silence of 416:",
            "",
            "| pause_ms | turns |",
            "| ---: | ---: |",
        ]
    )
    pauses = doc["pause_ms_counts"]
    if isinstance(pauses, dict):
        for key, value in pauses.items():
            lines.append(f"| {key} | {value} |")
    lines.extend(["", "Agent-event counts:", ""])
    counts = doc["condition_counts"]
    if isinstance(counts, dict):
        for key, value in sorted(counts.items()):
            lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Webhook fault cohort (in-process, SIMULATED)",
            "",
            "| Case | Pass | Attempts | Class | Detail |",
            "| --- | --- | ---: | --- | --- |",
        ]
    )
    for case in faults:
        lines.append(
            f"| {case.case_id} | {'yes' if case.passed else 'no'} | {case.attempts} | {case.error_class} | {case.detail} |"
        )
    lines.extend(
        [
            "",
            f"Turn-taking gate: {'pass' if cohort.passed else 'fail'}.",
            f"Webhook cases failing: {sum(1 for case in faults if not case.passed)}.",
            "",
            "This file is regenerated by `python -m voice_cascade eval-voice`.",
            "Do not compare these rows with the measured provider table in the README.",
            "",
        ]
    )
    return "\n".join(lines)


def write_voice_reports(
    cohort: CohortReport,
    faults: list[FaultCase],
    *,
    docs_dir: Path,
    reports_dir: Path,
    decisions_note: str,
) -> dict[str, object]:
    document = cohort_document(cohort)
    document["webhook_cases"] = [
        {
            "id": case.case_id,
            "passed": case.passed,
            "attempts": case.attempts,
            "error_class": case.error_class,
            "detail": case.detail,
            "provenance": "SIMULATED",
        }
        for case in faults
    ]
    document["version"] = __version__
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    reports_dir.mkdir(parents=True, exist_ok=True)
    docs_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / "latency_simulated.json").write_text(payload, encoding="utf-8")
    (docs_dir / "latency_simulated.json").write_text(payload, encoding="utf-8")
    markdown = render_markdown(cohort, faults, decisions_note=decisions_note)
    (docs_dir / "SIMULATED_LATENCY.md").write_text(markdown, encoding="utf-8")
    return document
