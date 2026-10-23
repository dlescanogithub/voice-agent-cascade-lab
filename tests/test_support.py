from __future__ import annotations

import logging
from pathlib import Path

import pytest

from voice_cascade.config import DEMO_HMAC_SECRET, Settings
from voice_cascade.logging_setup import configure_logging, log_event
from voice_cascade.metrics import percentile
from voice_cascade.pii import add_sensitive, redact_text, reset_denylist
from voice_cascade.providers import (
    RealProviderError,
    build_real_llm,
    build_real_stt,
    build_real_tts,
)
from voice_cascade.secretscan import scan_path
from voice_cascade.trace import append_trace, read_traces


def test_settings_from_env_does_not_require_a_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VOICE_CASCADE_HMAC_SECRET", raising=False)
    monkeypatch.setenv("VOICE_CASCADE_SEED", "7")
    monkeypatch.setenv("VOICE_CASCADE_ENABLE_REAL_STT", "1")
    monkeypatch.setenv("VOICE_CASCADE_STT_API_KEY", "present-but-unused")
    settings = Settings.from_env()
    assert settings.seed == 7
    assert settings.hmac_secret == DEMO_HMAC_SECRET
    assert settings.hmac_is_demo_default is True
    assert settings.enable_real_stt is True
    assert settings.stt_api_key == "present-but-unused"


def test_explicit_hmac_is_not_marked_as_demo() -> None:
    settings = Settings.from_env({"VOICE_CASCADE_HMAC_SECRET": "another-lab-value"})
    assert settings.hmac_is_demo_default is False
    assert settings.hmac_secret == "another-lab-value"


def test_real_providers_never_call_out() -> None:
    off = Settings()
    with pytest.raises(RealProviderError, match="off"):
        build_real_stt(off)
    with pytest.raises(RealProviderError, match="off"):
        build_real_llm(off)
    with pytest.raises(RealProviderError, match="off"):
        build_real_tts(off)
    enabled = Settings(enable_real_llm=True, enable_real_tts=True, enable_real_stt=True)
    with pytest.raises(RealProviderError, match="missing"):
        build_real_stt(enabled)
    keyed = Settings(enable_real_llm=True, llm_api_key="not-sent")
    with pytest.raises(RealProviderError, match="no HTTP client"):
        build_real_llm(keyed)
    keyed_tts = Settings(enable_real_tts=True, tts_api_key="not-sent")
    with pytest.raises(RealProviderError, match="none yet"):
        build_real_tts(keyed_tts)


def test_redaction_and_json_logs() -> None:
    from voice_cascade.logging_setup import ListHandler

    reset_denylist()
    add_sensitive(["Vera Lumen", "+5491100000099"])
    assert "[REDACTED_NAME]" in redact_text("this is Vera Lumen")
    assert "[REDACTED_PHONE]" in redact_text("call +5491100000099 please")
    assert "[REDACTED_EMAIL]" in redact_text("mail vera.lumen@example.com")
    assert "2026-11-03" in redact_text("date 2026-11-03")
    logger = logging.getLogger("voice_cascade.pii_test")
    logger.handlers.clear()
    logger.propagate = False
    handler = ListHandler()
    logger.addHandler(handler)
    log_event(
        logger,
        "turn_complete",
        "appointment for Vera Lumen",
        {"phone": "+5491100000099", "patient_name": "Vera Lumen", "transcript": "this is Vera"},
    )
    captured = "\n".join(handler.lines)
    assert "Vera" not in captured
    assert "+5491100000099" not in captured
    assert "[REDACTED]" in captured
    reset_denylist()


def test_trace_roundtrip(tmp_path: Path) -> None:
    reset_denylist()
    add_sensitive(["Ciro Pampero"])
    path = tmp_path / "nested" / "trace.jsonl"
    append_trace(path, {"patient_name": "Ciro Pampero", "note": "hello Ciro"})
    rows = read_traces(path)
    assert rows[0]["patient_name"] == "[REDACTED]"
    assert "Ciro" not in str(rows[0]["note"])
    assert read_traces(tmp_path / "missing.jsonl") == []
    reset_denylist()


def test_percentile_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        percentile([], 50)
    with pytest.raises(ValueError):
        percentile([1, 2], 120)


def test_secret_scan_flags_runtime_built_samples(tmp_path: Path) -> None:
    key = "AKIA" + "IOSFODNN7EXAMPLE"
    header = "-----BEGIN " + "PRIVATE KEY-----"
    (tmp_path / "leak.txt").write_text(f"aws={key}\n{header}\n", encoding="utf-8")
    (tmp_path / ".env").write_text("VOICE_CASCADE_HMAC_SECRET=nope\n", encoding="utf-8")
    findings = scan_path(tmp_path)
    assert any(item.startswith("aws_access_key:") for item in findings)
    assert any(item.startswith("env_file:") for item in findings)
    assert scan_path(Path(".")) == []


def test_configure_logging_is_idempotent() -> None:
    first = configure_logging("INFO")
    second = configure_logging("DEBUG")
    assert first is second
    assert isinstance(first, logging.Logger)
