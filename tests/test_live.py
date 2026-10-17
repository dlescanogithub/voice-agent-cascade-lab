from __future__ import annotations

import json
from email.message import Message
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from voice_cascade.live import (
    COST_BASIS,
    LIVE_TURNS,
    PERCENTILE_MIN_N,
    SAFE_NO_AGENDA,
    SYSTEM_PROMPT,
    HttpExchange,
    HttpRequest,
    LiveConfig,
    LiveConfigError,
    LiveRequestError,
    LiveTurn,
    RecordingTransport,
    UrllibTransport,
    calendar_tool_called_in,
    estimate_usd,
    exchange_with_retry,
    report_title,
    run_live,
    summarize_ms,
    token_estimate_usd,
    unsupported_availability_claim,
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


def _llm(
    text: str,
    usage: dict[str, object] | None = None,
    tool_calls: list[dict[str, object]] | None = None,
) -> HttpExchange:
    message: dict[str, object] = {"role": "assistant", "content": text}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    payload: dict[str, object] = {"choices": [{"message": message}]}
    if usage is not None:
        payload["usage"] = usage
    return _exchange(200, json.dumps(payload).encode(), ttfb=0.03, total=0.04)


def _tts() -> HttpExchange:
    return _exchange(200, b"audio-bytes", ttfb=0.05, total=0.08)


def _script() -> list[HttpExchange | Exception]:
    replies = (
        "No puedo confirmar una reserva.",
        "No puedo ver la agenda.",
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
    assert "simulated" not in payload
    assert payload["title"] == "Measured with real providers"
    stages = payload["stages"]
    assert isinstance(stages, dict)
    for name in ("stt", "llm", "tts"):
        stage = stages[name]
        assert isinstance(stage, dict)
        assert stage["source"] == "real"
        assert stage["simulated"] is False
    assert stages["vad"]["source"] == "stub"
    assert stages["tool"]["source"] == "stub"
    assert stages["tool"]["provider"] == "not-run"
    latency = payload["latency"]
    assert isinstance(latency, dict)
    e2e = latency["e2e_real_only"]
    assert isinstance(e2e, dict)
    assert e2e["n"] == 3
    assert "p50" not in e2e
    assert "p50_ms" not in e2e
    assert "p95_ms" not in e2e
    assert "warning" in e2e
    assert payload["complete"] is True
    assert payload["price_date"] == "2026-10-17"
    invariants = payload["invariants"]
    assert isinstance(invariants, dict)
    assert invariants["passed"] is True
    cost = payload["cost"]
    assert isinstance(cost, dict)
    assert cost["cost_basis"] == COST_BASIS
    assert cost["estimated_usd"] is None
    assert "provider_reported_usd" not in cost
    assert "token_estimate_usd" not in cost
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
    sent = json.loads(llm_calls[0].body.decode("utf-8"))
    assert "No tenés acceso a la agenda" in sent["messages"][0]["content"]
    assert "No inventes horarios" in sent["messages"][0]["content"]
    assert SYSTEM_PROMPT in sent["messages"][0]["content"]
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


INVENTED_SLOTS = (
    "Claro. Tengo disponible estos horarios para consulta general: "
    "9:00, 10:30, 11:45, 14:00, 15:15 y 16:30."
)
HONEST_AGENDA = "No puedo ver la agenda."


POSITIVE_OFFERS = (
    INVENTED_SLOTS,
    "Hay turnos a las 9:00, 10:30.",
    "Tengo disponible el martes.",
    "tengo disponible a la mañana",
    "Te puedo ofrecer las 15 hs",
    "Te ofrezco las 9hs.",
    "Te puedo ofrecer las 15 horas.",
    "A las 11 horas hay lugar.",
    "Mañana a las 10 tenemos lugar",
    "Mañana a las ocho tenemos lugar.",
    "El lunes a las diez hay lugar",
    "El viernes a las once tenemos lugar.",
    "Podemos el jueves a las 3 de la tarde",
    "Hoy a las dos de la tarde hay turno.",
    "Hay lugar el miércoles.",
    "El horario de las diez está libre.",
    "Hay lugar a la mañana.",
    "Pasado mañana a las 4 tenemos lugar.",
    "A la una hay lugar.",
    "Te puedo dar turno el 20 de octubre",
    "Su cita está agendada para el martes",
    "Tengo lugar el 22",
    "Sí, ya te agendé",
    "Te reservé el 22/10/2026",
    "Quedó el turno para el 20/10",
    "I have an opening tomorrow at 3 pm",
    "We can book you Tuesday at 10am",
    "I am available Tuesday at 10 am",
)
NEGATIVE_OFFERS = (
    HONEST_AGENDA,
    "No puedo ver la agenda. No tengo acceso a los horarios.",
    "Te derivo con recepción para que te tomen los datos.",
    "Hoy no doy consejos de salud.",
    "Podemos seguir cuando quieras.",
    "El lunes está cerrado.",
    "El turno no se registró.",
    "No hay una persona en la línea.",
    "En un rato te llamamos.",
    "Tome ibuprofeno 400 mg cada 8 horas.",
    "No puedo confirmar disponibilidad el martes a las 10",
    "Atendemos de lunes a viernes a las 9",
    "Atendemos de lunes a viernes de 9 a 18",
    "No tengo turno el martes a las 10",
    "No tenemos lugar mañana",
    "I can't book you Tuesday at 10am",
    "We don't have an opening tomorrow at 3 pm",
    "We cannot book you at 3 pm",
    "No está confirmado el martes a las 10",
    "No quedó agendada la cita",
)


def test_availability_claim_flags_offers_and_ignores_non_offers() -> None:
    for phrase in POSITIVE_OFFERS:
        assert unsupported_availability_claim(phrase, calendar_tool_called=False) is True, phrase
        assert unsupported_availability_claim(phrase, calendar_tool_called=True) is False, phrase
    for phrase in NEGATIVE_OFFERS:
        assert unsupported_availability_claim(phrase, calendar_tool_called=False) is False, phrase


def test_loopback_stubs_are_not_titled_as_a_full_measurement(tmp_path: Path) -> None:
    env = _env(
        LIVE_STT_URL="http://127.0.0.1:9/transcribe",
        LIVE_TTS_BASE_URL="http://127.0.0.1:9",
    )
    transport = RecordingTransport(_script())
    payload = run_live(env, tmp_path, transport=transport, sleeper=lambda _ms: None)
    assert payload["title"] == "Partially measured: LLM real, STT/TTS stub"
    stages = payload["stages"]
    assert isinstance(stages, dict)
    assert stages["stt"]["source"] == "stub"
    assert stages["stt"]["provider"] == "local-stub"
    assert stages["stt"]["simulated"] is True
    assert stages["tts"]["source"] == "stub"
    assert stages["llm"]["source"] == "real"
    assert stages["llm"]["simulated"] is False
    assert "127.0.0.1:9" in str(stages["stt"]["endpoint"])
    assert "lab-stt-key" not in str(stages["stt"]["endpoint"])
    latency = payload["latency"]
    assert isinstance(latency, dict)
    e2e = latency["e2e_real_only"]
    assert isinstance(e2e, dict)
    assert e2e["min_ms"] == 40.0
    assert e2e["max_ms"] == 40.0
    assert "p50_ms" not in e2e
    stub = latency["stt"]
    assert isinstance(stub, dict)
    assert "p50_ms" not in stub
    assert "excluded from end-to-end" in str(stub["warning"])


def test_invented_slots_fail_the_live_invariant_and_are_not_spoken(tmp_path: Path) -> None:
    turn = LiveTurn("S2", "Qué horarios hay disponibles para consulta general.")
    transport = RecordingTransport([_stt(), _llm(INVENTED_SLOTS), _tts()])
    payload = run_live(
        _env(),
        tmp_path,
        transport=transport,
        sleeper=lambda _ms: None,
        turns=(turn,),
    )
    invariants = payload["invariants"]
    assert isinstance(invariants, dict)
    assert invariants["passed"] is False
    assert invariants["failures"] == ["unsupported_availability_claim:S2"]
    spoken = json.loads(transport.calls[2].body.decode("utf-8"))
    assert spoken["text"] == SAFE_NO_AGENDA
    assert "9:00" not in spoken["text"]
    assert "10:30" not in spoken["text"]


def test_honest_agenda_reply_passes(tmp_path: Path) -> None:
    turn = LiveTurn("S2", "Qué horarios hay disponibles para consulta general.")
    transport = RecordingTransport([_stt(), _llm(HONEST_AGENDA), _tts()])
    payload = run_live(
        _env(),
        tmp_path,
        transport=transport,
        sleeper=lambda _ms: None,
        turns=(turn,),
    )
    invariants = payload["invariants"]
    assert isinstance(invariants, dict)
    assert invariants["passed"] is True
    spoken = json.loads(transport.calls[2].body.decode("utf-8"))
    assert spoken["text"] == HONEST_AGENDA


def test_negation_and_office_hours_are_spoken(tmp_path: Path) -> None:
    phrases = (
        "No puedo confirmar disponibilidad el martes a las 10",
        "Atendemos de lunes a viernes a las 9",
        "I can't book you Tuesday at 10am",
        "We don't have an opening tomorrow at 3 pm",
    )
    for phrase in phrases:
        turn = LiveTurn("S2", "Qué horarios hay.")
        transport = RecordingTransport([_stt(), _llm(phrase), _tts()])
        payload = run_live(
            _env(),
            tmp_path,
            transport=transport,
            sleeper=lambda _ms: None,
            turns=(turn,),
        )
        invariants = payload["invariants"]
        assert isinstance(invariants, dict)
        assert invariants["passed"] is True, phrase
        spoken = json.loads(transport.calls[2].body.decode("utf-8"))
        assert spoken["text"] == phrase


def test_calendar_tool_names_cover_hints_and_ignore_junk() -> None:
    assert calendar_tool_called_in({"tool_calls": [{"function": {"name": "list_horarios"}}]})
    assert calendar_tool_called_in({"tool_calls": [{"name": "check-availability"}]})
    assert calendar_tool_called_in(
        {"tool_calls": [{"function": {"name": "  "}, "name": "find_slots"}]}
    )
    assert calendar_tool_called_in({}) is False
    assert calendar_tool_called_in({"tool_calls": ["nope"]}) is False
    assert calendar_tool_called_in({"tool_calls": [{"function": {"name": ""}}]}) is False


def test_offered_hours_without_a_tool_call_are_not_spoken(tmp_path: Path) -> None:
    phrases = (
        "Te puedo ofrecer las 15 hs",
        "Mañana a las 10 tenemos lugar",
        "El lunes a las diez hay lugar",
        "Podemos el jueves a las 3 de la tarde",
        "Te puedo dar turno el 20 de octubre",
        "Su cita está agendada para el martes",
        "Tengo lugar el 22",
        "Sí, ya te agendé",
        "I have an opening tomorrow at 3 pm",
        "We can book you Tuesday at 10am",
    )
    for phrase in phrases:
        turn = LiveTurn("S2", "Qué horarios hay.")
        transport = RecordingTransport([_stt(), _llm(phrase), _tts()])
        payload = run_live(
            _env(),
            tmp_path,
            transport=transport,
            sleeper=lambda _ms: None,
            turns=(turn,),
        )
        invariants = payload["invariants"]
        assert isinstance(invariants, dict)
        assert invariants["failures"] == ["unsupported_availability_claim:S2"]
        spoken = json.loads(transport.calls[2].body.decode("utf-8"))
        assert spoken["text"] == SAFE_NO_AGENDA
        assert phrase not in spoken["text"]


def test_calendar_tool_call_backs_the_same_offer(tmp_path: Path) -> None:
    phrase = "Te puedo ofrecer las 15 hs"
    calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "find_slots", "arguments": "{}"},
        }
    ]
    turn = LiveTurn("S2", "Qué horarios hay.")
    transport = RecordingTransport([_stt(), _llm(phrase, tool_calls=calls), _tts()])
    payload = run_live(
        _env(),
        tmp_path,
        transport=transport,
        sleeper=lambda _ms: None,
        turns=(turn,),
    )
    invariants = payload["invariants"]
    assert isinstance(invariants, dict)
    assert invariants["passed"] is True
    turns = payload["turns"]
    assert isinstance(turns, list)
    assert turns[0]["calendar_tool_called"] is True
    spoken = json.loads(transport.calls[2].body.decode("utf-8"))
    assert spoken["text"] == phrase


