"""Local tool webhook: HMAC, idempotency, bounded retries, JSONL dead letters.

Signature v2 adds a signed timestamp. v1 (`sha256=<hex>` over the raw body)
stays accepted while ``accept_v1`` is on. That default is open decision D5,
not a final choice. Retries use full jitter when jitter is enabled.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import random
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from voice_cascade.booking import BookingStore
from voice_cascade.budget import TOOL_REPLAY_MS, TOOL_SUCCESS_MS
from voice_cascade.clock import SimulatedClock
from voice_cascade.config import Settings
from voice_cascade.logging_setup import log_event

SERVICE = "consulta_general"
SIMULATED_UNIX_S = 1_700_000_000
SIGNATURE_TOLERANCE_S = 300
KEY_RE = re.compile(r"^[A-Za-z0-9:._-]{1,200}$")
POISON_ERRORS = frozenset({"bad_json", "bad_args", "missing_idempotency_key"})
RETRY_5XX = frozenset({500, 502, 503, 504})
ElapsedFor = Callable[[dict[str, object]], int]


def simulated_unix_s() -> int:
    """Fixed unix time for the offline lab. Not the wall clock."""

    return SIMULATED_UNIX_S


def canonical_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode(
        "utf-8"
    )


def sign(secret: str, body: bytes) -> str:
    """v1 signature. Deprecated while D5 is open. Still accepted by default."""

    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def sign_v2(secret: str, body: bytes, timestamp_s: int) -> str:
    """v2 signature over ``b"{timestamp}.{body}"``."""

    material = f"{timestamp_s}.".encode() + body
    digest = hmac.new(secret.encode("utf-8"), material, hashlib.sha256).hexdigest()
    return f"t={timestamp_s},v1={digest}"


def parse_v2(header: str) -> tuple[int, str] | None:
    if "t=" not in header or "v1=" not in header:
        return None
    parts: dict[str, str] = {}
    for piece in header.split(","):
        if "=" not in piece:
            return None
        key, value = piece.split("=", 1)
        parts[key.strip()] = value.strip()
    timestamp = parts.get("t", "")
    mac = parts.get("v1", "")
    if not timestamp.isdigit() or not mac:
        return None
    return int(timestamp), mac


def secret_id(secret: str) -> str:
    """Short id for logs. Not the secret and not reversible on its own."""

    if not secret:
        return "secret:none"
    digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()[:8]
    return f"secret:{digest}"


def idempotency_key_hash(key: str) -> str:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]
    return f"sha256:{digest}"


def _eq(left: str, right: str) -> bool:
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def classify_http(status: int, payload: Mapping[str, object]) -> tuple[str, bool]:
    """Return ``(error_class, retryable)`` for one HTTP result."""

    error = str(payload.get("error", ""))
    retry_after = payload.get("retry_after_s")
    has_retry_after = isinstance(retry_after, int) and not isinstance(retry_after, bool)
    if status == 429 or (status == 503 and has_retry_after):
        return "throttled", True
    if status in RETRY_5XX:
        return "http_5xx", True
    if status == 400:
        if error in POISON_ERRORS or error == "":
            return "poison_payload", False
        return "poison_payload", False
    if status == 401:
        return "auth_failed", False
    if status == 409 or error == "slot_unavailable":
        return "slot_unavailable", False
    if status == 200:
        return "ok", False
    return "rejected", False


def delay_for(attempt_index: int, *, seed: int, key: str, base: int, cap: int, jitter: int) -> int:
    """Backoff for one retry.

    ``jitter <= 0`` keeps the old deterministic exponential delay so existing
    zero-jitter tests stay stable. ``jitter > 0`` is full jitter:
    ``rand(0, min(cap, base·2^n))``, seeded per key and attempt.
    """

    scaled = base * (1 << attempt_index)
    bound = min(cap, scaled)
    if jitter <= 0 or bound <= 0:
        return bound
    return random.Random(f"{seed}:{key}:{attempt_index}:full").randrange(0, bound + 1)


@dataclass
class FaultPlan:
    tool: str
    mode: str
    times: int
    used: int = 0
    retry_after_s: int = 0

    def next_mode(self) -> str | None:
        if self.used >= self.times:
            return None
        self.used += 1
        return self.mode


class JsonlDeadLetterQueue:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("", encoding="utf-8")

    def append(self, record: dict[str, object]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def read_all(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            parsed: object = json.loads(line)
            if isinstance(parsed, dict):
                rows.append({str(key): value for key, value in parsed.items()})
        return rows

    def replace_all(self, records: list[dict[str, object]]) -> None:
        body = "".join(
            json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
        )
        self.path.write_text(body, encoding="utf-8")


class ResponseBuffer:
    """Hold responses and release them last-in first-out (out-of-order delivery)."""

    def __init__(self) -> None:
        self._items: list[tuple[int, dict[str, object]]] = []

    def push(self, item: tuple[int, dict[str, object]]) -> None:
        self._items.append(item)

    def release_lifo(self) -> list[tuple[int, dict[str, object]]]:
        released = list(reversed(self._items))
        self._items.clear()
        return released


class WebhookApp:
    def __init__(
        self,
        store: BookingStore,
        secret: str,
        *,
        previous_secret: str = "",
        accept_v1: bool = True,
        tolerance_s: int = SIGNATURE_TOLERANCE_S,
        now_s: Callable[[], int] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if not secret:
            raise ValueError("HMAC secret is empty")
        self.store = store
        self.secret = secret
        self.previous_secret = previous_secret
        self.accept_v1 = accept_v1
        self.tolerance_s = tolerance_s
        self.now_s = now_s or simulated_unix_s
        self.logger = logger
        self.store_accesses = 0

    def handle(self, body: bytes, headers: Mapping[str, str]) -> tuple[int, dict[str, object]]:
        provided = ""
        correlation = ""
        request_id = ""
        for key, value in headers.items():
            lowered = key.lower()
            if lowered == "x-voice-signature":
                provided = value
            elif lowered == "x-correlation-id":
                correlation = value
            elif lowered == "x-request-id":
                request_id = value
        ok, reason = self._verify(body, provided)
        if not ok:
            payload = {"ok": False, "error": reason}
            if reason in {"bad_signature", "stale_timestamp"}:
                payload["alert"] = True
            self._log_request(correlation, request_id, reason, alert=reason != "")
            return 401, payload
        try:
            parsed: object = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return 400, {"ok": False, "error": "bad_json"}
        if not isinstance(parsed, dict):
            return 400, {"ok": False, "error": "bad_json"}
        payload_in = {str(key): value for key, value in parsed.items()}
        invalid = _validate_payload(payload_in)
        if invalid is not None:
            return invalid
        tool = str(payload_in.get("tool", ""))
        args = payload_in.get("args", {})
        arguments = (
            {str(key): value for key, value in args.items()} if isinstance(args, dict) else {}
        )
        key = str(payload_in.get("idempotency_key", ""))
        self._log_request(correlation, request_id, "accepted", alert=False)
        if tool == "find_slots":
            self.store_accesses += 1
            slots = self.store.find_slots(
                str(arguments.get("date", "")), str(arguments.get("service", SERVICE))
            )
            return 200, {"ok": True, "slots": slots}
        if tool == "book_appointment":
            self.store_accesses += 1
            result = self.store.book(
                str(arguments.get("slot_id", "")), str(arguments.get("patient_ref", "")), key
            )
            return 200, result
        if tool == "cancel_appointment":
            self.store_accesses += 1
            result = self.store.cancel(str(arguments.get("booking_id", "")), key)
            return 200, result
        return 400, {"ok": False, "error": "unknown_tool"}

    def _verify(self, body: bytes, header: str) -> tuple[bool, str]:
        if not header:
            return False, "bad_signature"
        parsed = parse_v2(header)
        if parsed is not None:
            timestamp_s, mac = parsed
            if abs(self.now_s() - timestamp_s) > self.tolerance_s:
                return False, "stale_timestamp"
            if self._mac_matches(body, timestamp_s, mac):
                return True, ""
            return False, "bad_signature"
        if self.accept_v1 and header.startswith("sha256="):
            if _eq(header, sign(self.secret, body)):
                return True, ""
            if self.previous_secret and _eq(header, sign(self.previous_secret, body)):
                return True, ""
            return False, "bad_signature"
        return False, "bad_signature"

    def _mac_matches(self, body: bytes, timestamp_s: int, mac: str) -> bool:
        current = sign_v2(self.secret, body, timestamp_s).split("v1=", 1)[1]
        if _eq(mac, current):
            return True
        if not self.previous_secret:
            return False
        previous = sign_v2(self.previous_secret, body, timestamp_s).split("v1=", 1)[1]
        return _eq(mac, previous)

    def _log_request(self, correlation: str, request_id: str, outcome: str, *, alert: bool) -> None:
        if self.logger is None or not correlation:
            return
        log_event(
            self.logger,
            "tool.auth.alert" if alert and outcome != "accepted" else "tool.request",
            "webhook request",
            {
                "call_id": correlation.split(":", 1)[0],
                "turn_id": correlation,
                "span_id": request_id,
                "provenance": "SIMULATED",
                "outcome": outcome,
                "secret_id": secret_id(self.secret),
                "previous_secret_id": secret_id(self.previous_secret),
            },
            level=logging.WARNING if alert and outcome != "accepted" else logging.INFO,
        )


def _validate_payload(payload: Mapping[str, object]) -> tuple[int, dict[str, object]] | None:
    key = payload.get("idempotency_key")
    if not isinstance(key, str) or key == "":
        return 400, {"ok": False, "error": "missing_idempotency_key"}
    if KEY_RE.fullmatch(key) is None:
        return 400, {"ok": False, "error": "bad_args"}
    args = payload.get("args", {})
    if not isinstance(args, dict):
        return 400, {"ok": False, "error": "bad_args"}
    for name in ("slot_id", "patient_ref", "booking_id", "date", "service"):
        if name in args and not isinstance(args[name], str):
            return 400, {"ok": False, "error": "bad_args"}
    return None


class InProcessTransport:
    def __init__(self, app: WebhookApp) -> None:
        self.app = app
        self.extra_headers: dict[str, str] = {}

    def deliver(
        self, body: bytes, signature: str, timeout_ms: int
    ) -> tuple[int, dict[str, object], int]:
        del timeout_ms
        headers = {"X-Voice-Signature": signature, **self.extra_headers}
        status, payload = self.app.handle(body, headers)
        elapsed = TOOL_REPLAY_MS if payload.get("idempotent_replay") is True else TOOL_SUCCESS_MS
        return status, payload, elapsed


class WebhookClient:
    def __init__(
        self,
        transport: InProcessTransport,
        clock: SimulatedClock,
        dlq: JsonlDeadLetterQueue,
        settings: Settings,
        elapsed_for: ElapsedFor | None = None,
        logger: logging.Logger | None = None,
        now_s: Callable[[], int] | None = None,
    ) -> None:
        self.transport = transport
        self.clock = clock
        self.dlq = dlq
        self.settings = settings
        self.elapsed_for = elapsed_for
        self.logger = logger
        self.now_s = now_s or simulated_unix_s
        self.attempt_log: list[dict[str, object]] = []

    def invoke(
        self,
        envelope: dict[str, object],
        fault: FaultPlan | None = None,
        *,
        turn_id: str = "",
        timestamp_s: int | None = None,
        signing_secret: str | None = None,
        body_override: bytes | None = None,
        signature_body: bytes | None = None,
    ) -> dict[str, object]:
        call_id = str(envelope.get("call_id", ""))
        turn = turn_id or (f"{call_id}:t01" if call_id else "call:t01")
        signed_at = self.now_s() if timestamp_s is None else timestamp_s
        secret = self.settings.hmac_secret if signing_secret is None else signing_secret
        body = canonical_json(envelope) if body_override is None else body_override
        signed_body = body if signature_body is None else signature_body
        signature = sign_v2(secret, signed_body, signed_at)
        key = str(envelope.get("idempotency_key", ""))
        tool = str(envelope.get("tool", ""))
        started = self.clock.now_ms
        attempts = 0
        last_error = "unknown"
        error_class = "unknown"
        first_status: int | None = None
        last_status = 0
        alert = False
        deadline = self.settings.tool_deadline_ms
        while attempts < self.settings.max_attempts:
            if deadline > 0 and (self.clock.now_ms - started) >= deadline:
                last_error = "deadline"
                error_class = "deadline"
                break
            attempts += 1
            span = f"{turn}:tool:a{attempts}"
            self._set_headers(turn, span)
            mode = fault.next_mode() if fault and fault.tool == tool else None
            status = 0
            payload: dict[str, object] = {}
            try:
                if mode == "timeout_before_commit":
                    raise TimeoutError
                if mode in {"http_500", "http_503"}:
                    self.clock.advance(TOOL_SUCCESS_MS)
                    status = 503 if mode == "http_503" else 500
                    payload = {"ok": False, "error": mode}
                    if mode == "http_503" and fault is not None and fault.retry_after_s > 0:
                        payload["retry_after_s"] = fault.retry_after_s
                        error_class = "throttled"
                    else:
                        error_class = "http_5xx"
                    last_error = "http_500" if mode == "http_500" else "http_503"
                    last_status = status
                    if first_status is None:
                        first_status = status
                    self._remember(
                        call_id=call_id,
                        turn_id=turn,
                        span_id=span,
                        tool=tool,
                        attempt=attempts,
                        status=status,
                        error_class=error_class,
                        retryable=True,
                        key=key,
                        started=started,
                    )
                    self._wait_retry(attempts, key, payload)
                    continue
                status, payload, elapsed = self.transport.deliver(
                    body, signature, self.settings.timeout_ms
                )
                if self.elapsed_for is not None and status == 200:
                    elapsed = self.elapsed_for(payload)
                if mode == "slow_after_commit":
                    self.clock.advance(self.settings.timeout_ms)
                    last_error = "timeout"
                    error_class = "timeout"
                    last_status = 0
                    if first_status is None:
                        first_status = 0
                    self._remember(
                        call_id=call_id,
                        turn_id=turn,
                        span_id=span,
                        tool=tool,
                        attempt=attempts,
                        status=0,
                        error_class="timeout",
                        retryable=True,
                        key=key,
                        started=started,
                    )
                    self._backoff(attempts, key)
                    continue
                self.clock.advance(elapsed)
            except TimeoutError:
                self.clock.advance(self.settings.timeout_ms)
                last_error = "timeout"
                error_class = "timeout"
                last_status = 0
                if first_status is None:
                    first_status = 0
                self._remember(
                    call_id=call_id,
                    turn_id=turn,
                    span_id=span,
                    tool=tool,
                    attempt=attempts,
                    status=0,
                    error_class="timeout",
                    retryable=True,
                    key=key,
                    started=started,
                )
                self._backoff(attempts, key)
                continue
            if first_status is None:
                first_status = status
            last_status = status
            error_class, retryable = classify_http(status, payload)
            if self.settings.retry_nonretryable and error_class == "poison_payload":
                retryable = True
            if retryable:
                last_error = f"http_{status}" if error_class == "http_5xx" else error_class
                self._remember(
                    call_id=call_id,
                    turn_id=turn,
                    span_id=span,
                    tool=tool,
                    attempt=attempts,
                    status=status,
                    error_class=error_class,
                    retryable=True,
                    key=key,
                    started=started,
                )
                self._wait_retry(attempts, key, payload)
                continue
            if status == 200 or status == 409 or error_class == "slot_unavailable":
                payload["attempts"] = attempts
                payload["tool"] = tool
                self._remember(
                    call_id=call_id,
                    turn_id=turn,
                    span_id=span,
                    tool=tool,
                    attempt=attempts,
                    status=status,
                    error_class=error_class,
                    retryable=False,
                    key=key,
                    started=started,
                )
                return payload
            if error_class in {"poison_payload", "auth_failed"}:
                alert = error_class == "auth_failed" or payload.get("alert") is True
                self._dead_letter(
                    envelope=envelope,
                    error=str(payload.get("error", error_class)),
                    error_class=error_class,
                    attempts=attempts,
                    call_id=call_id,
                    turn_id=turn,
                    span_id=span,
                    first_status=first_status,
                    last_status=last_status,
                    alert=alert,
                    replayable=False,
                )
                return {
                    "ok": False,
                    "error": "dead_lettered",
                    "error_class": error_class,
                    "attempts": attempts,
                    "tool": tool,
                    "status": status,
                    "alert": alert,
                }
            return {
                "ok": False,
                "error": "rejected",
                "attempts": attempts,
                "tool": tool,
                "status": status,
                "error_class": error_class,
            }
        self._dead_letter(
            envelope=envelope,
            error=last_error,
            error_class=error_class,
            attempts=attempts,
            call_id=call_id,
            turn_id=turn,
            span_id=f"{turn}:tool:a{attempts}",
            first_status=first_status,
            last_status=last_status,
            alert=alert,
            replayable=error_class not in {"poison_payload", "auth_failed"},
        )
        return {
            "ok": False,
            "error": "dead_lettered",
            "error_class": error_class,
            "attempts": attempts,
            "tool": tool,
            "alert": alert,
        }

    def _set_headers(self, turn_id: str, span_id: str) -> None:
        extra = getattr(self.transport, "extra_headers", None)
        if isinstance(extra, dict):
            extra.clear()
            extra["X-Correlation-Id"] = turn_id
            extra["X-Request-Id"] = span_id

    def _deadline_left(self, started: int) -> int | None:
        if self.settings.tool_deadline_ms <= 0:
            return None
        return self.settings.tool_deadline_ms - (self.clock.now_ms - started)

    def _remember(
        self,
        *,
        call_id: str,
        turn_id: str,
        span_id: str,
        tool: str,
        attempt: int,
        status: int,
        error_class: str,
        retryable: bool,
        key: str,
        started: int,
    ) -> None:
        retry_in = 0
        if retryable and attempt < self.settings.max_attempts:
            retry_in = delay_for(
                attempt - 1,
                seed=self.settings.seed,
                key=key,
                base=self.settings.backoff_base_ms,
                cap=self.settings.backoff_cap_ms,
                jitter=self.settings.jitter_ms,
            )
        left = self._deadline_left(started)
        row: dict[str, object] = {
            "ts": "SIMULATED",
            "event": "tool.attempt.failed"
            if retryable or error_class not in {"ok", "slot_unavailable"}
            else "tool.attempt.ok",
            "provenance": "SIMULATED",
            "call_id": call_id,
            "turn_id": turn_id,
            "span_id": span_id,
            "tool": tool,
            "attempt": attempt,
            "max_attempts": self.settings.max_attempts,
            "idempotency_key_hash": idempotency_key_hash(key),
            "http_status": status,
            "error_class": error_class,
            "retryable": retryable,
            "retry_in_ms": retry_in,
            "elapsed_ms": self.clock.now_ms - started,
            "deadline_left_ms": left if left is not None else "",
            "secret_id": secret_id(self.settings.hmac_secret),
        }
        self.attempt_log.append(row)
        if self.logger is not None:
            level = logging.WARNING if retryable or error_class == "auth_failed" else logging.INFO
            event = "tool.auth.alert" if error_class == "auth_failed" else str(row["event"])
            log_event(self.logger, event, "tool attempt", row, level=level)

    def _wait_retry(self, attempts: int, key: str, payload: Mapping[str, object]) -> None:
        if attempts >= self.settings.max_attempts:
            return
        retry_after = payload.get("retry_after_s")
        if isinstance(retry_after, int) and not isinstance(retry_after, bool):
            self.clock.advance(min(retry_after * 1000, self.settings.backoff_cap_ms))
            return
        self._backoff(attempts, key)

    def _backoff(self, attempts: int, key: str) -> None:
        if attempts >= self.settings.max_attempts:
            return
        delay = delay_for(
            attempts - 1,
            seed=self.settings.seed,
            key=key,
            base=self.settings.backoff_base_ms,
            cap=self.settings.backoff_cap_ms,
            jitter=self.settings.jitter_ms,
        )
        self.clock.advance(delay)

    def _dead_letter(
        self,
        *,
        envelope: dict[str, object],
        error: str,
        error_class: str,
        attempts: int,
        call_id: str,
        turn_id: str,
        span_id: str,
        first_status: int | None,
        last_status: int,
        alert: bool,
        replayable: bool,
    ) -> None:
        record: dict[str, object] = {
            "envelope": envelope,
            "error": error,
            "error_class": error_class,
            "attempts": attempts,
            "call_id": call_id,
            "turn_id": turn_id,
            "span_id": span_id,
            "first_status": first_status if first_status is not None else "",
            "last_status": last_status,
            "alert": alert,
            "replayable": replayable,
            "provenance": "SIMULATED",
        }
        self.dlq.append(record)


def replay_dead_letters(
    dlq: JsonlDeadLetterQueue,
    client: WebhookClient,
) -> tuple[int, int]:
    remaining: list[dict[str, object]] = []
    recovered = 0
    for record in dlq.read_all():
        if record.get("replayable") is False:
            remaining.append(record)
            continue
        envelope = record.get("envelope")
        if not isinstance(envelope, dict):
            remaining.append(record)
            continue
        result = client.invoke({str(key): value for key, value in envelope.items()})
        if result.get("ok") is True:
            recovered += 1
        else:
            remaining.append(record)
    dlq.replace_all(remaining)
    return recovered, len(remaining)


def build_http_server(app: WebhookApp, host: str, port: int) -> ThreadingHTTPServer:
    application = app

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            headers = {key: value for key, value in self.headers.items()}
            status, payload = application.handle(body, headers)
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt: str, *args: object) -> None:
            del fmt, args

    return ThreadingHTTPServer((host, port), Handler)


def serve(app: WebhookApp, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = build_http_server(app, host, port)
    try:
        server.serve_forever()
    finally:
        server.server_close()
