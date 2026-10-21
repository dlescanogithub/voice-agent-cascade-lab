from __future__ import annotations

import json
from pathlib import Path

from voice_cascade.booking import BookingStore
from voice_cascade.budget import TOOL_REPLAY_MS, TOOL_SUCCESS_MS
from voice_cascade.clock import SimulatedClock
from voice_cascade.config import Settings
from voice_cascade.webhook import (
    FaultPlan,
    InProcessTransport,
    JsonlDeadLetterQueue,
    ResponseBuffer,
    WebhookApp,
    WebhookClient,
    build_http_server,
    canonical_json,
    delay_for,
    replay_dead_letters,
    sign,
)


def _settings(**overrides: object) -> Settings:
    base = Settings(jitter_ms=0, hmac_is_demo_default=False, hmac_secret="test-only-hmac-secret")
    data = base.__dict__.copy()
    data.update(overrides)
    return Settings(**data)


def _client(
    tmp_path: Path, settings: Settings | None = None
) -> tuple[WebhookClient, BookingStore, SimulatedClock]:
    chosen = settings or _settings()
    store = BookingStore(tmp_path / "clinic.sqlite")
    clock = SimulatedClock()
    dlq = JsonlDeadLetterQueue(tmp_path / "dlq.jsonl")
    client = WebhookClient(
        InProcessTransport(WebhookApp(store, chosen.hmac_secret)), clock, dlq, chosen
    )
    return client, store, clock


def _book(slot: str, patient: str, key: str) -> dict[str, object]:
    return {
        "tool": "book_appointment",
        "args": {"slot_id": slot, "patient_ref": patient},
        "idempotency_key": key,
        "call_id": "call-1",
    }


def test_hmac_idempotency_and_conflict(tmp_path: Path) -> None:
    client, store, clock = _client(tmp_path)
    store.ensure_slot("slot-a", "2026-11-03", "consulta_general")
    store.ensure_slot("slot-b", "2026-11-03", "consulta_general")
    first = client.invoke(_book("slot-a", "pat-1", "key-a"))
    replay = client.invoke(_book("slot-a", "pat-1", "key-a"))
    conflict = client.invoke(_book("slot-a", "pat-2", "key-b"))
    assert first["ok"] is True
    assert replay["idempotent_replay"] is True
    assert replay["booking_id"] == first["booking_id"]
    assert conflict["error"] == "slot_unavailable"
    assert store.active_counts() == {"slot-a": 1}
    assert clock.now_ms == TOOL_SUCCESS_MS + TOOL_REPLAY_MS + TOOL_SUCCESS_MS
    store.close()


def test_idempotency_survives_reopen(tmp_path: Path) -> None:
    client, store, _clock = _client(tmp_path)
    store.ensure_slot("slot-a", "2026-11-03", "consulta_general")
    first = client.invoke(_book("slot-a", "pat-1", "key-a"))
    store.close()
    reopened = BookingStore(tmp_path / "clinic.sqlite")
    again = reopened.book("slot-a", "pat-9", "key-a")
    assert again["booking_id"] == first["booking_id"]
    assert again["idempotent_replay"] is True
    assert reopened.active_counts()["slot-a"] == 1
    reopened.close()


def test_cancel_and_unknown_slot(tmp_path: Path) -> None:
    client, store, _clock = _client(tmp_path)
    store.seed_booking("slot-c", "2026-11-03", "consulta_general", "pat-1", "bk-seed")
    cancelled = client.invoke(
        {
            "tool": "cancel_appointment",
            "args": {"booking_id": "bk-seed"},
            "idempotency_key": "cancel-1",
            "call_id": "call-2",
        }
    )
    again = client.invoke(
        {
            "tool": "cancel_appointment",
            "args": {"booking_id": "bk-seed"},
            "idempotency_key": "cancel-1",
            "call_id": "call-2",
        }
    )
    missing = client.invoke(
        {
            "tool": "cancel_appointment",
            "args": {"booking_id": "missing"},
            "idempotency_key": "cancel-2",
            "call_id": "call-3",
        }
    )
    unknown = client.invoke(_book("nope", "pat-1", "key-missing"))
    assert cancelled["ok"] is True
    assert again["idempotent_replay"] is True
    assert store.active_counts() == {}
    assert missing["error"] == "not_found"
    assert unknown["error"] == "unknown_slot"
    found = client.invoke(
        {
            "tool": "find_slots",
            "args": {"date": "2026-11-03", "service": "consulta_general"},
            "idempotency_key": "find-1",
            "call_id": "call-4",
        }
    )
    assert found["ok"] is True
    store.close()