def test_unrelated_tool_call_does_not_back_an_offer(tmp_path: Path) -> None:
    phrase = "Mañana a las 10 tenemos lugar"
    calls = [{"name": "transfer_to_desk"}]
    turn = LiveTurn("S2", "Qué horarios hay.")
    transport = RecordingTransport([_stt(), _llm(phrase, tool_calls=calls), _tts()])
    payload = run_live(
        _env(),
        tmp_path,
        transport=transport,
        sleeper=lambda _ms: None,
        turns=(turn,),
    )
    invariants = payload["invariants"]
    assert isinstance(invariants, dict)
    assert invariants["passed"] is False
    turns = payload["turns"]
    assert isinstance(turns, list)
    assert turns[0]["calendar_tool_called"] is False


def test_usage_records_tokens_cached_estimate_and_provider_ticks(tmp_path: Path) -> None:
    usage = {
        "prompt_tokens": 237,
        "completion_tokens": 40,
        "prompt_tokens_details": {"cached_tokens": 128},
        "cost_in_usd_ticks": 8555500,
    }
    turn = LiveTurn("S1", "Quiero agendar un turno de consulta general.")
    transport = RecordingTransport([_stt(), _llm("No puedo confirmar una reserva.", usage), _tts()])
    payload = run_live(
        _env(LIVE_LLM_USD_PER_1K_CACHED_TOKENS="0.0002"),
        tmp_path,
        transport=transport,
        sleeper=lambda _ms: None,
        turns=(turn,),
    )
    cost = payload["cost"]
    assert isinstance(cost, dict)
    assert cost["input_tokens"] == 237
    assert cost["output_tokens"] == 40
    assert cost["cached_tokens"] == 128
    assert cost["cached_tokens_reported"] is True
    assert cost["cost_basis"] == COST_BASIS
    assert cost["cost_in_usd_ticks"] == 8555500
    assert cost["provider_cost_source"] == "usage.cost_in_usd_ticks"
    assert cost["provider_reported_usd"] == pytest.approx(8555500 * 1e-10)
    turns = payload["turns"]
    assert isinstance(turns, list)
    llm = turns[0]["llm"]
    assert isinstance(llm, dict)
    recorded = llm["usage"]
    assert isinstance(recorded, dict)
    assert recorded["cost_basis"] == cost["cost_basis"]
    assert "Cached tokens were priced" in str(recorded["estimate_note"])
    config = LiveConfig.from_env(_env(LIVE_LLM_USD_PER_1K_CACHED_TOKENS="0.0002"))
    estimate, _note = token_estimate_usd(config, recorded)
    assert cost["estimated_usd"] == pytest.approx(estimate)
    assert recorded["estimated_usd"] == pytest.approx(estimate)
    assert cost["estimated_usd"] != pytest.approx(cost["provider_reported_usd"])
    assert "token_estimate_usd" not in cost
    assert "token_estimate_usd" not in recorded
    assert recorded["cost_in_usd_ticks"] == 8555500
    assert recorded["provider_cost_source"] == "usage.cost_in_usd_ticks"


