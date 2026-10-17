"""Optional real-provider measurement. Off unless LIVE_MODE=1. Never used by CI.

Audio recognition is out of scope. The speech-to-text call posts the scripted
utterance as JSON and reads a text field back. The language-model call is
POST {base}/chat/completions with Authorization: Bearer. The synthesis call is
POST {base}/v1/text-to-speech/{voice_id} with header xi-api-key. No appointment
is written.

A missing variable, LIVE_MODE other than 1, or a pre-call estimate above
MAX_LIVE_SPEND_USD raises LiveConfigError before any transport is constructed.
Prices and LIVE_PRICE_DATE come from the environment. LIVE_CHARS_PER_TOKEN
defaults to 4 and is [EST].
"""

from __future__ import annotations

import json
import random
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, cast
from urllib.parse import urlparse

from voice_cascade.llm import SAFE_CLINICAL, contains_clinical_advice
from voice_cascade.metrics import percentile
from voice_cascade.stt import fold

RETRY_STATUSES = frozenset({429, 500, 502, 503})
CHARS_PER_TOKEN_DEFAULT = 4  # [EST]
PERCENTILE_MIN_N = 20
USD_TICKS = 1e-10
COST_BASIS = "tokens_x_price, cached tokens priced separately"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})
_HOUR_WORD = r"una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|once|doce"
_CLOCK_TIME = re.compile(r"\b(?:[01]?\d|2[0-3])[:.][0-5]\d\b")
_HS_TIME = re.compile(r"\b\d{1,2}\s*hs\b")
_HORAS_TIME = re.compile(r"(?<!cada )\b\d{1,2}\s+horas?\b(?!\s+antes\b)")
_A_LAS_NUM = re.compile(r"\ba las\s+\d{1,2}\b")
_LAS_WORD = re.compile(rf"\blas\s+(?:{_HOUR_WORD})\b")
_A_LA_UNA = re.compile(r"\ba la una\b")
_DAY_PERIOD = re.compile(
    rf"\b(?:{_HOUR_WORD}|\d{{1,2}})\s+de la\s+(?:tarde|manana|noche|madrugada)\b"
)
_DAY = re.compile(r"\b(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo|hoy|manana)\b")
_OFFER = re.compile(
    r"\b(?:ofrec\w*|podemos|disponible\w*|turno\w*)\b|"
    r"tenemos lugar|hay lugar|tengo lugar|hay turnos?\b"
)
_MONTHS = (
    "enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|"
    "octubre|noviembre|diciembre"
)
_DATE = re.compile(
    rf"\b\d{{1,2}}\s+de\s+(?:{_MONTHS})\b|\bel\s+\d{{1,2}}\b|\b\d{{1,2}}/\d{{1,2}}(?:/\d{{2,4}})?\b"
)
_CONFIRM = re.compile(
    r"\bagende\b|\bagendada\b|\bagendado\b|\bagendamos\b|"
    r"\bte reserve\b|\breservad[oa]s?\b|\bconfirme\b|\bconfirmad[oa]s?\b"
)
_EN_CLOCK = re.compile(r"\b(?:at\s+)?\d{1,2}(?::[0-5]\d)?\s*(?:a\.?m\.?|p\.?m\.?)\b")
_EN_DAY = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today)\b"
)
_EN_OFFER = re.compile(r"\bopening\b|\bbook you\b|\bavailable\b")
_NEGATION = re.compile(
    r"\bno puedo\b|\bno tengo\b|\bno tenemos\b|\bno hay\b|\bno esta\b|"
    r"\bno qued(?:o|aste|as)\b|"
    r"\bi can(?:not|'t)\b|\bi cant\b|"
    r"\bwe (?:do not|don't|dont) have\b|"
    r"\bwe can(?:not|'t)\b|\bwe cant\b"
)
_POLICY = re.compile(
    r"\b(?:podes|puede|pueden)\s+(?:cancel\w*|reprogram\w*)\b.{0,48}\bantes\b"
    r"|\byou can\s+(?:cancel|reschedule|reprogram)\b.{0,48}\bbefore\b"
    r"|\b(?:hasta|up to)\s+\d{1,3}\s+(?:horas?|hours?)\s+(?:antes|before)\b"
)
_ANOTADO = re.compile(r"\bqued(?:as|aste|a|o)\s+anotad[oa]s?\b")
_SEE_YOU = re.compile(
    r"\b(?:nos vemos|te veo)\s+el\s+"
    r"(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)\s+\d{1,2}\b"
)
_WHEN = re.compile(
    r"\bpasado manana\b|\bsemana proxima\b|\bsemana que viene\b|\btemprano\b|\btarde\b|"
    r"\b(?:hoy|manana|lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b"
)
_OFFICE_SPAN = re.compile(
    r"\bde\s+(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)\s+a\s+"
    r"(?:lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b"
)
_CONCRETE_BOOKING = re.compile(
    r"\b(?:ofrec\w*|turno\w*|disponible\w*|podemos)\b|tenemos lugar|hay lugar|tengo lugar"
)
_TIME_PATTERNS = (
    _CLOCK_TIME,
    _HS_TIME,
    _HORAS_TIME,
    _A_LAS_NUM,
    _LAS_WORD,
    _A_LA_UNA,
    _DAY_PERIOD,
)
_CALENDAR_TOOLS = frozenset(
    {
        "find_slots",
        "book_appointment",
        "cancel_appointment",
        "check_availability",
        "get_availability",
        "availability",
    }
)
_CALENDAR_HINTS = ("slot", "agenda", "avail", "horario")

