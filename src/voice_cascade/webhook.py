"""Local tool webhook: HMAC, idempotency, bounded retries, JSONL dead letters."""

from __future__ import annotations

import hashlib
import hmac
import json
import random
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from voice_cascade.booking import BookingStore
from voice_cascade.budget import TOOL_REPLAY_MS, TOOL_SUCCESS_MS
from voice_cascade.clock import SimulatedClock
from voice_cascade.config import Settings

SERVICE = "consulta_general"
ElapsedFor = Callable[[dict[str, object]], int]


def canonical_json(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode(
        "utf-8"
    )


def sign(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def delay_for(attempt_index: int, *, seed: int, key: str, base: int, cap: int, jitter: int) -> int:
    extra = 0
    if jitter > 0:
        extra = random.Random(f"{seed}:{key}:{attempt_index}").randrange(0, jitter + 1)
    # Shift, not **, because typeshed types int power as Any.
    scaled = base * (1 << attempt_index)
    return min(cap, scaled + extra)


@dataclass
class FaultPlan:
    tool: str
    mode: str
    times: int
    used: int = 0

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
    def __init__(self, store: BookingStore, secret: str) -> None:
        if not secret:
            raise ValueError("HMAC secret is empty")
        self.store = store
        self.secret = secret

    def handle(self, body: bytes, headers: Mapping[str, str]) -> tuple[int, dict[str, object]]:
        provided = ""
        for key, value in headers.items():
            if key.lower() == "x-voice-signature":
                provided = value
                break
        expected = sign(self.secret, body)
        if not provided or not hmac.compare_digest(provided, expected):
            return 401, {"ok": False, "error": "bad_signature"}
        try:
            parsed: object = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError:
            return 400, {"ok": False, "error": "bad_json"}
        if not isinstance(parsed, dict):
            return 400, {"ok": False, "error": "bad_json"}
        payload = {str(key): value for key, value in parsed.items()}
        tool = str(payload.get("tool", ""))
        args = payload.get("args", {})
        if not isinstance(args, dict):
            return 400, {"ok": False, "error": "bad_args"}
        arguments = {str(key): value for key, value in args.items()}
        key = str(payload.get("idempotency_key", ""))
        if tool == "find_slots":
            slots = self.store.find_slots(
                str(arguments.get("date", "")), str(arguments.get("service", SERVICE))
            )
            return 200, {"ok": True, "slots": slots}
        if tool == "book_appointment":
            result = self.store.book(
                str(arguments.get("slot_id", "")), str(arguments.get("patient_ref", "")), key
            )
            return 200, result
        if tool == "cancel_appointment":
            result = self.store.cancel(str(arguments.get("booking_id", "")), key)
            return 200, result
        return 400, {"ok": False, "error": "unknown_tool"}


class InProcessTransport:
    def __init__(self, app: WebhookApp) -> None:
        self.app = app

    def deliver(
        self, body: bytes, signature: str, timeout_ms: int
    ) -> tuple[int, dict[str, object], int]:
        del timeout_ms
        status, payload = self.app.handle(body, {"X-Voice-Signature": signature})
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
    ) -> None:
        self.transport = transport
        self.clock = clock
        self.dlq = dlq
        self.settings = settings
        self.elapsed_for = elapsed_for

    def invoke(
        self, envelope: dict[str, object], fault: FaultPlan | None = None
    ) -> dict[str, object]:
        body = canonical_json(envelope)
        signature = sign(self.settings.hmac_secret, body)
        key = str(envelope.get("idempotency_key", ""))
        tool = str(envelope.get("tool", ""))
        attempts = 0
        last_error = "unknown"
        while attempts < self.settings.max_attempts:
            attempts += 1
            mode = fault.next_mode() if fault and fault.tool == tool else None
            status = 0
            payload: dict[str, object] = {}
            try:
                if mode == "timeout_before_commit":
                    raise TimeoutError
                if mode == "http_500":
                    self.clock.advance(TOOL_SUCCESS_MS)
                    last_error = "http_500"
                    self._backoff(attempts, key)
                    continue
                status, payload, elapsed = self.transport.deliver(
                    body, signature, self.settings.timeout_ms
                )
                if self.elapsed_for is not None and status == 200:
                    elapsed = self.elapsed_for(payload)
                if mode == "slow_after_commit":
                    self.clock.advance(self.settings.timeout_ms)
                    last_error = "timeout"
                    self._backoff(attempts, key)
                    continue
                self.clock.advance(elapsed)
            except TimeoutError:
                self.clock.advance(self.settings.timeout_ms)
                last_error = "timeout"
                self._backoff(attempts, key)
                continue
            if status >= 500:
                last_error = f"http_{status}"
                self._backoff(attempts, key)
                continue
            if status != 200:
                return {
                    "ok": False,
                    "error": "rejected",
                    "attempts": attempts,
                    "tool": tool,
                    "status": status,
                }
            payload["attempts"] = attempts
            payload["tool"] = tool
            return payload
        record: dict[str, object] = {
            "envelope": envelope,
            "error": last_error,
            "attempts": attempts,
            "call_id": envelope.get("call_id", ""),
        }
        self.dlq.append(record)
        return {"ok": False, "error": "dead_lettered", "attempts": attempts, "tool": tool}

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


def replay_dead_letters(
    dlq: JsonlDeadLetterQueue,
    client: WebhookClient,
) -> tuple[int, int]:
    remaining: list[dict[str, object]] = []
    recovered = 0
    for record in dlq.read_all():
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