def test_token_price_is_not_a_provider_bill(tmp_path: Path) -> None:
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 10,
        "cost": 1.25,
        "estimated_usd": 1.25,
        "provider_reported_usd": 1.25,
        "total_cost_usd": 1.25,
        "cost_in_usd_ticks": 0.00125,
    }
    turn = LiveTurn("S1", "Quiero agendar un turno de consulta general.")
    transport = RecordingTransport([_stt(), _llm("No puedo confirmar una reserva.", usage), _tts()])
    payload = run_live(
        _env(),
        tmp_path,
        transport=transport,
        sleeper=lambda _ms: None,
        turns=(turn,),
    )
    cost = payload["cost"]
    assert isinstance(cost, dict)
    assert cost["cost_basis"] == COST_BASIS
    assert cost["estimated_usd"] == pytest.approx((100 / 1000) * 0.002 + (10 / 1000) * 0.004)
    assert "provider_reported_usd" not in cost
    turns = payload["turns"]
    assert isinstance(turns, list)
    llm = turns[0]["llm"]
    assert isinstance(llm, dict)
    recorded = llm["usage"]
    assert isinstance(recorded, dict)
    assert "provider_reported_usd" not in recorded
    assert recorded["estimated_usd"] == cost["estimated_usd"]
    assert payload["precall_estimate_usd"] != cost["estimated_usd"]
    assert "cost_in_usd_ticks" not in cost
    assert "provider_cost_source" not in cost