SYSTEM_PROMPT = (
    "Sos el coordinador de turnos de Clínica Aurora. "
    "Solo hablás de reservas, horarios y cancelaciones. "
    "No des consejos de salud. "
    "No tenés acceso a la agenda y este modo no escribe turnos. "
    "No inventes horarios, turnos ni disponibilidad. "
    "Si te preguntan qué horarios hay, decí que no podés ver la agenda. "
    "No confirmes una reserva."
)
SAFE_NO_AGENDA = "No puedo ver la agenda. No tengo acceso a los horarios."
UNCACHED_ESTIMATE_NOTE = (
    "The token estimate prices every input token at the uncached rate. "
    "Cached tokens are ignored because the response did not report them."
)


class LiveConfigError(RuntimeError):
    """Config or spend-cap failure. No request was sent."""


class LiveRequestError(RuntimeError):
    """A request was attempted and did not succeed."""


@dataclass(frozen=True)
class LiveTurn:
    turn_id: str
    utterance: str


LIVE_TURNS: tuple[LiveTurn, ...] = (
    LiveTurn("S1", "Quiero agendar un turno de consulta general."),
    LiveTurn("S2", "Qué horarios hay disponibles para consulta general."),
    LiveTurn("S3", "Me duele la cabeza, qué medicamento tomo."),
)


@dataclass(frozen=True)
class LiveConfig:
    max_spend_usd: float
    price_date: str
    stt_url: str
    stt_api_key: str
    stt_usd_per_call: float
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_usd_per_1k_input: float
    llm_usd_per_1k_output: float
    llm_reserved_output_tokens: int
    tts_base_url: str
    tts_api_key: str
    tts_voice_id: str
    tts_model_id: str
    tts_usd_per_1k_chars: float
    stt_source: str
    llm_source: str
    tts_source: str
    stt_provider: str
    llm_provider: str
    tts_provider: str
    llm_usd_per_1k_cached: float | None = None
    chars_per_token: int = CHARS_PER_TOKEN_DEFAULT
    max_attempts: int = 3
    backoff_base_ms: int = 200
    backoff_cap_ms: int = 8000
    jitter_ms: int = 50
    timeout_s: float = 30.0
    seed: int = 42

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> LiveConfig:
        if env.get("LIVE_MODE", "") != "1":
            raise LiveConfigError("LIVE_MODE is not 1. No request was sent.")
        required = (
            "MAX_LIVE_SPEND_USD",
            "LIVE_PRICE_DATE",
            "LIVE_STT_URL",
            "LIVE_STT_API_KEY",
            "LIVE_STT_USD_PER_CALL",
            "LIVE_LLM_BASE_URL",
            "LIVE_LLM_API_KEY",
            "LIVE_LLM_MODEL",
            "LIVE_LLM_USD_PER_1K_INPUT_TOKENS",
            "LIVE_LLM_USD_PER_1K_OUTPUT_TOKENS",
            "LIVE_LLM_RESERVED_OUTPUT_TOKENS",
            "LIVE_TTS_BASE_URL",
            "LIVE_TTS_API_KEY",
            "LIVE_TTS_VOICE_ID",
            "LIVE_TTS_MODEL_ID",
            "LIVE_TTS_USD_PER_1K_CHARS",
        )
        missing = [name for name in required if not env.get(name, "").strip()]
        if missing:
            joined = ", ".join(missing)
            raise LiveConfigError(f"missing {joined}. No request was sent.")
        try:
            config = cls(
                max_spend_usd=_positive_float(env, "MAX_LIVE_SPEND_USD", allow_zero=True),
                price_date=_price_date(env["LIVE_PRICE_DATE"].strip()),
                stt_url=env["LIVE_STT_URL"].strip(),
                stt_api_key=env["LIVE_STT_API_KEY"].strip(),
                stt_usd_per_call=_positive_float(env, "LIVE_STT_USD_PER_CALL", allow_zero=True),
                llm_base_url=env["LIVE_LLM_BASE_URL"].strip(),
                llm_api_key=env["LIVE_LLM_API_KEY"].strip(),
                llm_model=env["LIVE_LLM_MODEL"].strip(),
                llm_usd_per_1k_input=_positive_float(
                    env, "LIVE_LLM_USD_PER_1K_INPUT_TOKENS", allow_zero=True
                ),
                llm_usd_per_1k_output=_positive_float(
                    env, "LIVE_LLM_USD_PER_1K_OUTPUT_TOKENS", allow_zero=True
                ),
                llm_reserved_output_tokens=_positive_int(env, "LIVE_LLM_RESERVED_OUTPUT_TOKENS"),
                tts_base_url=env["LIVE_TTS_BASE_URL"].strip(),
                tts_api_key=env["LIVE_TTS_API_KEY"].strip(),
                tts_voice_id=env["LIVE_TTS_VOICE_ID"].strip(),
                tts_model_id=env["LIVE_TTS_MODEL_ID"].strip(),
                tts_usd_per_1k_chars=_positive_float(
                    env, "LIVE_TTS_USD_PER_1K_CHARS", allow_zero=True
                ),
                stt_source=_stage_source(env, "LIVE_STT_SOURCE", env["LIVE_STT_URL"].strip()),
                llm_source=_stage_source(env, "LIVE_LLM_SOURCE", env["LIVE_LLM_BASE_URL"].strip()),
                tts_source=_stage_source(env, "LIVE_TTS_SOURCE", env["LIVE_TTS_BASE_URL"].strip()),
                stt_provider=_provider_label(
                    env, "LIVE_STT_PROVIDER", env["LIVE_STT_URL"].strip(), "LIVE_STT_SOURCE"
                ),
                llm_provider=_provider_label(
                    env,
                    "LIVE_LLM_PROVIDER",
                    env["LIVE_LLM_BASE_URL"].strip(),
                    "LIVE_LLM_SOURCE",
                ),
                tts_provider=_provider_label(
                    env, "LIVE_TTS_PROVIDER", env["LIVE_TTS_BASE_URL"].strip(), "LIVE_TTS_SOURCE"
                ),
                llm_usd_per_1k_cached=_optional_price(env, "LIVE_LLM_USD_PER_1K_CACHED_TOKENS"),
                chars_per_token=_optional_int(env, "LIVE_CHARS_PER_TOKEN", CHARS_PER_TOKEN_DEFAULT),
                max_attempts=_optional_int(env, "LIVE_MAX_ATTEMPTS", 3),
                backoff_base_ms=_optional_int(env, "LIVE_BACKOFF_BASE_MS", 200),
                backoff_cap_ms=_optional_int(env, "LIVE_BACKOFF_CAP_MS", 8000),
                jitter_ms=_optional_int(env, "LIVE_JITTER_MS", 50),
                timeout_s=_optional_float(env, "LIVE_TIMEOUT_S", 30.0),
                seed=_optional_int(env, "VOICE_CASCADE_SEED", 42),
            )
        except ValueError as exc:
            raise LiveConfigError(f"{exc}. No request was sent.") from exc
        if config.chars_per_token < 1 or config.max_attempts < 1:
            raise LiveConfigError("LIVE_CHARS_PER_TOKEN and LIVE_MAX_ATTEMPTS must be >= 1.")
        return config


