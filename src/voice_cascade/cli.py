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
from voice_cascade.evalkit import EvalReport, evaluate
from voice_cascade.live import LiveConfigError, LiveRequestError, run_live
from voice_cascade.logging_setup import configure_logging
from voice_cascade.pipeline import SuiteResult, run_suite
from voice_cascade.scenarios import build_scenarios
from voice_cascade.secretscan import scan_path
from voice_cascade.vad import PROFILES
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


def cmd_eval(settings: Settings, profile: str) -> int:
    result, report = _run(settings, profile, "eval", regression=False)
    _print_report(report, result)
    _write_report(Path("reports") / "eval.json", report, result)
    return 0 if report.passed else 1


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
    print(
        f"{payload.get('title', 'live')} "
        f"turns={count} estimated_usd={payload.get('estimated_usd')} "
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
    sub.add_parser("eval-regression", help="must fail: clinical guard off and a bad cassette")
    sub.add_parser(
        "latency-report", help="print simulated latency and barge-in rates for 3 profiles"
    )
    sub.add_parser("demo", help="run three scripted calls on the simulated clock")
    replay = sub.add_parser("dlq-replay", help="replay a JSONL dead-letter queue")
    replay.add_argument("--dlq", required=True)
    replay.add_argument("--db", required=True)
    scan = sub.add_parser("secretscan", help="scan a tree for committed secrets")
    scan.add_argument("path", nargs="?", default=".")
    sub.add_parser(
        "live",
        help="optional real-provider measurement; off unless LIVE_MODE=1; not for CI",
    )
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
    if command == "eval-regression":
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
        return cmd_live(settings)
    if command == "webhook-serve":
        data = Path(settings.data_dir) / "serve"
        store = BookingStore(data / "clinic.sqlite")
        serve(WebhookApp(store, settings.hmac_secret), str(args.host), int(args.port))
        return 0
    parser.error(f"unknown command {command}")
    return 2
