from __future__ import annotations

import json
from pathlib import Path

import pytest

import voice_cascade.__main__ as entrypoint
from voice_cascade.booking import BookingStore
from voice_cascade.cli import main
from voice_cascade.clock import SimulatedClock
from voice_cascade.config import Settings
from voice_cascade.webhook import (
    FaultPlan,
    InProcessTransport,
    JsonlDeadLetterQueue,
    WebhookApp,
    WebhookClient,
    canonical_json,
    serve,
)


def test_cli_gate_demo_and_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOICE_CASCADE_DATA_DIR", str(tmp_path / "data"))
    assert main(["demo"]) == 0
    assert main(["eval"]) == 0
    report = json.loads((tmp_path / "reports" / "eval.json").read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["simulated"] is True
    assert report["title"] == "SIMULATED latency report"
    assert main(["eval", "--profile", "patient"]) == 0
    assert main(["eval", "--profile", "aggressive"]) == 1
    assert main(["eval-regression"]) == 1
    assert main(["latency-report"]) == 0
    regression = json.loads((tmp_path / "reports" / "regression.json").read_text(encoding="utf-8"))
    assert regression["passed"] is False
    assert main(["secretscan", str(tmp_path / "reports")]) == 0


def test_cli_dlq_replay_and_serve(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VOICE_CASCADE_HMAC_SECRET", "test-only-hmac-secret")
    monkeypatch.setenv("VOICE_CASCADE_DATA_DIR", str(tmp_path / "data"))
    settings = Settings.from_env()
    store = BookingStore(tmp_path / "clinic.sqlite")
    store.ensure_slot("slot-z", "2026-11-03", "consulta_general")
    dlq_path = tmp_path / "dlq.jsonl"
    client = WebhookClient(
        InProcessTransport(WebhookApp(store, settings.hmac_secret)),
        SimulatedClock(),
        JsonlDeadLetterQueue(dlq_path),
        settings,
    )
    dropped = client.invoke(
        {
            "tool": "book_appointment",
            "args": {"slot_id": "slot-z", "patient_ref": "pat-z"},
            "idempotency_key": "replay-me",
            "call_id": "cli",
        },
        FaultPlan("book_appointment", "timeout_before_commit", 9),
    )
    assert dropped["error"] == "dead_lettered"
    store.close()
    assert (
        main(["dlq-replay", "--dlq", str(dlq_path), "--db", str(tmp_path / "clinic.sqlite")]) == 0
    )
    reopened = BookingStore(tmp_path / "clinic.sqlite")
    assert reopened.active_counts()["slot-z"] == 1
    reopened.close()

    def fake_serve(app: WebhookApp, host: str = "127.0.0.1", port: int = 8765) -> None:
        del app
        assert host == "127.0.0.1"
        assert port == 9

    monkeypatch.setattr("voice_cascade.cli.serve", fake_serve)
    assert main(["webhook-serve", "--port", "9"]) == 0


def test_module_entrypoint_is_importable() -> None:
    assert callable(entrypoint.main)


def test_live_without_config_exits_before_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LIVE_MODE", raising=False)
    assert main(["live"]) == 2


def test_live_command_prints_a_measured_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("VOICE_CASCADE_DATA_DIR", str(tmp_path))

    def fake_run(env: object, output: Path) -> dict[str, object]:
        del env
        assert output == tmp_path / "live"
        return {
            "title": "Measured with real providers",
            "turns": [{}],
            "estimated_usd": 0.01,
            "price_date": "2026-10-17",
            "invariants": {"passed": True, "failures": []},
        }

    monkeypatch.setattr("voice_cascade.cli.run_live", fake_run)
    assert main(["live"]) == 0
    captured = capsys.readouterr().out
    assert "Measured with real providers" in captured
    assert "README table" in captured

    def fail_run(env: object, output: Path) -> dict[str, object]:
        del env, output
        from voice_cascade.live import LiveRequestError

        raise LiveRequestError("gave up")

    monkeypatch.setattr("voice_cascade.cli.run_live", fail_run)
    assert main(["live"]) == 1


def test_live_command_exits_1_when_an_invariant_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VOICE_CASCADE_DATA_DIR", str(tmp_path))

    def fake_run(env: object, output: Path) -> dict[str, object]:
        del env, output
        return {
            "title": "Partially measured: LLM real, STT/TTS stub",
            "turns": [{}],
            "estimated_usd": 0.01,
            "price_date": "2026-10-17",
            "invariants": {
                "passed": False,
                "failures": ["unsupported_availability_claim:S2"],
            },
            "latency": {
                "e2e_real_only": {
                    "n": 3,
                    "warning": "n=3 is below 20; p50 and p95 are not reported.",
                }
            },
        }

    monkeypatch.setattr("voice_cascade.cli.run_live", fake_run)
    assert main(["live"]) == 1


def test_cli_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        main([])


def test_serve_returns_after_forever_stops(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = BookingStore(tmp_path / "clinic.sqlite")
    app = WebhookApp(store, "test-only-hmac-secret")
    monkeypatch.setattr(
        "voice_cascade.webhook.ThreadingHTTPServer.serve_forever",
        lambda self: None,
    )
    serve(app, "127.0.0.1", 0)
    store.close()


def test_canonical_json_is_stable() -> None:
    body = canonical_json({"b": 1, "a": "z"})
    assert body == b'{"a":"z","b":1}'