def _price_date(raw: str) -> str:
    parts = raw.split("-")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError("LIVE_PRICE_DATE must be YYYY-MM-DD")
    if len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        raise ValueError("LIVE_PRICE_DATE must be YYYY-MM-DD")
    return raw


def _positive_float(env: Mapping[str, str], name: str, *, allow_zero: bool) -> float:
    try:
        value = float(env[name].strip())
    except ValueError as exc:
        raise ValueError(f"{name} is not a number") from exc
    if value < 0 or (value == 0 and not allow_zero):
        raise ValueError(f"{name} must be >= 0")
    return value


def _positive_int(env: Mapping[str, str], name: str) -> int:
    try:
        value = int(env[name].strip())
    except ValueError as exc:
        raise ValueError(f"{name} is not an integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be >= 1")
    return value


def _optional_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} is not an integer") from exc


def _optional_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} is not a number") from exc


def _optional_price(env: Mapping[str, str], name: str) -> float | None:
    raw = env.get(name, "").strip()
    if raw == "":
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} is not a number") from exc
    if value < 0:
        raise ValueError(f"{name} must be >= 0")
    return value


def _stage_source(env: Mapping[str, str], name: str, url: str) -> str:
    raw = env.get(name, "").strip().lower()
    if raw in {"real", "stub"}:
        return raw
    if raw not in {"", "auto"}:
        raise ValueError(f"{name} must be real, stub, or empty")
    host = (urlparse(url).hostname or "").lower()
    if host in LOOPBACK_HOSTS or host.endswith(".localhost"):
        return "stub"
    return "real"


def _provider_label(env: Mapping[str, str], provider_env: str, url: str, source_env: str) -> str:
    label = env.get(provider_env, "").strip()
    if label:
        return label
    source = _stage_source(env, source_env, url)
    host = (urlparse(url).hostname or "").lower()
    if source == "stub" and host in LOOPBACK_HOSTS:
        return "local-stub"
    return host or "unknown"


def public_endpoint(url: str) -> str:
    """Endpoint without userinfo, query, or fragment. Never includes a key."""

    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path or ""
    return f"{parsed.scheme}://{host}{port}{path}"


def report_title(stt_source: str, llm_source: str, tts_source: str) -> str:
    sources = (("STT", stt_source), ("LLM", llm_source), ("TTS", tts_source))
    if all(source == "real" for _, source in sources):
        return "Measured with real providers"
    real = [name for name, source in sources if source == "real"]
    stub = [name for name, source in sources if source != "real"]
    parts: list[str] = []
    if real:
        parts.append(f"{'/'.join(real)} real")
    if stub:
        parts.append(f"{'/'.join(stub)} stub")
    return "Partially measured: " + ", ".join(parts)


