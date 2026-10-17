"""Environment-only settings. This module does not read .env files."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

DEMO_HMAC_SECRET = "local-demo-not-a-secret"


def _as_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _as_bool_flag(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "0") == "1"


@dataclass(frozen=True)
class Settings:
    seed: int = 42
    hmac_secret: str = DEMO_HMAC_SECRET
    hmac_is_demo_default: bool = True
    max_attempts: int = 3
    backoff_base_ms: int = 40
    backoff_cap_ms: int = 500
    jitter_ms: int = 20
    timeout_ms: int = 300
    log_level: str = "INFO"
    disable_clinical_guard: bool = False
    enable_real_stt: bool = False
    enable_real_llm: bool = False
    enable_real_tts: bool = False
    stt_api_key: str = ""
    llm_api_key: str = ""
    tts_api_key: str = ""
    data_dir: str = "./var"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        source = os.environ if env is None else env
        secret = source.get("VOICE_CASCADE_HMAC_SECRET", "")
        demo = secret == ""
        return cls(
            seed=_as_int(source, "VOICE_CASCADE_SEED", 42),
            hmac_secret=DEMO_HMAC_SECRET if demo else secret,
            hmac_is_demo_default=demo,
            max_attempts=_as_int(source, "VOICE_CASCADE_MAX_ATTEMPTS", 3),
            backoff_base_ms=_as_int(source, "VOICE_CASCADE_BACKOFF_BASE_MS", 40),
            backoff_cap_ms=_as_int(source, "VOICE_CASCADE_BACKOFF_CAP_MS", 500),
            jitter_ms=_as_int(source, "VOICE_CASCADE_JITTER_MS", 20),
            timeout_ms=_as_int(source, "VOICE_CASCADE_TIMEOUT_MS", 300),
            log_level=source.get("VOICE_CASCADE_LOG_LEVEL", "INFO"),
            disable_clinical_guard=_as_bool_flag(source, "VOICE_CASCADE_DISABLE_CLINICAL_GUARD"),
            enable_real_stt=_as_bool_flag(source, "VOICE_CASCADE_ENABLE_REAL_STT"),
            enable_real_llm=_as_bool_flag(source, "VOICE_CASCADE_ENABLE_REAL_LLM"),
            enable_real_tts=_as_bool_flag(source, "VOICE_CASCADE_ENABLE_REAL_TTS"),
            stt_api_key=source.get("VOICE_CASCADE_STT_API_KEY", ""),
            llm_api_key=source.get("VOICE_CASCADE_LLM_API_KEY", ""),
            tts_api_key=source.get("VOICE_CASCADE_TTS_API_KEY", ""),
            data_dir=source.get("VOICE_CASCADE_DATA_DIR", "./var"),
        )
