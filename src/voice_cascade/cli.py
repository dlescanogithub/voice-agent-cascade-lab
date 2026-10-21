"""Command line. `python -m voice_cascade <command>` matches the Makefile targets."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import replace
from pathlib import Path

from voice_cascade import __version__
from voice_cascade.booking import BookingStore
from voice_cascade.clock import SimulatedClock
from voice_cascade.config import Settings
from voice_cascade.cost_estimate import dry_run_plan
from voice_cascade.evalkit import EvalReport, evaluate
from voice_cascade.fault_cohort import run_fault_cohort, trace_example, w06_shows_retries
from voice_cascade.live import LiveConfigError, LiveRequestError, run_live
from voice_cascade.logging_setup import configure_logging
from voice_cascade.pipeline import SuiteResult, run_suite
from voice_cascade.scenarios import build_scenarios
from voice_cascade.secretscan import scan_path
from voice_cascade.synth_audio import draw_calls, render_turn, write_clip
from voice_cascade.trace_join import format_turn
from voice_cascade.vad import PROFILES
from voice_cascade.voice_cohort import cohort_document, echo_guard_off_rate, run_cohort
from voice_cascade.voice_report import write_voice_reports
from voice_cascade.webhook import (
    InProcessTransport,
    JsonlDeadLetterQueue,
    WebhookApp,
    WebhookClient,
    replay_dead_letters,
    serve,
)


def _print_report(report: EvalReport, result: SuiteResult) -> None:
    print(
        "SIMULATED latency report "
        f"profile={result.profile} scenarios={len(result.runs)} "
        f"simulated=true version={__version__}"
    )
    for stage, stats in report.latency.items():
        print(f"{stage}: p50={_fmt(stats.p50)} p95={_fmt(stats.p95)} n={stats.n} (SIMULATED ms)")
    print(
        "rates "
        f"false_cut={report.false_cut_rate:.3f} "
        f"missed_eligible={report.missed_eligible_rate:.3f} "
        f"missed_barge_in={report.missed_barge_in_rate:.3f} "
        f"premature={report.premature_rate:.3f}"
    )
    print("invariants=" + ("pass" if report.passed else "fail"))
    for failure in report.failures:
        print(f"failure: {failure}")


def _fmt(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.3f}"


def _write_report(path: Path, report: EvalReport, result: SuiteResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict()
    payload["profile"] = result.profile
    payload["version"] = __version__
    payload["active_bookings"] = result.active_bookings
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _run(
    settings: Settings, profile: str, folder: str, *, regression: bool
) -> tuple[SuiteResult, EvalReport]:
    scenarios = build_scenarios()
    result = run_suite(
        scenarios,
        data_dir=Path(settings.data_dir) / folder,
        settings=settings,
        profile_name=profile,
        regression=regression,
    )
    report = evaluate(result, scenarios, require_zero_false_cuts=not regression)
    return result, report


DECISIONS_NOTE = (
    "Open decisions, not resolved: D1 default L1 (100x1) for the dry-run estimate; "
    "D2 default offline DSP audio (no paid TTS); D3 default bundle D (lowest list, [EST]); "
    "D4 Silero lane manual only, not a CI job; D5 v1 signatures accepted by default in 0.2.0 "
    "and marked deprecated. See docs/voice/OPEN_DECISIONS.md."
)


def _voice_extension(settings: Settings, *, write_docs: bool) -> int:
    cohort = run_cohort(seed=settings.seed, n_calls=100, profile_name="balanced", echo_guard=True)
    fault_settings = replace(settings, tool_deadline_ms=1500, jitter_ms=0)
    fault_root = Path(settings.data_dir) / "faults"
    faults = run_fault_cohort(fault_root, fault_settings)
    docs_dir = Path("docs") / "voice"
    reports_dir = Path("reports")
    document = cohort_document(cohort)
    if write_docs:
        write_voice_reports(
            cohort,
            faults,
            docs_dir=docs_dir,
            reports_dir=reports_dir,
            decisions_note=DECISIONS_NOTE,
        )
        example = trace_example(fault_root, fault_settings)
        (docs_dir / "TRACE_W01.md").write_text(example, encoding="utf-8")
    else:
        reports_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(document)
        payload["version"] = __version__
        (reports_dir / "latency_simulated.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    taking = document["turn_taking"]
    print(
        "SIMULATED voice cohort "
        f"calls={cohort.n_calls} turns={cohort.n_turns} "
        f"gate={'pass' if cohort.passed else 'fail'} version={__version__}"
    )
    if isinstance(taking, dict):
        print(
            "turn-taking "
            f"false_barge_in={taking['false_barge_in_rate']} "
            f"missed_barge_in={taking['missed_barge_in_rate']} "
            f"reaction_p95={taking['reaction_p95_ms']} "
            f"endpoint_p95={taking['endpoint_p95_ms']} "
            "(SIMULATED)"
        )
    for case in faults:
        if not case.passed:
            print(f"failure: webhook:{case.case_id}:{case.detail}")
    for failure in cohort.failures:
        print(f"failure: {failure}")
    if cohort.passed and all(case.passed for case in faults):
        return 0
    return 1


def cmd_eval(settings: Settings, profile: str) -> int:
    result, report = _run(settings, profile, "eval", regression=False)
    _print_report(report, result)
    _write_report(Path("reports") / "eval.json", report, result)
    if not report.passed:
        return 1
    if profile != "balanced":
        return 0
    return _voice_extension(settings, write_docs=False)


def cmd_eval_voice(settings: Settings) -> int:
    return _voice_extension(settings, write_docs=True)


def cmd_regression(settings: Settings) -> int:
    poisoned = replace(settings, disable_clinical_guard=True)
    result, report = _run(poisoned, "balanced", "regression", regression=True)
    _print_report(report, result)
    _write_report(Path("reports") / "regression.json", report, result)
    if report.passed:
        print("REGRESSION UNEXPECTEDLY PASSED")
        return 0
    print("REGRESSION FAILED AS REQUIRED")
    return 1


def cmd_turn_regression() -> int:
    observed = echo_guard_off_rate()
    print(f"echo-guard-off false_barge_in={observed:.3f} (SIMULATED)")
    if observed > 0.05:
        print("REGRESSION FAILED AS REQUIRED")
        return 1
    print("REGRESSION UNEXPECTEDLY PASSED")
    return 0


def cmd_webhook_regression(settings: Settings) -> int:
    poisoned = replace(settings, retry_nonretryable=True, jitter_ms=0, tool_deadline_ms=1500)
    case = w06_shows_retries(Path(settings.data_dir) / "regression-webhook", poisoned)
    print(f"W06 attempts={case.attempts} error_class={case.error_class} (SIMULATED)")
    if case.attempts > 1:
        print("REGRESSION FAILED AS REQUIRED")
        return 1
    print("REGRESSION UNEXPECTEDLY PASSED")
    return 0


def cmd_latency_report(settings: Settings) -> int:
    scenarios = build_scenarios()
    print(
        "SIMULATED latency report (seeded lognormal clock; placeholders until a real-provider run)"
    )
    for name in PROFILES:
        result = run_suite(
            scenarios,
            data_dir=Path(settings.data_dir) / f"report-{name}",
            settings=settings,
            profile_name=name,
            regression=False,
        )
        report = evaluate(result, scenarios, require_zero_false_cuts=False)
        e2e = report.latency["e2e_ms"]
        gated = evaluate(result, scenarios, require_zero_false_cuts=True)
        print(
            f"{name}: e2e_p50={_fmt(e2e.p50)} e2e_p95={_fmt(e2e.p95)} "
            f"false_cut={report.false_cut_rate:.3f} "
            f"missed_eligible={report.missed_eligible_rate:.3f} "
            f"missed_barge_in={report.missed_barge_in_rate:.3f} "
            f"premature={report.premature_rate:.3f} "
            f"gate={'pass' if gated.passed else 'fail'} "
            "(SIMULATED)"
        )
    return 0


def cmd_demo(settings: Settings) -> int:
    scenarios = [item for item in build_scenarios() if item.id in {"L11", "L20", "L26"}]
    result = run_suite(
        scenarios,
        data_dir=Path(settings.data_dir) / "demo",
        settings=settings,
        profile_name="balanced",
        regression=False,
    )
    print(f"voice-agent-cascade-lab {__version__} demo (simulated clock, fake providers)")
    for run in result.runs:
        print(
            f"{run.scenario_id} outcome={run.outcome} e2e_ms={run.spans['e2e_ms']} "
            f"false_cut={run.false_cut} cancelled={run.cancelled} (simulated)"
        )
    print("Gate for the full script: python -m voice_cascade eval")
    return 0


def cmd_dlq_replay(settings: Settings, dlq_path: Path, db_path: Path) -> int:
    store = BookingStore(db_path)
    try:
        app = WebhookApp(store, settings.hmac_secret)
        client = WebhookClient(
            InProcessTransport(app),
            SimulatedClock(),
            JsonlDeadLetterQueue(dlq_path),
            settings,
        )
        recovered, left = replay_dead_letters(JsonlDeadLetterQueue(dlq_path), client)
    finally:
        store.close()
    print(f"dlq-replay recovered={recovered} remaining={left}")
    return 0 if left == 0 else 1


def cmd_live_dry_run() -> int:
    raw = os.environ.get("MAX_LIVE_SPEND_USD", "").strip()
    cap = float(raw) if raw else None
    plan = dry_run_plan(cap)
    print(
        "live dry-run "
        f"provenance={plan['provenance']} "
        f"bundle={plan['bundle']} "
        f"estimated_usd={plan['estimated_usd']} "
        f"with_contingency={plan['estimated_usd_with_contingency']} "
        f"over_cap={plan['over_cap']} request_sent={plan['request_sent']}"
    )
    print("No request was sent.")
    return 2 if plan["over_cap"] else 0


def cmd_synth_audio(settings: Settings, seed: int, calls: int, out: Path) -> int:
    draws = draw_calls(seed, calls)
    count = 0
    for call in draws:
        profile_silence = 416
        for index, event in enumerate(call.events):
            clip = render_turn(
                seed=seed + index,
                pause_ms=call.pause_ms,
                noise_kind=call.noise_kind,
                agent_event=event,
                trailing_silence_ms=profile_silence,
            )
            write_clip(out / f"{call.call_id}-t{index + 1:02d}", clip)
            count += 1
    print(f"synth-audio wrote {count} clips to {out} (SIMULATED, seed={seed})")
    del settings
    return 0


def cmd_trace(turn_id: str, log_path: Path, trace_path: Path | None) -> int:
    text = format_turn(turn_id, log_path, trace_path)
    print(text, end="")
    return 1 if text.startswith("no events") else 0


def cmd_live(settings: Settings) -> int:
    try:
        payload = run_live(os.environ, Path(settings.data_dir) / "live")
    except LiveConfigError as exc:
        print(f"live: {exc}")
        return 2
    except LiveRequestError as exc:
        print(f"live: {exc}")
        return 1
    turns = payload.get("turns")
    count = len(turns) if isinstance(turns, list) else 0
    cost = payload.get("cost")
    precall = payload.get("precall_estimate_usd")
    estimated: object = None
    basis: object = None
    if isinstance(cost, dict):
        precall = cost.get("precall_estimate_usd", precall)
        estimated = cost.get("estimated_usd")
        basis = cost.get("cost_basis")
    print(
        f"{payload.get('title', 'live')} "
        f"turns={count} precall_estimate_usd={precall} "
        f"estimated_usd={estimated} cost_basis={basis} "
        f"price_date={payload.get('price_date')}"
    )
    invariants = payload.get("invariants")
    passed = True
    if isinstance(invariants, dict):
        passed = invariants.get("passed") is True
        raw_failures = invariants.get("failures")
        if isinstance(raw_failures, list):
            for item in raw_failures:
                print(f"failure: {item}")
    latency = payload.get("latency")
    if isinstance(latency, dict):
        e2e = latency.get("e2e_real_only")
        if isinstance(e2e, dict) and isinstance(e2e.get("warning"), str):
            print(f"warning: {e2e['warning']}")
    print(f"wrote {Path(settings.data_dir) / 'live' / 'results.json'}")
    print("README table 'Measured with real providers' is not updated by this command.")
    return 0 if passed else 1


def cmd_secretscan(root: Path) -> int:
    findings = scan_path(root)
    if findings:
        for finding in findings:
            print(f"secret-scan: {finding}")
        return 1
    print(f"secret-scan: clean ({root})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="voice-cascade")
    sub = parser.add_subparsers(dest="command", required=True)
    eval_parser = sub.add_parser("eval", help="run the invariant gate on the balanced profile")
    eval_parser.add_argument("--profile", default="balanced", choices=sorted(PROFILES))
    regression = sub.add_parser(
        "eval-regression",
        help="must fail: clinical guard off, or --turn-taking / --webhook",
    )
    regression.add_argument(
        "--turn-taking",
        action="store_true",
        help="echo guard off; false barge-in must exceed the gate",
    )
    regression.add_argument(
        "--webhook",
        action="store_true",
        help="treat poison 4xx as retryable; W06 must show retries",
    )
    sub.add_parser(
        "eval-voice",
        help="SIMULATED 100-call cohort, webhook faults, docs/voice report",
    )
    sub.add_parser(
        "latency-report", help="print simulated latency and barge-in rates for 3 profiles"
    )
    sub.add_parser("demo", help="run three scripted calls on the simulated clock")
    replay = sub.add_parser("dlq-replay", help="replay a JSONL dead-letter queue")
    replay.add_argument("--dlq", required=True)
    replay.add_argument("--db", required=True)
    scan = sub.add_parser("secretscan", help="scan a tree for committed secrets")
    scan.add_argument("path", nargs="?", default=".")
    live_parser = sub.add_parser(
        "live",
        help="optional real-provider measurement; off unless LIVE_MODE=1; not for CI",
    )
    live_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the [EST] cost and exit 2 above the cap; no request",
    )
    synth = sub.add_parser("synth-audio", help="write seeded DSP clips and sidecars")
    synth.add_argument("--seed", type=int, default=42)
    synth.add_argument("--calls", type=int, default=1)
    synth.add_argument("--out", default="")
    trace = sub.add_parser("trace", help="print the joined timeline for one turn")
    trace.add_argument("--turn", required=True)
    trace.add_argument("--log", required=True)
    trace.add_argument("--trace-file", default="")
    serve_parser = sub.add_parser("webhook-serve", help="serve the tool webhook on localhost")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    command = str(args.command)
    if command == "eval":
        return cmd_eval(settings, str(args.profile))
    if command == "eval-voice":
        return cmd_eval_voice(settings)
    if command == "eval-regression":
        if bool(args.turn_taking) and bool(args.webhook):
            parser.error("pass only one of --turn-taking and --webhook")
        if bool(args.turn_taking):
            return cmd_turn_regression()
        if bool(args.webhook):
            return cmd_webhook_regression(settings)
        return cmd_regression(settings)
    if command == "latency-report":
        return cmd_latency_report(settings)
    if command == "demo":
        return cmd_demo(settings)
    if command == "dlq-replay":
        return cmd_dlq_replay(settings, Path(str(args.dlq)), Path(str(args.db)))
    if command == "secretscan":
        return cmd_secretscan(Path(str(args.path)))
    if command == "live":
        if bool(args.dry_run):
            return cmd_live_dry_run()
        return cmd_live(settings)
    if command == "synth-audio":
        out = Path(str(args.out)) if str(args.out) else Path(settings.data_dir) / "synth"
        return cmd_synth_audio(settings, int(args.seed), int(args.calls), out)
    if command == "trace":
        trace_file = str(args.trace_file)
        return cmd_trace(
            str(args.turn),
            Path(str(args.log)),
            Path(trace_file) if trace_file else None,
        )
    if command == "webhook-serve":
        data = Path(settings.data_dir) / "serve"
        store = BookingStore(data / "clinic.sqlite")
        serve(WebhookApp(store, settings.hmac_secret), str(args.host), int(args.port))
        return 0
    parser.error(f"unknown command {command}")
    return 2