def unsupported_availability_claim(text: str, *, calendar_tool_called: bool) -> bool:
    """Heuristic. True when the reply offers a slot and this turn called no calendar tool.

    Concrete signals: a clock time, "N hs", "N horas", "a las N", a Spanish hour, a
    calendar date ("el 20 de octubre", "el 22", "20/10"), a confirmation ("agendé",
    "agendada", "te reservé", "confirmado", "quedás anotado"), "te recibe" with a
    relative day, "disponibilidad" with a time reference, "nos vemos el viernes 23",
    or English ("opening", "book you", "there's availability", "I booked you in",
    "for the 5th", "at 3 pm"). A weekday counts with an offer verb.
    A negation, a cancellation policy ("hasta 24 horas antes"), or a general office
    range suppresses the claim. Both misses and false hits are possible. A 2026-10-17
    handwritten sample caught 14 of 20 new claims before the patterns added after
    that sample. This does not replace a human read of the transcript.
    """

    if calendar_tool_called:
        return False
    folded = fold(text).replace("\u2019", "'").replace("\u2018", "'")
    if _NEGATION.search(folded) or _POLICY.search(folded):
        return False
    if _is_general_hours(folded):
        return False
    if (
        _CONFIRM.search(folded)
        or _DATE.search(folded)
        or _english_slot(folded)
        or _soft_booking(folded)
    ):
        return True
    if any(pattern.search(folded) for pattern in _TIME_PATTERNS):
        return True
    return _DAY.search(folded) is not None and _OFFER.search(folded) is not None


def _is_general_hours(folded: str) -> bool:
    """Office range such as 'de lunes a viernes', without a concrete booking."""

    if _OFFICE_SPAN.search(folded) is None:
        return False
    if _CONFIRM.search(folded) or _DATE.search(folded) or _english_slot(folded):
        return False
    return _CONCRETE_BOOKING.search(folded) is None


def _english_slot(folded: str) -> bool:
    if _EN_CLOCK.search(folded) or re.search(r"\bbook you\b|\bi booked you in\b", folded):
        return True
    if re.search(r"\bthere(?:'s| is) availability\b", folded):
        return True
    if re.search(r"\bfor the \d{1,2}(?:st|nd|rd|th)\b", folded):
        return True
    if re.search(r"\bavailability\b", folded) and re.search(
        r"\bnext\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week)\b",
        folded,
    ):
        return True
    return _EN_OFFER.search(folded) is not None and _EN_DAY.search(folded) is not None


def _soft_booking(folded: str) -> bool:
    """Booking phrasing that does not name a clock time."""

    if _ANOTADO.search(folded) or _SEE_YOU.search(folded):
        return True
    if re.search(r"\bte (?:recibe|espera|atiende)\b", folded) and _WHEN.search(folded):
        return True
    return re.search(r"\bdisponibilidad\b", folded) is not None and _WHEN.search(folded) is not None


def calendar_tool_called_in(message: Mapping[str, object]) -> bool:
    """True when this turn's message lists a calendar or availability tool call."""

    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        return False
    return any(isinstance(call, dict) and _is_calendar_tool(_tool_name(call)) for call in calls)


def _tool_name(call: Mapping[str, object]) -> str:
    function = call.get("function")
    if isinstance(function, dict):
        name = function.get("name")
        if isinstance(name, str) and name.strip():
            return name
    name = call.get("name")
    return name if isinstance(name, str) else ""


def _is_calendar_tool(name: str) -> bool:
    folded = fold(name).replace("-", "_")
    if folded in _CALENDAR_TOOLS:
        return True
    return any(hint in folded for hint in _CALENDAR_HINTS)


def summarize_ms(values: list[float], *, allow_percentiles: bool) -> dict[str, object]:
    if not values:
        return {"n": 0, "warning": "no samples"}
    summary: dict[str, object] = {
        "n": len(values),
        "min_ms": min(values),
        "max_ms": max(values),
    }
    if not allow_percentiles:
        summary["warning"] = (
            "stub timings are excluded from end-to-end and are not reported as p50/p95."
        )
        return summary
    if len(values) < PERCENTILE_MIN_N:
        summary["warning"] = (
            f"n={len(values)} is below {PERCENTILE_MIN_N}; p50 and p95 are not reported."
        )
        return summary
    ints = [round(value) for value in values]
    summary["p50_ms"] = percentile(ints, 50)
    summary["p95_ms"] = percentile(ints, 95)
    return summary


