from __future__ import annotations

import json
from email.message import Message
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from voice_cascade.live import (
    LIVE_TURNS,
    HttpExchange,
    HttpRequest,
    LiveConfig,
    LiveConfigError,
    LiveRequestError,
    RecordingTransport,
    UrllibTransport,
    estimate_usd,
    exchange_with_retry,
    run_live,
    wait_ms,
)
from voice_cascade.llm import SAFE_CLINICAL


def _env(**overrides: str) -> dict[str, str]:
    base = {
        "LIVE_MODE": "1",
        "MAX_LIVE_SPEND_USD": "5",
        "LIVE_PRICE_DATE": "2026-10-17",
        "LIVE_STT_URL": "http://stt.example.invalid/v1/transcribe",
        "LIVE_STT_API_KEY": "lab-stt-key",
        "LIVE_STT_USD_PER_CALL": "0.01",
        "LIVE_LLM_BASE_URL": "http://llm.example.invalid/v1",
        "LIVE_LLM_API_KEY": "lab-llm-key",
        "LIVE_LLM_MODEL": "lab-model",
        "LIVE_LLM_USD_PER_1K_INPUT_TOKENS": "0.002",
        "LIVE_LLM_USD_PER_1K_OUTPUT_TOKENS": "0.004",
        "LIVE_LLM_RESERVED_OUTPUT_TOKENS": "32",
        "LIVE_TTS_BASE_URL": "http://tts.example.invalid",
        "LIVE_TTS_API_KEY": "lab-tts-key",
        "LIVE_TTS_VOICE_ID": "voice-lab",
        "LIVE_TTS_MODEL_ID": "model-lab",
        "LIVE_TTS_USD_PER_1K_CHARS": "0.003",
        "LIVE_JITTER_MS": "0",
        "LIVE_BACKOFF_BASE_MS": "200",
        "LIVE_BACKOFF_CAP_MS": "8000",
        "VOICE_CASCADE_SEED": "42",
    }
    base.update(overrides)
    return base


def _exchange(status: int, body: bytes, *, ttfb: float = 0.01, total: float = 0.02) -> HttpExchange:
    return HttpExchange(status, {}, body, ttfb, total)


def _stt(text: str = "quiero un turno") -> HttpExchange:
    return _exchange(200, json.dumps({"text": text}).encode())


def _llm(text: str) -> HttpExchange:
    payload = {"choices": [{"message": {"role": "assistant", "content": text}}]}
    return _exchange(200, json.dumps(payload).encode(), ttfb=0.03, total=0.04)


def _tts() -> HttpExchange:
    return _exchange(200, b"audio-bytes", ttfb=0.05, total=0.08)


def _script() -> list[HttpExchange | Exception]:
    replies = (
        "El horario de las diez está libre.",
        "Hay lugar a la mañana.",
        "Tome ibuprofeno 400 mg cada 8 horas.",
    )
    script: list[HttpExchange | Exception] = []
    for reply in replies:
        script.extend((_stt(), _llm(reply), _tts()))
    return script


def test_missing_config_sends_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[str] = []

    def boom() -> None:
        built.append("built")

    monkeypatch.setattr("voice_cascade.live.UrllibTransport", boom)
    with pytest.raises(LiveConfigError, match="No request was sent"):
        run_live({}, tmp_path)
    assert built == []
    assert not (tmp_path / "results.json").exists()


def test_spend_cap_sends_nothing(tmp_path: Path) -> None:
    transport = RecordingTransport([])
    env = _env(MAX_LIVE_SPEND_USD="0.0001", LIVE_STT_USD_PER_CALL="2")
    with pytest.raises(LiveConfigError, match="exceeds"):
        run_live(env, tmp_path, transport=transport)
    assert transport.calls == []
    assert not (tmp_path / "results.json").exists()


def test_estimate_uses_env_prices_and_the_est_token_width() -> None:
    config = LiveConfig.from_env(_env(LIVE_CHARS_PER_TOKEN="4"))
    assert config.chars_per_token == 4
    assert estimate_usd(config, LIVE_TURNS[:1]) > 0
    with pytest.raises(LiveConfigError, match="YYYY-MM-DD"):
        LiveConfig.from_env(_env(LIVE_PRICE_DATE="October"))


