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
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from voice_cascade.llm import SAFE_CLINICAL, contains_clinical_advice

RETRY_STATUSES = frozenset({429, 500, 502, 503})
CHARS_PER_TOKEN_DEFAULT = 4  # [EST]

SYSTEM_PROMPT = (
    "Sos el coordinador de turnos de Clínica Aurora. "
    "Solo hablás de reservas, horarios y cancelaciones. "
    "No des consejos de salud. No confirmes una reserva: este modo no escribe la agenda."
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


def _stage_record(exchange: HttpExchange) -> dict[str, object]:
    return {
        "status": exchange.status,
        "ttfb_ms": round(exchange.ttfb_s * 1000.0, 3),
        "total_ms": round(exchange.total_s * 1000.0, 3),
    }


def _speakable(model_text: str) -> str:
    if contains_clinical_advice(model_text):
        return SAFE_CLINICAL
    return model_text


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
    reply = _message_text(_object(llm.body))
    spoken = _speakable(reply)
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
    record: dict[str, object] = {
        "id": turn.turn_id,
        "stt": _stage_record(stt),
        "llm": _stage_record(llm),
        "tts": _stage_record(tts),
        "clinical_guard_replaced": spoken != reply,
    }
    return record, tts.body


def _message_text(payload: Mapping[str, object]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LiveRequestError("language response had no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise LiveRequestError("language response choice was not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise LiveRequestError("language response had no message")
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
        payload: dict[str, object] = {
            "title": "Measured with real providers",
            "simulated": False,
            "price_date": config.price_date,
            "estimated_usd": round(estimate, 6),
            "max_spend_usd": config.max_spend_usd,
            "chars_per_token_est": config.chars_per_token,
            "turns": rows,
            "complete": len(rows) == len(turns),
        }
        (output_dir / "results.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if len(rows) != len(turns):
        raise LiveRequestError("live run incomplete")
    return payload


def _sleep_ms(delay_ms: int) -> None:
    time.sleep(delay_ms / 1000.0)