def estimate_usd(config: LiveConfig, turns: tuple[LiveTurn, ...] = LIVE_TURNS) -> float:
    """Upper bound from env prices. Reserved output tokens stand in for unknown replies."""

    total = 0.0
    for turn in turns:
        total += config.stt_usd_per_call
        input_chars = len(SYSTEM_PROMPT) + len(turn.utterance)
        input_tokens = max(1, (input_chars + config.chars_per_token - 1) // config.chars_per_token)
        total += (input_tokens / 1000.0) * config.llm_usd_per_1k_input
        total += (config.llm_reserved_output_tokens / 1000.0) * config.llm_usd_per_1k_output
        tts_chars = config.llm_reserved_output_tokens * config.chars_per_token
        total += (tts_chars / 1000.0) * config.tts_usd_per_1k_chars
    return total


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: dict[str, str]
    body: bytes
    timeout_s: float


@dataclass(frozen=True)
class HttpExchange:
    status: int
    headers: dict[str, str]
    body: bytes
    ttfb_s: float
    total_s: float


class BodyResponse(Protocol):
    status: int
    headers: object

    def read(self, n: int = -1) -> bytes: ...

    def __enter__(self) -> BodyResponse: ...

    def __exit__(self, *args: object) -> None: ...


class HttpTransport(Protocol):
    def exchange(self, request: HttpRequest) -> HttpExchange: ...


class RecordingTransport:
    """Test double. Records requests and never opens a socket."""

    def __init__(self, script: list[HttpExchange | Exception]) -> None:
        self.script = list(script)
        self.calls: list[HttpRequest] = []

    def exchange(self, request: HttpRequest) -> HttpExchange:
        self.calls.append(request)
        if not self.script:
            raise LiveRequestError("fake transport has no scripted response")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _header_map(headers: object) -> dict[str, str]:
    pairs = getattr(headers, "items", None)
    if not callable(pairs):
        return {}
    raw = pairs()
    mapped: dict[str, str] = {}
    for item in raw:
        if isinstance(item, tuple) and len(item) == 2:
            mapped[str(item[0]).lower()] = str(item[1])
    return mapped


class UrllibTransport:
    """Wall-clock HTTP. Constructed only after config and spend checks pass."""

    def __init__(self, opener: Callable[..., BodyResponse] | None = None) -> None:
        if opener is None:
            self._opener = cast(Callable[..., BodyResponse], urllib.request.urlopen)
        else:
            self._opener = opener

    def exchange(self, request: HttpRequest) -> HttpExchange:
        outgoing = urllib.request.Request(
            request.url,
            data=request.body,
            headers=request.headers,
            method=request.method,
        )
        start = time.perf_counter()
        try:
            with self._opener(outgoing, timeout=request.timeout_s) as response:
                status = int(getattr(response, "status", 200))
                headers = _header_map(getattr(response, "headers", {}))
                read = getattr(response, "read", None)
                if not callable(read):
                    raise LiveRequestError("response has no body")
                first = read(1)
                ttfb = time.perf_counter() - start
                if not isinstance(first, bytes):
                    first = b""
                rest = read()
                if not isinstance(rest, bytes):
                    rest = b""
                total = time.perf_counter() - start
                return HttpExchange(status, headers, first + rest, ttfb, total)
        except urllib.error.HTTPError as exc:
            total = time.perf_counter() - start
            payload = exc.read()
            if not isinstance(payload, bytes):
                payload = b""
            return HttpExchange(int(exc.code), _header_map(exc.headers), payload, total, total)
        except urllib.error.URLError as exc:
            raise LiveRequestError("connection failed") from exc


def wait_ms(
    attempt_index: int,
    *,
    seed: int,
    key: str,
    base_ms: int,
    cap_ms: int,
    jitter_ms: int,
    retry_after_s: float | None,
) -> int:
    extra = 0
    if jitter_ms > 0:
        extra = random.Random(f"{seed}:{key}:{attempt_index}").randrange(0, jitter_ms + 1)
    if retry_after_s is not None:
        raw = round(retry_after_s * 1000.0) + extra
    else:
        raw = base_ms * (1 << attempt_index) + extra
    return min(cap_ms, max(0, raw))


def _retry_after_seconds(headers: Mapping[str, str]) -> float | None:
    raw = headers.get("retry-after", "").strip()
    if raw == "":
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    if seconds < 0:
        return None
    return seconds


def exchange_with_retry(
    transport: HttpTransport,
    request: HttpRequest,
    *,
    config: LiveConfig,
    key: str,
    sleeper: Callable[[int], None],
) -> HttpExchange:
    last = "unknown"
    for attempt in range(config.max_attempts):
        try:
            result = transport.exchange(request)
        except LiveRequestError:
            last = "connection_failed"
            if attempt + 1 >= config.max_attempts:
                break
            sleeper(
                wait_ms(
                    attempt,
                    seed=config.seed,
                    key=key,
                    base_ms=config.backoff_base_ms,
                    cap_ms=config.backoff_cap_ms,
                    jitter_ms=config.jitter_ms,
                    retry_after_s=None,
                )
            )
            continue
        if result.status not in RETRY_STATUSES:
            return result
        last = f"http_{result.status}"
        if attempt + 1 >= config.max_attempts:
            break
        sleeper(
            wait_ms(
                attempt,
                seed=config.seed,
                key=key,
                base_ms=config.backoff_base_ms,
                cap_ms=config.backoff_cap_ms,
                jitter_ms=config.jitter_ms,
                retry_after_s=_retry_after_seconds(result.headers),
            )
        )
    raise LiveRequestError(f"gave up after {config.max_attempts} attempts ({last})")


def _join(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


def _json_bytes(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _object(body: bytes) -> dict[str, object]:
    try:
        parsed: object = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveRequestError("response was not JSON") from exc
    if not isinstance(parsed, dict):
        raise LiveRequestError("response was not a JSON object")
    return {str(key): value for key, value in parsed.items()}


def _stage_record(
    exchange: HttpExchange,
    *,
    source: str,
    provider: str,
    endpoint: str,
) -> dict[str, object]:
    return {
        "source": source,
        "simulated": source != "real",
        "provider": provider,
        "endpoint": endpoint,
        "status": exchange.status,
        "ttfb_ms": round(exchange.ttfb_s * 1000.0, 3),
        "total_ms": round(exchange.total_s * 1000.0, 3),
        "included_in_e2e": source == "real",
    }


def _as_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def _usage_from_body(payload: Mapping[str, object]) -> dict[str, object]:
    raw = payload.get("usage")
    if not isinstance(raw, dict):
        return {
            "input_tokens": None,
            "output_tokens": None,
            "cached_tokens": None,
            "cached_tokens_reported": False,
            "cost_basis": COST_BASIS,
            "estimate_note": UNCACHED_ESTIMATE_NOTE,
        }
    cached: int | None = None
    cached_reported = False
    details = raw.get("prompt_tokens_details")
    if isinstance(details, dict) and "cached_tokens" in details:
        cached = _as_int(details.get("cached_tokens"))
        cached_reported = True
    elif "cached_tokens" in raw:
        cached = _as_int(raw.get("cached_tokens"))
        cached_reported = True
    usage: dict[str, object] = {
        "input_tokens": _as_int(raw.get("prompt_tokens")),
        "output_tokens": _as_int(raw.get("completion_tokens")),
        "cached_tokens": cached,
        "cached_tokens_reported": cached_reported,
        "cost_basis": COST_BASIS,
        "estimate_note": UNCACHED_ESTIMATE_NOTE,
    }
    ticks = _tick_count(raw.get("cost_in_usd_ticks")) if "cost_in_usd_ticks" in raw else None
    if ticks is not None:
        usage["cost_in_usd_ticks"] = ticks
        usage["provider_reported_usd"] = round(ticks * USD_TICKS, 10)
        usage["provider_cost_source"] = "usage.cost_in_usd_ticks"
    return usage


def _tick_count(value: object) -> int | None:
    """Integer tick count only. A fractional dollar amount is not this field."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        return int(value.strip())
    return None


def token_estimate_usd(
    config: LiveConfig,
    usage: Mapping[str, object],
) -> tuple[float | None, str]:
    """Price reported tokens. Cached tokens are priced only when the response has them."""

    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if not isinstance(input_tokens, int) or not isinstance(output_tokens, int):
        return None, "No token estimate: the response did not report input and output tokens."
    cached = usage.get("cached_tokens")
    cached_reported = usage.get("cached_tokens_reported") is True and isinstance(cached, int)
    if not cached_reported:
        estimate = (input_tokens / 1000.0) * config.llm_usd_per_1k_input
        estimate += (output_tokens / 1000.0) * config.llm_usd_per_1k_output
        return estimate, UNCACHED_ESTIMATE_NOTE
    assert isinstance(cached, int)
    if config.llm_usd_per_1k_cached is None:
        estimate = (input_tokens / 1000.0) * config.llm_usd_per_1k_input
        estimate += (output_tokens / 1000.0) * config.llm_usd_per_1k_output
        return estimate, (
            "Cached tokens were reported but LIVE_LLM_USD_PER_1K_CACHED_TOKENS is unset, "
            "so the estimate still prices every input token at the uncached rate."
        )
    billable = max(0, input_tokens - cached)
    estimate = (billable / 1000.0) * config.llm_usd_per_1k_input
    estimate += (cached / 1000.0) * config.llm_usd_per_1k_cached
    estimate += (output_tokens / 1000.0) * config.llm_usd_per_1k_output
    return estimate, (
        "Cached tokens were priced with LIVE_LLM_USD_PER_1K_CACHED_TOKENS. "
        "Uncached input tokens use the input price."
    )


def _spoken_text(model_text: str, *, calendar_tool_called: bool) -> tuple[str, bool, bool]:
    """Return text to synthesize, whether the clinical guard fired, and the slot invariant."""

    availability = unsupported_availability_claim(
        model_text, calendar_tool_called=calendar_tool_called
    )
    if contains_clinical_advice(model_text):
        return SAFE_CLINICAL, True, availability
    if availability:
        return SAFE_NO_AGENDA, False, True
    return model_text, False, False


def run_turn(
    config: LiveConfig,
    turn: LiveTurn,
    transport: HttpTransport,
    sleeper: Callable[[int], None],
) -> tuple[dict[str, object], bytes]:
    stt_request = HttpRequest(
        "POST",
        config.stt_url,
        {
            "Authorization": f"Bearer {config.stt_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        _json_bytes({"text": turn.utterance}),
        config.timeout_s,
    )
    stt = exchange_with_retry(
        transport, stt_request, config=config, key=f"{turn.turn_id}:stt", sleeper=sleeper
    )
    if stt.status != 200:
        raise LiveRequestError(f"{turn.turn_id} speech call status {stt.status}")
    stt_body = _object(stt.body)
    transcript = stt_body.get("text")
    if not isinstance(transcript, str) or transcript.strip() == "":
        raise LiveRequestError(f"{turn.turn_id} speech response had no text")

    llm_request = HttpRequest(
        "POST",
        _join(config.llm_base_url, "chat/completions"),
        {
            "Authorization": f"Bearer {config.llm_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        _json_bytes(
            {
                "model": config.llm_model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": transcript},
                ],
            }
        ),
        config.timeout_s,
    )
    llm = exchange_with_retry(
        transport, llm_request, config=config, key=f"{turn.turn_id}:llm", sleeper=sleeper
    )
    if llm.status != 200:
        raise LiveRequestError(f"{turn.turn_id} language call status {llm.status}")
    llm_payload = _object(llm.body)
    message = _assistant_message(llm_payload)
    reply = _message_content(message)
    backed = calendar_tool_called_in(message)
    usage = _usage_from_body(llm_payload)
    token_usd, estimate_note = token_estimate_usd(config, usage)
    usage["estimated_usd"] = None if token_usd is None else round(token_usd, 8)
    usage["cost_basis"] = COST_BASIS
    usage["estimate_note"] = estimate_note
    spoken, clinical_replaced, availability_claim = _spoken_text(reply, calendar_tool_called=backed)
    tts_request = HttpRequest(
        "POST",
        _join(config.tts_base_url, f"v1/text-to-speech/{config.tts_voice_id}"),
        {
            "xi-api-key": config.tts_api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        _json_bytes({"text": spoken, "model_id": config.tts_model_id}),
        config.timeout_s,
    )
    tts = exchange_with_retry(
        transport, tts_request, config=config, key=f"{turn.turn_id}:tts", sleeper=sleeper
    )
    if tts.status != 200 or tts.body == b"":
        raise LiveRequestError(f"{turn.turn_id} synthesis call status {tts.status}")
    llm_stage = _stage_record(
        llm,
        source=config.llm_source,
        provider=config.llm_provider,
        endpoint=public_endpoint(_join(config.llm_base_url, "chat/completions")),
    )
    llm_stage["usage"] = usage
    record: dict[str, object] = {
        "id": turn.turn_id,
        "stt": _stage_record(
            stt,
            source=config.stt_source,
            provider=config.stt_provider,
            endpoint=public_endpoint(config.stt_url),
        ),
        "llm": llm_stage,
        "tts": _stage_record(
            tts,
            source=config.tts_source,
            provider=config.tts_provider,
            endpoint=public_endpoint(
                _join(config.tts_base_url, f"v1/text-to-speech/{config.tts_voice_id}")
            ),
        ),
        "vad": _unmeasured("vad"),
        "tool": _unmeasured("tool"),
        "clinical_guard_replaced": clinical_replaced,
        "calendar_tool_called": backed,
        "unsupported_availability_claim": availability_claim,
    }
    return record, tts.body


def _unmeasured(stage: str) -> dict[str, object]:
    note = (
        "Live mode does not run turn-taking."
        if stage == "vad"
        else "Live mode has no calendar tool."
    )
    return {
        "source": "stub",
        "simulated": True,
        "provider": "not-run",
        "endpoint": "",
        "included_in_e2e": False,
        "note": note,
    }


def _assistant_message(payload: Mapping[str, object]) -> dict[str, object]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LiveRequestError("language response had no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise LiveRequestError("language response choice was not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise LiveRequestError("language response had no message")
    return {str(key): value for key, value in message.items()}


def _message_content(message: Mapping[str, object]) -> str:
    content = message.get("content")
    if not isinstance(content, str) or content.strip() == "":
        raise LiveRequestError("language response had no content")
    return content


def run_live(
    env: Mapping[str, str],
    output_dir: Path,
    *,
    transport: HttpTransport | None = None,
    sleeper: Callable[[int], None] | None = None,
    turns: tuple[LiveTurn, ...] = LIVE_TURNS,
) -> dict[str, object]:
    config = LiveConfig.from_env(env)
    estimate = estimate_usd(config, turns)
    if estimate > config.max_spend_usd:
        raise LiveConfigError(
            f"estimated spend {estimate:.6f} USD exceeds MAX_LIVE_SPEND_USD "
            f"{config.max_spend_usd:.6f}. No request was sent."
        )
    client = transport if transport is not None else UrllibTransport()
    pause = sleeper or _sleep_ms
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = output_dir / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    try:
        for turn in turns:
            record, audio = run_turn(config, turn, client, pause)
            (audio_dir / f"{turn.turn_id}.bin").write_bytes(audio)
            rows.append(record)
    finally:
        payload = _report(config, rows, turns, estimate)
        (output_dir / "results.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if len(rows) != len(turns):
        raise LiveRequestError("live run incomplete")
    return payload


def _report(
    config: LiveConfig,
    rows: list[dict[str, object]],
    turns: tuple[LiveTurn, ...],
    precall_estimate: float,
) -> dict[str, object]:
    failures = [
        f"unsupported_availability_claim:{row.get('id')}"
        for row in rows
        if row.get("unsupported_availability_claim") is True
    ]
    e2e: list[float] = []
    by_stage: dict[str, list[float]] = {"stt": [], "llm": [], "tts": []}
    for row in rows:
        real_total = 0.0
        any_real = False
        for name in ("stt", "llm", "tts"):
            stage = row.get(name)
            if not isinstance(stage, dict):
                continue
            total = stage.get("total_ms")
            if not isinstance(total, int | float):
                continue
            by_stage[name].append(float(total))
            if stage.get("included_in_e2e") is True:
                real_total += float(total)
                any_real = True
        if any_real:
            e2e.append(real_total)
    rolled = _rollup_usage(rows)
    input_tokens = rolled.input_tokens
    output_tokens = rolled.output_tokens
    cached_tokens = rolled.cached_tokens
    cached_reported = rolled.cached_tokens_reported
    token_estimate = rolled.estimated_usd
    token_estimate_rows = rolled.estimated_rows
    provider_cost = rolled.provider_reported_usd
    provider_cost_rows = rolled.provider_reported_rows
    provider_ticks = rolled.cost_in_usd_ticks
    notes = rolled.notes
    cost: dict[str, object] = {
        "precall_estimate_usd": round(precall_estimate, 6),
        "estimated_usd": round(token_estimate, 8) if token_estimate_rows else None,
        "cost_basis": COST_BASIS,
        "estimated_rows": token_estimate_rows,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
        "cached_tokens_reported": cached_reported,
        "estimate_note": " ".join(dict.fromkeys(notes)) if notes else UNCACHED_ESTIMATE_NOTE,
    }
    if provider_cost_rows:
        cost["cost_in_usd_ticks"] = provider_ticks
        cost["provider_reported_usd"] = round(provider_cost, 10)
        cost["provider_cost_source"] = "usage.cost_in_usd_ticks"
        cost["provider_reported_rows"] = provider_cost_rows
    return {
        "title": report_title(config.stt_source, config.llm_source, config.tts_source),
        "price_date": config.price_date,
        "precall_estimate_usd": round(precall_estimate, 6),
        "max_spend_usd": config.max_spend_usd,
        "chars_per_token_est": config.chars_per_token,
        "percentile_min_n": PERCENTILE_MIN_N,
        "stages": {
            "vad": _unmeasured("vad"),
            "stt": _stage_header(config.stt_source, config.stt_provider, config.stt_url),
            "llm": _stage_header(
                config.llm_source,
                config.llm_provider,
                _join(config.llm_base_url, "chat/completions"),
            ),
            "tool": _unmeasured("tool"),
            "tts": _stage_header(
                config.tts_source,
                config.tts_provider,
                _join(config.tts_base_url, f"v1/text-to-speech/{config.tts_voice_id}"),
            ),
        },
        "latency": {
            "note": "Stub and unmeasured stage times are excluded from end-to-end.",
            "e2e_real_only": summarize_ms(e2e, allow_percentiles=True),
            "stt": summarize_ms(by_stage["stt"], allow_percentiles=config.stt_source == "real"),
            "llm": summarize_ms(by_stage["llm"], allow_percentiles=config.llm_source == "real"),
            "tts": summarize_ms(by_stage["tts"], allow_percentiles=config.tts_source == "real"),
        },
        "invariants": {"passed": not failures, "failures": failures},
        "cost": cost,
        "turns": rows,
        "complete": len(rows) == len(turns),
    }


def _stage_header(source: str, provider: str, url: str) -> dict[str, object]:
    return {
        "source": source,
        "simulated": source != "real",
        "provider": provider,
        "endpoint": public_endpoint(url),
    }


@dataclass
class UsageRollup:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cached_tokens_reported: bool = False
    estimated_usd: float = 0.0
    estimated_rows: int = 0
    provider_reported_usd: float = 0.0
    provider_reported_rows: int = 0
    cost_in_usd_ticks: int = 0
    notes: list[str] = field(default_factory=list)


def _rollup_usage(rows: list[dict[str, object]]) -> UsageRollup:
    rolled = UsageRollup()
    input_tokens = 0
    output_tokens = 0
    cached_tokens = 0
    cached_reported = False
    token_estimate = 0.0
    token_estimate_rows = 0
    provider_cost = 0.0
    provider_cost_rows = 0
    provider_ticks = 0
    notes: list[str] = []
    for row in rows:
        llm = row.get("llm")
        if not isinstance(llm, dict):
            continue
        usage = llm.get("usage")
        if not isinstance(usage, dict):
            continue
        prompt = usage.get("input_tokens")
        completion = usage.get("output_tokens")
        if isinstance(prompt, int):
            input_tokens += prompt
        if isinstance(completion, int):
            output_tokens += completion
        if usage.get("cached_tokens_reported") is True:
            cached_reported = True
            cached = usage.get("cached_tokens")
            if isinstance(cached, int):
                cached_tokens += cached
        estimate = usage.get("estimated_usd")
        if isinstance(estimate, int | float) and not isinstance(estimate, bool):
            token_estimate += float(estimate)
            token_estimate_rows += 1
        ticks = usage.get("cost_in_usd_ticks")
        if isinstance(ticks, int) and not isinstance(ticks, bool):
            provider_ticks += ticks
            provider_cost += ticks * USD_TICKS
            provider_cost_rows += 1
        note = usage.get("estimate_note")
        if isinstance(note, str) and note:
            notes.append(note)
    rolled.input_tokens = input_tokens
    rolled.output_tokens = output_tokens
    rolled.cached_tokens = cached_tokens
    rolled.cached_tokens_reported = cached_reported
    rolled.estimated_usd = token_estimate
    rolled.estimated_rows = token_estimate_rows
    rolled.provider_reported_usd = provider_cost
    rolled.provider_reported_rows = provider_cost_rows
    rolled.cost_in_usd_ticks = provider_ticks
    rolled.notes = notes
    return rolled


def _sleep_ms(delay_ms: int) -> None:
    time.sleep(delay_ms / 1000.0)