def test_bad_signature_and_payloads(tmp_path: Path) -> None:
    store = BookingStore(tmp_path / "clinic.sqlite")
    app = WebhookApp(store, "test-only-hmac-secret")
    body = canonical_json({"tool": "find_slots", "args": {}, "idempotency_key": "k"})
    status, payload = app.handle(body, {"X-Voice-Signature": "sha256=nope"})
    assert status == 401
    assert payload["error"] == "bad_signature"
    status, payload = app.handle(b"{", {"X-Voice-Signature": sign("test-only-hmac-secret", b"{")})
    assert status == 400
    status, payload = app.handle(
        canonical_json({"tool": "nope", "args": {}, "idempotency_key": "k2"}),
        {
            "X-Voice-Signature": sign(
                "test-only-hmac-secret",
                canonical_json({"tool": "nope", "args": {}, "idempotency_key": "k2"}),
            )
        },
    )
    assert payload["error"] == "unknown_tool"
    array_body = b"[]"
    status, payload = app.handle(
        array_body, {"x-voice-signature": sign("test-only-hmac-secret", array_body)}
    )
    assert payload["error"] == "bad_json"
    bad_args = canonical_json({"tool": "find_slots", "args": [], "idempotency_key": "k3"})
    status, payload = app.handle(
        bad_args, {"X-Voice-Signature": sign("test-only-hmac-secret", bad_args)}
    )
    assert payload["error"] == "bad_args"
    empty = app.handle(b"", {})
    assert empty[0] == 401
    store.close()


def test_retries_dlq_and_replay(tmp_path: Path) -> None:
    settings = _settings(
        max_attempts=3, jitter_ms=0, timeout_ms=300, backoff_base_ms=40, backoff_cap_ms=500
    )
    client, store, clock = _client(tmp_path, settings)
    store.ensure_slot("slot-a", "2026-11-03", "consulta_general")
    fault = FaultPlan("book_appointment", "http_500", 2)
    result = client.invoke(_book("slot-a", "pat-1", "key-500"), fault)
    assert result["ok"] is True
    assert result["attempts"] == 3
    backoff = delay_for(0, seed=settings.seed, key="key-500", base=40, cap=500, jitter=0)
    backoff_2 = delay_for(1, seed=settings.seed, key="key-500", base=40, cap=500, jitter=0)
    assert clock.now_ms == TOOL_SUCCESS_MS + backoff + TOOL_SUCCESS_MS + backoff_2 + TOOL_SUCCESS_MS
    store.close()

    client_b, store_b, clock_b = _client(tmp_path / "dlq", settings)
    store_b.ensure_slot("slot-z", "2026-11-03", "consulta_general")
    dropped = client_b.invoke(
        _book("slot-z", "pat-9", "key-drop"),
        FaultPlan("book_appointment", "timeout_before_commit", 9),
    )
    assert dropped["error"] == "dead_lettered"
    assert dropped["attempts"] == 3
    assert store_b.active_counts() == {}
    assert clock_b.now_ms == 300 + 40 + 300 + 80 + 300
    records = client_b.dlq.read_all()
    assert len(records) == 1
    store_b.close()

    replay_store = BookingStore(tmp_path / "dlq" / "clinic.sqlite")
    replay_client = WebhookClient(
        InProcessTransport(WebhookApp(replay_store, settings.hmac_secret)),
        SimulatedClock(),
        JsonlDeadLetterQueue(tmp_path / "dlq" / "dlq.jsonl"),
        settings,
    )
    recovered, left = replay_dead_letters(replay_client.dlq, replay_client)
    assert recovered == 1
    assert left == 0
    assert replay_store.active_counts()["slot-z"] == 1
    replay_store.close()


def test_slow_after_commit_is_idempotent(tmp_path: Path) -> None:
    settings = _settings(jitter_ms=20, timeout_ms=300)
    client, store, clock = _client(tmp_path, settings)
    store.ensure_slot("slot-a", "2026-11-03", "consulta_general")
    result = client.invoke(
        _book("slot-a", "pat-1", "key-slow"), FaultPlan("book_appointment", "slow_after_commit", 1)
    )
    assert result["ok"] is True
    assert result["attempts"] == 2
    assert store.active_counts() == {"slot-a": 1}
    pause = delay_for(0, seed=settings.seed, key="key-slow", base=40, cap=500, jitter=20)
    assert clock.now_ms == 300 + pause + TOOL_REPLAY_MS
    assert pause <= 500
    store.close()


def test_backoff_cap() -> None:
    capped = delay_for(8, seed=1, key="k", base=40, cap=50, jitter=30)
    assert 0 <= capped <= 50
    assert delay_for(8, seed=1, key="k", base=40, cap=50, jitter=0) == 50