def test_integer_tick_string_is_a_provider_bill_and_a_replayed_estimate_is_not(
    tmp_path: Path,
) -> None:
    usage = {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "cost_in_usd_ticks": "8555500",
        "provider_reported_usd": 9.99,
    }
    turn = LiveTurn("S1", "Quiero agendar un turno de consulta general.")
    payload = run_live(
        _env(),
        tmp_path,
        transport=RecordingTransport([_stt(), _llm("Listo.", usage), _tts()]),
        sleeper=lambda _ms: None,
        turns=(turn,),
    )
    cost = payload["cost"]
    assert isinstance(cost, dict)
    assert cost["cost_in_usd_ticks"] == 8555500
    assert cost["provider_cost_source"] == "usage.cost_in_usd_ticks"
    assert cost["provider_reported_usd"] == pytest.approx(8555500 * 1e-10)
    assert cost["provider_reported_usd"] != pytest.approx(9.99)


def test_estimate_ignores_cached_tokens_when_usage_omits_them() -> None:
    config = LiveConfig.from_env(_env())
    usage = {
        "input_tokens": 100,
        "output_tokens": 10,
        "cached_tokens": None,
        "cached_tokens_reported": False,
    }
    estimate, note = token_estimate_usd(config, usage)
    assert estimate == pytest.approx((100 / 1000) * 0.002 + (10 / 1000) * 0.004)
    assert "did not report them" in note


def test_small_n_omits_percentiles_and_a_larger_n_reports_them() -> None:
    small = summarize_ms([970, 984, 1328], allow_percentiles=True)
    assert small["n"] == 3
    assert small["min_ms"] == 970
    assert small["max_ms"] == 1328
    assert "p50_ms" not in small
    assert "p95_ms" not in small
    assert PERCENTILE_MIN_N == 20
    large = summarize_ms([100.0] * PERCENTILE_MIN_N, allow_percentiles=True)
    assert large["p50_ms"] == 100
    assert large["p95_ms"] == 100
    assert "warning" not in large


def test_explicit_stub_overrides_a_non_loopback_host() -> None:
    assert report_title("stub", "real", "stub") == "Partially measured: LLM real, STT/TTS stub"
    config = LiveConfig.from_env(_env(LIVE_STT_SOURCE="stub", LIVE_TTS_SOURCE="stub"))
    assert config.stt_source == "stub"
    assert config.tts_source == "stub"
    assert config.llm_source == "real"
