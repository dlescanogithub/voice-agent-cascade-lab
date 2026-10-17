from __future__ import annotations

from pathlib import Path

from voice_cascade.config import Settings
from voice_cascade.evalkit import evaluate
from voice_cascade.metrics import percentile
from voice_cascade.pipeline import run_suite
from voice_cascade.scenarios import build_scenarios


def test_percentile_type7() -> None:
    assert percentile([770, 860, 950], 50) == 860
    assert percentile([10], 95) == 10


def test_scenario_catalog_covers_the_script() -> None:
    scenarios = build_scenarios()
    assert len(scenarios) >= 30
    assert sum(1 for item in scenarios if item.cohort == "latency") == 36
    assert sum(1 for item in scenarios if item.noise_ms) >= 6
    assert sum(1 for item in scenarios if item.barge_in_ms >= 200) >= 4
    assert sum(1 for item in scenarios if 0 < item.barge_in_ms < 120) >= 4
    assert sum(1 for item in scenarios if item.internal_pause_ms >= 300) >= 4
    assert sum(1 for item in scenarios if item.wer > 0) >= 6
    assert {item.fault_mode for item in scenarios if item.fault_mode} >= {
        "http_500",
        "timeout_before_commit",
        "slow_after_commit",
    }
    assert any(item.duplicate_submit for item in scenarios)
    assert any(item.conflict_submit for item in scenarios)
    assert len({item.id for item in scenarios}) == len(scenarios)


def test_balanced_gate_passes_with_simulated_budget(tmp_path: Path) -> None:
    scenarios = build_scenarios()
    result = run_suite(
        scenarios,
        data_dir=tmp_path,
        settings=Settings(),
        profile_name="balanced",
    )
    report = evaluate(result, scenarios)
    assert report.passed, report.failures
    assert report.latency["e2e_ms"].p50 == 860
    assert report.latency["e2e_ms"].p95 == 950
    assert report.latency["e2e_ms"].n == 36
    assert report.latency["vad_endpoint_ms"].p95 == 400
    assert report.latency["stt_final_ms"].p95 == 160
    assert report.latency["llm_ttft_ms"].p95 == 140
    assert report.latency["tool_webhook_ms"].p50 == 90
    assert report.latency["tool_webhook_ms"].p95 == 180
    assert report.latency["tts_ttfb_ms"].p95 == 70
    assert report.false_cut_rate == 0
    assert report.missed_eligible_rate == 0
    assert report.missed_barge_in_rate == 0.5
    assert report.premature_rate == 0
    assert report.noise_n == 6
    assert report.barge_n == 8
    blob = result.log_text + result.trace_text
    assert "Quillay" not in blob
    assert "+54911" not in blob
    assert "local-demo-not-a-secret" not in blob
    assert '"phone": "[REDACTED]"' in result.log_text or "[REDACTED]" in result.log_text
    by_id = {run.scenario_id: run for run in result.runs}
    assert by_id["L11"].outcome == "booked"
    assert by_id["L11"].spans["e2e_ms"] == 950
    assert by_id["L20"].outcome == "slots_offered"
    assert by_id["L26"].outcome == "cancelled"
    assert by_id["L28"].outcome == "escalated"
    assert by_id["R01"].outcome == "booked"
    assert by_id["R01"].tool_names.count("book_appointment") == 2
    assert result.active_bookings["slot-r01"] == 1
    assert by_id["R02"].outcome == "escalated"
    assert result.active_bookings["slot-r02"] == 1
    assert by_id["R04"].outcome == "escalated"
    assert any(record.get("call_id") == "R04" for record in result.dlq_records)
    assert by_id["L22"].premature is False
    assert '"partials":' in result.trace_text


def test_profile_tradeoffs(tmp_path: Path) -> None:
    scenarios = build_scenarios()
    aggressive = run_suite(
        scenarios,
        data_dir=tmp_path / "aggressive",
        settings=Settings(),
        profile_name="aggressive",
    )
    patient = run_suite(
        scenarios,
        data_dir=tmp_path / "patient",
        settings=Settings(),
        profile_name="patient",
    )
    aggressive_report = evaluate(aggressive, scenarios, require_zero_false_cuts=False)
    patient_report = evaluate(patient, scenarios, require_zero_false_cuts=True)
    assert aggressive_report.false_cut_rate == 1
    assert aggressive_report.missed_eligible_rate == 0
    assert aggressive_report.missed_barge_in_rate == 0
    assert aggressive_report.premature_rate == 1
    assert aggressive_report.latency["e2e_ms"].p95 == 730
    assert aggressive_report.latency["e2e_ms"].p50 == 640
    gated = evaluate(aggressive, scenarios, require_zero_false_cuts=True)
    assert gated.passed is False
    assert any(item.startswith("false_cut:") for item in gated.failures)
    assert patient_report.passed, patient_report.failures
    assert patient_report.false_cut_rate == 0
    assert patient_report.missed_eligible_rate == 0
    assert patient_report.premature_rate == 0
    assert patient_report.latency["e2e_ms"].p95 == 1350
    assert patient_report.latency["e2e_ms"].p50 == 1260
    assert patient_report.latency["vad_endpoint_ms"].p95 == 800


def test_regression_poison_fails_and_safe_cassette_does_not(tmp_path: Path) -> None:
    scenarios = build_scenarios()
    poisoned = run_suite(
        scenarios,
        data_dir=tmp_path / "bad",
        settings=Settings(disable_clinical_guard=True),
        profile_name="balanced",
        regression=True,
    )
    bad = evaluate(poisoned, scenarios)
    assert bad.passed is False
    assert any(item.startswith("clinical_advice:") for item in bad.failures)
    safe = run_suite(
        scenarios,
        data_dir=tmp_path / "safe",
        settings=Settings(disable_clinical_guard=True),
        profile_name="balanced",
        regression=False,
    )
    report = evaluate(safe, scenarios)
    assert report.passed, report.failures
