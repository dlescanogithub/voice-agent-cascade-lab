"""Webhook fault cohort W01-W12. In-process only. No network.

Outcomes are invariants on the local store and the dead-letter file.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from voice_cascade.booking import BookingStore
from voice_cascade.clock import SimulatedClock
from voice_cascade.config import Settings
from voice_cascade.logging_setup import ListHandler, log_event
from voice_cascade.webhook import (
    SIMULATED_UNIX_S,
    FaultPlan,
    InProcessTransport,
    JsonlDeadLetterQueue,
    WebhookApp,
    WebhookClient,
    canonical_json,
    sign_v2,
)


@dataclass(frozen=True)
class FaultCase:
    case_id: str
    passed: bool
    detail: str
    attempts: int
    error_class: str


def _attempts(result: Mapping[str, object]) -> int:
    raw = result.get("attempts")
    if isinstance(raw, bool) or not isinstance(raw, int):
        return 0
    return raw


def _book(slot: str, patient: str, key: str, call_id: str) -> dict[str, object]:
    return {
        "tool": "book_appointment",
        "args": {"slot_id": slot, "patient_ref": patient},
        "idempotency_key": key,
        "call_id": call_id,
    }


def _client(
    tmp: Path,
    settings: Settings,
    *,
    secret: str | None = None,
    previous: str = "",
    accept_v1: bool | None = None,
    now_offset_s: int = 0,
    logger: logging.Logger | None = None,
) -> tuple[WebhookClient, BookingStore, WebhookApp]:
    db_path = tmp / "clinic.sqlite"
    if db_path.exists():
        db_path.unlink()
    store = BookingStore(db_path)
    app = WebhookApp(
        store,
        secret or settings.hmac_secret,
        previous_secret=previous,
        accept_v1=settings.accept_v1_signature if accept_v1 is None else accept_v1,
        tolerance_s=settings.signature_tolerance_s,
        now_s=lambda: SIMULATED_UNIX_S + now_offset_s,
        logger=logger,
    )
    dlq = JsonlDeadLetterQueue(tmp / "dlq.jsonl")
    dlq.replace_all([])
    client = WebhookClient(
        InProcessTransport(app),
        SimulatedClock(),
        dlq,
        settings,
        logger=logger,
        now_s=lambda: SIMULATED_UNIX_S,
    )
    return client, store, app


def run_fault_cohort(root: Path, settings: Settings | None = None) -> list[FaultCase]:
    chosen = settings or Settings(jitter_ms=0, tool_deadline_ms=1500, hmac_is_demo_default=False)
    logger = logging.getLogger("voice_cascade.faults")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = ListHandler()
    logger.addHandler(handler)
    cases = [
        _w01(root / "w01", chosen, logger),
        _w02(root / "w02", chosen, logger),
        _w03(root / "w03", chosen, logger),
        _w04(root / "w04", chosen, logger),
        _w05(root / "w05", chosen, logger),
        _w06(root / "w06", chosen, logger),
        _w07(root / "w07", chosen, logger),
        _w08(root / "w08", chosen, logger),
        _w09(root / "w09", chosen, logger),
        _w10(root / "w10", chosen, logger),
        _w11(root / "w11", chosen, logger),
        _w12(root / "w12", chosen, logger),
    ]
    for case in cases:
        log_event(
            logger,
            "fault.case",
            case.detail,
            {
                "call_id": case.case_id.lower(),
                "turn_id": f"{case.case_id.lower()}:t01",
                "span_id": f"{case.case_id.lower()}:t01:case",
                "provenance": "SIMULATED",
                "error_class": case.error_class,
                "passed": case.passed,
            },
        )
    (root / "fault.log").write_text("\n".join(handler.lines) + "\n", encoding="utf-8")
    return cases


def w06_shows_retries(root: Path, settings: Settings) -> FaultCase:
    """Regression helper: 4xx marked retryable. W06 must show retries."""

    return _w06(root, settings, logger=None)


def _w01(tmp: Path, settings: Settings, logger: logging.Logger) -> FaultCase:
    client, store, _app = _client(tmp, settings, logger=logger)
    store.ensure_slot("slot-w01", "2026-11-03", "general_consult")
    result = client.invoke(
        _book("slot-w01", "pat-w01", "key-w01", "w01"),
        FaultPlan("book_appointment", "timeout_before_commit", 9),
        turn_id="w01:t01",
    )
    letters = client.dlq.read_all()
    passed = (
        result.get("error") == "dead_lettered"
        and result.get("error_class") == "timeout"
        and result.get("attempts") == settings.max_attempts
        and store.active_counts() == {}
        and len(letters) == 1
        and letters[0].get("error_class") == "timeout"
    )
    store.close()
    return FaultCase(
        "W01",
        passed,
        "timeout before commit, no booking, one dead letter",
        _attempts(result),
        "timeout",
    )


def _w02(tmp: Path, settings: Settings, logger: logging.Logger) -> FaultCase:
    client, store, _app = _client(tmp, settings, logger=logger)
    store.ensure_slot("slot-w02", "2026-11-03", "general_consult")
    result = client.invoke(
        _book("slot-w02", "pat-w02", "key-w02", "w02"),
        FaultPlan("book_appointment", "slow_after_commit", 1),
        turn_id="w02:t01",
    )
    passed = (
        result.get("ok") is True
        and result.get("idempotent_replay") is True
        and store.active_counts() == {"slot-w02": 1}
        and result.get("attempts") == 2
    )
    store.close()
    return FaultCase(
        "W02",
        passed,
        "slow after commit replays the same booking",
        _attempts(result),
        "timeout",
    )


def _w03(tmp: Path, settings: Settings, logger: logging.Logger) -> FaultCase:
    client, store, _app = _client(tmp, settings, logger=logger)
    store.ensure_slot("slot-w03", "2026-11-03", "general_consult")
    result = client.invoke(
        _book("slot-w03", "pat-w03", "key-w03", "w03"),
        FaultPlan("book_appointment", "http_503", 2),
        turn_id="w03:t01",
    )
    passed = (
        result.get("ok") is True
        and result.get("attempts") == 3
        and store.active_counts() == {"slot-w03": 1}
    )
    store.close()
    return FaultCase("W03", passed, "two 503s then one booking", _attempts(result), "http_5xx")


def _w04(tmp: Path, settings: Settings, logger: logging.Logger) -> FaultCase:
    client, store, _app = _client(tmp, settings, logger=logger)
    store.ensure_slot("slot-w04", "2026-11-03", "general_consult")
    before = client.clock.now_ms
    result = client.invoke(
        _book("slot-w04", "pat-w04", "key-w04", "w04"),
        FaultPlan("book_appointment", "http_503", 1, retry_after_s=2),
        turn_id="w04:t01",
    )
    waited = client.clock.now_ms - before
    passed = (
        result.get("ok") is True
        and _attempts(result) <= settings.max_attempts
        and waited <= settings.tool_deadline_ms + settings.timeout_ms + settings.backoff_cap_ms
    )
    # The 2s Retry-After must have been capped. A 2000 ms wait would push the
    # clock well past cap + two short attempts.
    capped = waited < 2000
    store.close()
    return FaultCase(
        "W04",
        passed and capped,
        "Retry-After 2s capped at backoff_cap_ms",
        _attempts(result),
        "throttled",
    )


def _w05(tmp: Path, settings: Settings, logger: logging.Logger) -> FaultCase:
    client, store, _app = _client(tmp, settings, logger=logger)
    store.ensure_slot("slot-w05", "2026-11-03", "general_consult")
    result = client.invoke(
        _book("slot-w05", "pat-w05", "key-w05", "w05"),
        FaultPlan("book_appointment", "http_500", 9),
        turn_id="w05:t01",
    )
    bound = settings.tool_deadline_ms + settings.timeout_ms
    # Deadline is 1500 ms and the simulated 500s use the short in-process charge,
    # so the run finishes inside the bound. The bound is still checked.
    passed = (
        result.get("error") == "dead_lettered"
        and result.get("error_class") == "http_5xx"
        and result.get("attempts") == settings.max_attempts
        and client.clock.now_ms <= bound
        and store.active_counts() == {}
    )
    store.close()
    return FaultCase(
        "W05",
        passed,
        "persistent 500 dead-letters inside the tool bound",
        _attempts(result),
        "http_5xx",
    )


def _w06(tmp: Path, settings: Settings, logger: logging.Logger | None) -> FaultCase:
    client, store, app = _client(tmp, settings, logger=logger)
    store.ensure_slot("slot-w06", "2026-11-03", "general_consult")
    before = app.store_accesses
    result = client.invoke(
        _book("slot-w06", "pat-w06", "key-w06", "w06"),
        turn_id="w06:t01",
        body_override=b'{"tool":',
    )
    letters = client.dlq.read_all()
    attempts = _attempts(result)
    passed = bool(
        result.get("error_class") == "poison_payload"
        and attempts == 1
        and app.store_accesses == before
        and letters
        and letters[0].get("error_class") == "poison_payload"
        and store.active_counts() == {}
    )
    if settings.retry_nonretryable:
        passed = bool(attempts > 1 and result.get("error_class") == "poison_payload")
    store.close()
    return FaultCase(
        "W06", passed, "truncated JSON is poison and is not retried", attempts, "poison_payload"
    )


def _w07(tmp: Path, settings: Settings, logger: logging.Logger) -> FaultCase:
    client, store, app = _client(tmp, settings, logger=logger)
    envelope: dict[str, object] = {
        "tool": "book_appointment",
        "args": {"slot_id": ["nope"], "patient_ref": "pat-w07"},
        "idempotency_key": "key-w07",
        "call_id": "w07",
    }
    before = app.store_accesses
    result = client.invoke(envelope, turn_id="w07:t01")
    passed = (
        result.get("error_class") == "poison_payload"
        and result.get("attempts") == 1
        and app.store_accesses == before
        and result.get("status") == 400
    )
    store.close()
    return FaultCase(
        "W07",
        passed,
        "slot_id list is bad_args and is not retried",
        _attempts(result),
        "bad_args",
    )


def _w08(tmp: Path, settings: Settings, logger: logging.Logger) -> FaultCase:
    client, store, app = _client(tmp, settings, logger=logger)
    envelope: dict[str, object] = {
        "tool": "book_appointment",
        "args": {"slot_id": "slot-w08", "patient_ref": "pat-w08"},
        "call_id": "w08",
    }
    before = app.store_accesses
    result = client.invoke(envelope, turn_id="w08:t01")
    passed = (
        result.get("attempts") == 1 and app.store_accesses == before and result.get("status") == 400
    )
    store.close()
    return FaultCase(
        "W08",
        passed,
        "missing idempotency key is not retried",
        _attempts(result),
        "missing_idempotency_key",
    )


def _w09(tmp: Path, settings: Settings, logger: logging.Logger) -> FaultCase:
    client, store, _app = _client(tmp, settings, logger=logger)
    envelope = _book("slot-w09", "pat-w09", "key-w09", "w09")
    signed = canonical_json(envelope)
    tampered = json.dumps(
        {key: envelope[key] for key in reversed(list(envelope))},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    result = client.invoke(
        envelope,
        turn_id="w09:t01",
        body_override=tampered,
        signature_body=signed,
    )
    letters = client.dlq.read_all()
    passed = bool(
        result.get("attempts") == 1
        and result.get("error_class") == "auth_failed"
        and result.get("alert") is True
        and letters
        and letters[0].get("alert") is True
        and tampered != signed
    )
    store.close()
    return FaultCase(
        "W09", passed, "reordered JSON fails the signature and alerts", 1, "bad_signature"
    )


def _w10(tmp: Path, settings: Settings, logger: logging.Logger) -> FaultCase:
    wrong = "rotation-lab-previous"
    client, store, _app = _client(tmp, settings, logger=logger)
    store.ensure_slot("slot-w10", "2026-11-03", "general_consult")
    denied = client.invoke(
        _book("slot-w10", "pat-w10", "key-w10", "w10"),
        turn_id="w10:t01",
        signing_secret=wrong,
    )
    store.close()
    client_ok, store_ok, _app_ok = _client(tmp / "rotated", settings, previous=wrong, logger=logger)
    store_ok.ensure_slot("slot-w10", "2026-11-03", "general_consult")
    allowed = client_ok.invoke(
        _book("slot-w10", "pat-w10", "key-w10b", "w10"),
        turn_id="w10:t01",
        signing_secret=wrong,
    )
    passed = (
        denied.get("error_class") == "auth_failed"
        and denied.get("alert") is True
        and allowed.get("ok") is True
    )
    store_ok.close()
    return FaultCase(
        "W10",
        passed,
        "previous secret accepts a one-sided rotation",
        _attempts(denied),
        "auth_failed",
    )


def _w11(tmp: Path, settings: Settings, logger: logging.Logger) -> FaultCase:
    client, store, _app = _client(tmp, settings, logger=logger, now_offset_s=0)
    # Verifier clock is the simulated epoch. A capture from 10 minutes earlier is stale.
    result = client.invoke(
        _book("slot-w11", "pat-w11", "key-w11", "w11"),
        turn_id="w11:t01",
        timestamp_s=SIMULATED_UNIX_S - 600,
    )
    passed = (
        result.get("attempts") == 1
        and result.get("status") == 401
        and result.get("error_class") == "auth_failed"
    )
    letters = client.dlq.read_all()
    stale = bool(letters) and letters[0].get("error") == "stale_timestamp"
    store.close()
    return FaultCase(
        "W11", passed and stale, "capture older than 300s is stale_timestamp", 1, "stale_timestamp"
    )


def _w12(tmp: Path, settings: Settings, logger: logging.Logger) -> FaultCase:
    client, store, _app = _client(tmp, settings, logger=logger)
    store.ensure_slot("slot-w12", "2026-11-03", "general_consult")
    envelope = _book("slot-w12", "pat-w12", "key-w12", "w12")
    first = client.invoke(envelope, turn_id="w12:t01")
    second = client.invoke(envelope, turn_id="w12:t01")
    passed = (
        first.get("ok") is True
        and second.get("idempotent_replay") is True
        and second.get("booking_id") == first.get("booking_id")
        and store.active_counts() == {"slot-w12": 1}
    )
    store.close()
    return FaultCase(
        "W12",
        passed,
        "duplicate delivery returns the stored booking",
        _attempts(second),
        "ok",
    )


def trace_example(root: Path, settings: Settings) -> str:
    """Joined timeline for W01, safe to paste into docs. No secrets."""

    case_dir = root / "trace-w01"
    logger = logging.getLogger("voice_cascade.trace_example")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = ListHandler()
    logger.addHandler(handler)
    case = _w01(case_dir, settings, logger)
    log_path = case_dir / "tool.log"
    log_path.write_text("\n".join(handler.lines) + "\n", encoding="utf-8")
    from voice_cascade.trace_join import format_turn

    text = format_turn("w01:t01", log_path)
    header = (
        f"SIMULATED trace for {case.case_id} ({case.detail}). "
        "Provenance: SIMULATED. No provider was called.\n"
    )
    return header + text


def sign_roundtrip_header(secret: str, body: bytes) -> str:
    return sign_v2(secret, body, SIMULATED_UNIX_S)
