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


def _stt(text: str = "I want an appointment") -> HttpExchange:
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
        "I can't confirm a booking.",
        "I can't see the schedule.",
        "Take ibuprofen 400 mg every 8 hours.",
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
    assert "ibuprofen" not in guarded["text"]
    assert tts_calls[2].headers["xi-api-key"] == "lab-tts-key"
    assert tts_calls[2].url.endswith("/v1/text-to-speech/voice-lab")
    llm_calls = [call for call in transport.calls if call.url.endswith("/chat/completions")]
    assert llm_calls[0].headers["Authorization"] == "Bearer lab-llm-key"
    sent = json.loads(llm_calls[0].body.decode("utf-8"))
    assert "You do not have access to the schedule" in sent["messages"][0]["content"]
    assert "Do not invent times" in sent["messages"][0]["content"]
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
    "Sure. These times are open for a general consultation: "
    "9:00, 10:30, 11:45, 14:00, 15:15 and 16:30."
)
HONEST_AGENDA = "I can't see the schedule."


POSITIVE_OFFERS = (
    INVENTED_SLOTS,
    "There are openings at 9:00 and 10:30.",
    "I have Tuesday available.",
    "I have tomorrow morning available.",
    "I can offer you 3 pm.",
    "I can offer you 9:00.",
    "I can offer you 3:00 pm.",
    "There is a slot at 11:00.",
    "Tomorrow at 10:00 we have a slot.",
    "Tomorrow at 8:00 we have a slot.",
    "Monday at 10:00 there is an opening.",
    "Friday at 11:00 we have a slot.",
    "We can do Thursday at 3 pm.",
    "Today at 2 pm there is an opening.",
    "We have a slot on Wednesday.",
    "The 10:00 slot is open.",
    "There is an opening tomorrow morning.",
    "The day after tomorrow at 4:00 we have a slot.",
    "At 1:00 there is a slot.",
    "I can give you an appointment on October 20.",
    "Your appointment is scheduled for Tuesday.",
    "I have a slot on the 22nd.",
    "Yes, I already booked you.",
    "I reserved 22/10/2026 for you.",
    "The appointment is set for 20/10.",
    "I have an opening tomorrow at 3 pm",
    "We can book you Tuesday at 10am",
    "I am available Tuesday at 10 am",
    "That time is open, and you're booked for Tuesday.",
    "You're on the list for the consultation.",
    "You're on the list.",
    "The doctor will see you tomorrow morning.",
    "There is availability next week.",
    "We can see you early on Monday.",
    "We have availability next Thursday.",
    "There is availability tomorrow.",
    "There's availability next Thursday",
    "There is availability next week",
    "I booked you in for the 5th at noon",
    "See you on Friday the 23rd.",
    "See you on Monday the 4th.",
    "I have an opening Thursday afternoon.",
    "Yes, on Wednesday we have a slot.",
    "We have a slot on Monday.",
    "I can fit you in tomorrow first thing.",
    "I can fit you in Thursday morning.",
    "I confirm your appointment at 10:15.",
    "Saturday morning is open.",
    "Thursday afternoon is open.",
    "We have an appointment open tomorrow morning",
    "Slots are available on the 12th, 13th and 14th",
    "I've scheduled you for next Wednesday at 4",
    "Next Tuesday afternoon is open if you'd like",
    "You're booked with Dr. Lopez on Friday the 6th.",
    "You're booked with Dr. Perez on Monday the 3rd.",
    "We can see you tomorrow afternoon",
    "There's a free slot on Friday morning",
    "I've put you down for Wednesday at 9",
    "Our next opening is the 21st at half past two",
    "The study requires an 8 hour fast, and I can offer you 3 pm.",
    "I've reserved your follow-up for Saturday morning.",
    "We have reserved the appointment for Monday.",
    "I can fit you in tomorrow around noon",
    "Your appointment is confirmed for November 5th",
    "I scheduled your check-up for Friday at 2",
    "We're holding a spot for you on Tuesday at 11",
    "Sure, I've reserved 3 o'clock on Thursday for you",
    "I can offer you 3 pm. Rest for 24 hours.",
    "I've blocked Friday at noon for your appointment",
    "You're booked with Dr. Lee on Tuesday morning",
    "You are booked with Dr. Lee on Tuesday morning",
    "We still have a slot this Saturday at 9",
    "Okay, Monday at 8 works, it's on the calendar now",
)
NEGATIVE_OFFERS = (
    HONEST_AGENDA,
    "I can't see the schedule. I don't have access to the times.",
    "I'm transferring you to the front desk so they can take your details.",
    "I don't give health advice today.",
    "We can continue whenever you want.",
    "Monday is closed.",
    "The appointment was not saved.",
    "There is nobody on the line.",
    "We'll call you in a little while.",
    "Take ibuprofen 400 mg every 8 hours.",
    "I can't confirm availability for Tuesday at 10:00.",
    "We are open Monday to Friday at 9:00.",
    "We are open Monday to Friday from 9 to 6.",
    "I don't have an appointment on Tuesday at 10:00.",
    "We don't have a slot tomorrow.",
    "I can't book you Tuesday at 10am",
    "We don't have an opening tomorrow at 3 pm",
    "We cannot book you at 3 pm",
    "It is not confirmed for Tuesday at 10:00.",
    "The appointment was not scheduled.",
    "You can cancel up to 24 hours before.",
    "You can reschedule up to 2 hours before.",
    "You can cancel up to 24 hours before",
    "You can reschedule up to 2 hours before",
    "I don't have an opening on Thursday afternoon.",
    "There is no slot on Wednesday.",
    "I can't fit you in tomorrow first thing.",
    "Insurance coverage is handled at the front desk.",
    "Leave a gap in the afternoon for lunch.",
    "Arrive first thing if you can.",
    "I confirm that we received the form.",
    "I do not confirm the appointment.",
    "Saturday morning is closed.",
    "The parking lot is open.",
    "We don't have an appointment open tomorrow morning",
    "Slots are not available on the 12th",
    "Ask whether slots are available",
    "I have not scheduled you for Wednesday",
    "Next Tuesday afternoon is closed",
    "The loading dock on Tuesday afternoon is for deliveries",
    "You can cancel the opening up to 24 hours before.",
    "You can cancel the slot up to 24 hours before",
    "The study requires an 8 hour fast",
    "The study requires a 12 hour fast.",
    "You need to fast for 8 hours",
    "You must stay fasting for 6 hours.",
    "Instruction: an 8 hour fast.",
    "The study lasts 8 hours.",
    "Rest for 8 hours.",
    "The study requires an 8 hour fast",
    "You need to fast for 8 hours",
    "You were left wondering.",
    "We can see you in the lobby",
    "We cannot see you tomorrow afternoon",
    "There is no free slot on Friday morning",
    "The free slot for coats is in the hall",
    "I have not put you down for Wednesday",
    "I didn't put you down for Wednesday",
    "Lunch is at half past two",
    "The next opening of the wing is a renovation",
    "Our next opening is in the spring",
    "We don't have a next opening on the 21st",
    "You can reschedule the appointment up to 24 hours before.",
    "Rest for 24 hours.",
    "Please rest.",
    "Absolute rest for 24 hours.",
    "Absolute rest for 48 hours.",
    "Rest for 12 hours.",
    "Instruction: 24 hours of rest.",
    "Please reserve judgment",
    "I did not reserve your follow-up.",
    "I cannot fit you in tomorrow around noon",
    "I can fit you in the waiting room",
    "Lunch is around noon",
    "Your appointment is not confirmed for November 5th",
    "Your appointment may be confirmed",
    "November 5th is a public holiday",
    "I did not schedule your check-up for Friday",
    "We're not holding a spot for you on Tuesday",
    "Holding a spot in the parking lot",
    "The conference room is reserved for Thursday",
    "I have not reserved a time on Thursday",
    "Lunch is at 3 o'clock",
    "The study requires an 8 hour fast and rest for 24 hours.",
    "Fast for 10 hours.",
    "You need to fast for 10 hours.",
    "Take the antibiotic every 8 hours.",
    "Fast for 12 hours",
    "Rest for 24 hours",
    "Please rest for 24 hours",
    "The procedure takes about 3 hours",
    "The appointment takes about 3 hours",
    "I have not blocked Friday at noon for your appointment",
    "The road is blocked on Friday",
    "I've blocked the driveway on Friday",
    "You're not booked with Dr. Lee on Tuesday morning",
    "The conference room is booked on Tuesday",
    "We don't have a slot this Saturday",
    "We have no slot this Saturday at 9",
    "We have a slot in the parking garage",
    "It's not on the calendar for Monday at 8",
    "Monday at 8 works for the courier",
    "Monday's notice is on the calendar by the door",
    "You can cancel up to 24 hours before and fast for 10 hours.",
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
    turn = LiveTurn("S2", "What times are available for a general consultation?")
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
    turn = LiveTurn("S2", "What times are available for a general consultation?")
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
        "I can't confirm availability for Tuesday at 10:00.",
        "We are open Monday to Friday at 9:00.",
        "I can't book you Tuesday at 10am",
        "We don't have an opening tomorrow at 3 pm",
        "You can cancel up to 24 hours before.",
        "You can reschedule up to 2 hours before.",
        "You can cancel up to 24 hours before",
        "I don't have an opening on Thursday afternoon.",
        "Saturday morning is closed.",
        "Slots are not available on the 12th",
        "Next Tuesday afternoon is closed",
        "You can cancel the opening up to 24 hours before.",
        "The study requires an 8 hour fast.",
        "You need to fast for 8 hours.",
        "The study requires an 8 hour fast",
        "We cannot see you tomorrow afternoon",
        "There is no free slot on Friday morning",
        "I have not put you down for Wednesday",
        "You can reschedule the appointment up to 24 hours before.",
        "Rest for 24 hours.",
        "Absolute rest for 48 hours.",
        "The study requires an 8 hour fast and rest for 24 hours.",
        "I did not reserve your follow-up.",
        "I cannot fit you in tomorrow around noon",
        "Your appointment is not confirmed for November 5th",
        "I did not schedule your check-up for Friday",
        "We're not holding a spot for you on Tuesday",
        "I have not reserved a time on Thursday",
        "Fast for 10 hours.",
        "Fast for 12 hours",
        "Rest for 24 hours",
        "The procedure takes about 3 hours",
        "I have not blocked Friday at noon for your appointment",
        "You're not booked with Dr. Lee on Tuesday morning",
        "We have no slot this Saturday at 9",
        "It's not on the calendar for Monday at 8",
        "You can reschedule up to 2 hours before",
    )
    for phrase in phrases:
        turn = LiveTurn("S2", "What times are open?")
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
    assert calendar_tool_called_in({"tool_calls": [{"function": {"name": "list_schedules"}}]})
    assert calendar_tool_called_in({"tool_calls": [{"name": "check-availability"}]})
    assert calendar_tool_called_in(
        {"tool_calls": [{"function": {"name": "  "}, "name": "find_slots"}]}
    )
    assert calendar_tool_called_in({}) is False
    assert calendar_tool_called_in({"tool_calls": ["nope"]}) is False
    assert calendar_tool_called_in({"tool_calls": [{"function": {"name": ""}}]}) is False