def test_scripted_run_measures_wall_clock_fields_and_guards_advice(tmp_path: Path) -> None:
    transport = RecordingTransport(_script())
    payload = run_live(_env(), tmp_path, transport=transport, sleeper=lambda _ms: None)
    assert payload["simulated"] is False
    assert payload["title"] == "Measured with real providers"
    assert payload["complete"] is True
    assert payload["price_date"] == "2026-10-17"
    turns = payload["turns"]
    assert isinstance(turns, list)
    assert len(turns) == 3
    first = turns[0]
    assert isinstance(first, dict)
    stt = first["stt"]
    assert isinstance(stt, dict)
    assert stt["ttfb_ms"] == 10.0
    assert stt["total_ms"] == 20.0
    assert turns[2]["clinical_guard_replaced"] is True
    tts_calls = [call for call in transport.calls if "text-to-speech" in call.url]
    assert len(tts_calls) == 3
    guarded = json.loads(tts_calls[2].body.decode("utf-8"))
    assert guarded["text"] == SAFE_CLINICAL
    assert "ibuprofeno" not in guarded["text"]
    assert tts_calls[2].headers["xi-api-key"] == "lab-tts-key"
    assert tts_calls[2].url.endswith("/v1/text-to-speech/voice-lab")
    llm_calls = [call for call in transport.calls if call.url.endswith("/chat/completions")]
    assert llm_calls[0].headers["Authorization"] == "Bearer lab-llm-key"
    written = (tmp_path / "results.json").read_text(encoding="utf-8")
    assert "lab-stt-key" not in written
    assert "lab-llm-key" not in written
    assert "lab-tts-key" not in written
    assert (tmp_path / "audio" / "S3.bin").read_bytes() == b"audio-bytes"


def test_retry_after_is_honored_and_capped() -> None:
    config = LiveConfig.from_env(_env())
    slept: list[int] = []
    transport = RecordingTransport(
        [
            HttpExchange(429, {"retry-after": "2"}, b"", 0.1, 0.1),
            _stt(),
        ]
    )
    request = HttpRequest("POST", "http://stt.example.invalid/v1", {}, b"{}", 1.0)
    result = exchange_with_retry(
        transport, request, config=config, key="S1:stt", sleeper=slept.append
    )
    assert result.status == 200
    assert slept == [2000]
    capped = wait_ms(
        0,
        seed=1,
        key="k",
        base_ms=200,
        cap_ms=8000,
        jitter_ms=0,
        retry_after_s=100,
    )
    assert capped == 8000


def test_backoff_when_retry_after_is_absent_and_connection_errors_retry() -> None:
    config = LiveConfig.from_env(_env(LIVE_MAX_ATTEMPTS="3"))
    slept: list[int] = []
    transport = RecordingTransport(
        [
            LiveRequestError("connection failed"),
            HttpExchange(503, {}, b"busy", 0.0, 0.0),
            _stt(),
        ]
    )
    request = HttpRequest("POST", "http://stt.example.invalid/v1", {}, b"{}", 1.0)
    result = exchange_with_retry(
        transport, request, config=config, key="S1:stt", sleeper=slept.append
    )
    assert result.status == 200
    assert slept == [200, 400]


def test_client_error_is_not_retried() -> None:
    config = LiveConfig.from_env(_env())
    slept: list[int] = []
    transport = RecordingTransport([HttpExchange(401, {}, b"no", 0.0, 0.0)])
    request = HttpRequest("POST", "http://stt.example.invalid/v1", {}, b"{}", 1.0)
    result = exchange_with_retry(
        transport, request, config=config, key="S1:stt", sleeper=slept.append
    )
    assert result.status == 401
    assert slept == []


def test_urllib_transport_uses_the_injected_opener_and_http_errors() -> None:
    seen: list[object] = []

    class _Resp:
        def __init__(self, body: bytes) -> None:
            self.status = 200
            self.headers = {"Content-Type": "application/json"}
            self._body = body
            self._pos = 0

        def read(self, n: int = -1) -> bytes:
            if n is None or n < 0:
                chunk = self._body[self._pos :]
                self._pos = len(self._body)
                return chunk
            chunk = self._body[self._pos : self._pos + n]
            self._pos += len(chunk)
            return chunk

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *args: object) -> None:
            return None

    def opener(outgoing: object, timeout: float = 0) -> _Resp:
        del timeout
        seen.append(outgoing)
        return _Resp(b'{"text":"ok"}')

    transport = UrllibTransport(opener)
    request = HttpRequest(
        "POST",
        "http://stt.example.invalid/v1",
        {"Authorization": "Bearer lab-stt-key"},
        b"{}",
        5.0,
    )
    result = transport.exchange(request)
    assert result.status == 200
    assert result.body == b'{"text":"ok"}'
    assert result.ttfb_s <= result.total_s
    assert seen

    headers = Message()
    headers["Retry-After"] = "1"

    def failing(outgoing: object, timeout: float = 0) -> _Resp:
        del outgoing, timeout
        raise HTTPError(
            "http://stt.example.invalid/v1",
            503,
            "busy",
            headers,
            BytesIO(b"later"),
        )

    failed = UrllibTransport(failing).exchange(request)
    assert failed.status == 503
    assert failed.headers.get("retry-after") == "1"
    assert failed.body == b"later"

    def offline(outgoing: object, timeout: float = 0) -> _Resp:
        del outgoing, timeout
        raise URLError("timed out")

    with pytest.raises(LiveRequestError, match="connection failed"):
        UrllibTransport(offline).exchange(request)