def test_out_of_order_release_does_not_double_book(tmp_path: Path) -> None:
    store = BookingStore(tmp_path / "clinic.sqlite")
    app = WebhookApp(store, "test-only-hmac-secret")
    store.ensure_slot("slot-a", "2026-11-03", "consulta_general")
    store.ensure_slot("slot-b", "2026-11-03", "consulta_general")
    buffer = ResponseBuffer()
    bodies = [
        canonical_json(_book("slot-a", "pat-1", "key-a")),
        canonical_json(_book("slot-b", "pat-2", "key-b")),
    ]
    for body in bodies:
        signature = sign("test-only-hmac-secret", body)
        buffer.push(app.handle(body, {"X-Voice-Signature": signature}))
    observed = buffer.release_lifo()
    assert observed[0][1]["slot_id"] == "slot-b"
    assert observed[1][1]["slot_id"] == "slot-a"
    again = app.handle(bodies[0], {"X-Voice-Signature": sign("test-only-hmac-secret", bodies[0])})
    assert again[1]["idempotent_replay"] is True
    assert store.active_counts() == {"slot-a": 1, "slot-b": 1}
    store.close()


def test_transport_http_500_is_retried(tmp_path: Path) -> None:
    settings = _settings(jitter_ms=0)
    store = BookingStore(tmp_path / "clinic.sqlite")
    store.ensure_slot("slot-a", "2026-11-03", "consulta_general")
    clock = SimulatedClock()

    class Flaky(InProcessTransport):
        def __init__(self, app: WebhookApp) -> None:
            super().__init__(app)
            self.calls = 0

        def deliver(
            self, body: bytes, signature: str, timeout_ms: int
        ) -> tuple[int, dict[str, object], int]:
            self.calls += 1
            if self.calls == 1:
                return 500, {"ok": False, "error": "injected"}, TOOL_SUCCESS_MS
            return super().deliver(body, signature, timeout_ms)

    app = WebhookApp(store, settings.hmac_secret)
    client = WebhookClient(
        Flaky(app), clock, JsonlDeadLetterQueue(tmp_path / "dlq.jsonl"), settings
    )
    result = client.invoke(_book("slot-a", "pat-1", "key-flaky"))
    assert result["ok"] is True
    assert result["attempts"] == 2
    assert store.active_counts() == {"slot-a": 1}
    store.close()


def test_rejected_status_does_not_retry(tmp_path: Path) -> None:
    settings = _settings()
    store = BookingStore(tmp_path / "clinic.sqlite")
    clock = SimulatedClock()

    class BadTransport(InProcessTransport):
        def deliver(
            self, body: bytes, signature: str, timeout_ms: int
        ) -> tuple[int, dict[str, object], int]:
            del body, signature, timeout_ms
            return 401, {"ok": False, "error": "bad_signature"}, 5

    client = WebhookClient(
        BadTransport(WebhookApp(store, settings.hmac_secret)),
        clock,
        JsonlDeadLetterQueue(tmp_path / "dlq.jsonl"),
        settings,
    )
    result = client.invoke(_book("slot-a", "pat-1", "key-a"))
    assert result["error"] == "dead_lettered"
    assert result["error_class"] == "auth_failed"
    assert result["attempts"] == 1
    assert result["alert"] is True
    assert clock.now_ms == 5
    letters = client.dlq.read_all()
    assert len(letters) == 1
    assert letters[0]["error_class"] == "auth_failed"
    assert letters[0]["replayable"] is False
    store.close()


def test_http_server_roundtrip(tmp_path: Path) -> None:
    import http.client
    import threading

    store = BookingStore(tmp_path / "clinic.sqlite")
    store.ensure_slot("slot-a", "2026-11-03", "consulta_general")
    app = WebhookApp(store, "test-only-hmac-secret")
    server = build_http_server(app, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        body = canonical_json(_book("slot-a", "pat-1", "key-http"))
        connection = http.client.HTTPConnection(str(host), int(port), timeout=2)
        connection.request(
            "POST",
            "/tools",
            body=body,
            headers={
                "Content-Type": "application/json",
                "X-Voice-Signature": sign("test-only-hmac-secret", body),
            },
        )
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        connection.close()
        assert response.status == 200
        assert payload["ok"] is True
    finally:
        server.shutdown()
        server.server_close()
        store.close()


def test_empty_secret_rejected(tmp_path: Path) -> None:
    import pytest

    store = BookingStore(tmp_path / "clinic.sqlite")
    with pytest.raises(ValueError):
        WebhookApp(store, "")
    store.close()


def test_replay_skips_malformed(tmp_path: Path) -> None:
    path = tmp_path / "dlq.jsonl"
    path.write_text(json.dumps({"error": "no-envelope"}) + "\n", encoding="utf-8")
    store = BookingStore(tmp_path / "clinic.sqlite")
    settings = _settings()
    client = WebhookClient(
        InProcessTransport(WebhookApp(store, settings.hmac_secret)),
        SimulatedClock(),
        JsonlDeadLetterQueue(path),
        settings,
    )
    recovered, left = replay_dead_letters(client.dlq, client)
    assert recovered == 0
    assert left == 1
    store.close()