def test_offered_hours_without_a_tool_call_are_not_spoken(tmp_path: Path) -> None:
    phrases = (
        "I can offer you 3 pm.",
        "Tomorrow at 10:00 we have a slot.",
        "Monday at 10:00 there is an opening.",
        "We can do Thursday at 3 pm.",
        "I can give you an appointment on October 20.",
        "Your appointment is scheduled for Tuesday.",
        "I have a slot on the 22nd.",
        "Yes, I already booked you.",
        "I have an opening tomorrow at 3 pm",
        "We can book you Tuesday at 10am",
        "That time is open, and you're booked for Tuesday.",
        "The doctor will see you tomorrow morning.",
        "There is availability next week.",
        "There's availability next Thursday",
        "I booked you in for the 5th at noon",
        "See you on Friday the 23rd.",
        "I have an opening Thursday afternoon.",
        "Yes, on Wednesday we have a slot.",
        "I can fit you in tomorrow first thing.",
        "I confirm your appointment at 10:15.",
        "Saturday morning is open.",
        "We have an appointment open tomorrow morning",
        "Slots are available on the 12th, 13th and 14th",
        "I've scheduled you for next Wednesday at 4",
        "Next Tuesday afternoon is open if you'd like",
        "You're booked with Dr. Lopez on Friday the 6th.",
        "We can see you tomorrow afternoon",
        "There's a free slot on Friday morning",
        "I've put you down for Wednesday at 9",
        "Our next opening is the 21st at half past two",
        "I've reserved your follow-up for Saturday morning.",
        "I can fit you in tomorrow around noon",
        "Your appointment is confirmed for November 5th",
        "I scheduled your check-up for Friday at 2",
        "We're holding a spot for you on Tuesday at 11",
        "Sure, I've reserved 3 o'clock on Thursday for you",
        "I've blocked Friday at noon for your appointment",
        "You're booked with Dr. Lee on Tuesday morning",
        "We still have a slot this Saturday at 9",
        "Okay, Monday at 8 works, it's on the calendar now",
    )
    for phrase in phrases:
        turn = LiveTurn("S2", "What times are open?")
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
    phrase = "I can offer you 3 pm."
    calls = [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "find_slots", "arguments": "{}"},
        }
    ]
    turn = LiveTurn("S2", "What times are open?")
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
    phrase = "Tomorrow at 10:00 we have a slot."
    calls = [{"name": "transfer_to_desk"}]
    turn = LiveTurn("S2", "What times are open?")
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
    turn = LiveTurn("S1", "I want to book a general consultation appointment.")
    transport = RecordingTransport([_stt(), _llm("I can't confirm a booking.", usage), _tts()])
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
    turn = LiveTurn("S1", "I want to book a general consultation appointment.")
    transport = RecordingTransport([_stt(), _llm("I can't confirm a booking.", usage), _tts()])
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
    turn = LiveTurn("S1", "I want to book a general consultation appointment.")
    payload = run_live(
        _env(),
        tmp_path,
        transport=RecordingTransport([_stt(), _llm("Done.", usage), _tts()]),
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
