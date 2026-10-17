"""Environment-only settings. This module does not read .env files."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from voice_cascade.latency import (
    LLM_MEDIAN_MS,
    LLM_SIGMA,
    REPLAY_MEDIAN_MS,
    REPLAY_SIGMA,
    STT_MEDIAN_MS,
    STT_SIGMA,
    TOOL_MEDIAN_MS,
    TOOL_SIGMA,
    TTS_MEDIAN_MS,
    TTS_SIGMA,
    VAD_SIGMA,
    LatencyLaw,
)

DEMO_HMAC_SECRET = "local-demo-not-a-secret"


def _as_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    return int(raw)


def _as_bool_flag(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "0") == "1"


def _as_float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    return float(raw)


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
    # [EST] Simulated-clock law. Not a provider measurement.
    stt_median_ms: float = STT_MEDIAN_MS
    stt_sigma: float = STT_SIGMA
    llm_median_ms: float = LLM_MEDIAN_MS
    llm_sigma: float = LLM_SIGMA
    tts_median_ms: float = TTS_MEDIAN_MS
    tts_sigma: float = TTS_SIGMA
    tool_median_ms: float = TOOL_MEDIAN_MS
    tool_sigma: float = TOOL_SIGMA
    replay_median_ms: float = REPLAY_MEDIAN_MS
    replay_sigma: float = REPLAY_SIGMA
    vad_sigma: float = VAD_SIGMA

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
            stt_median_ms=_as_float(source, "VOICE_CASCADE_STT_MEDIAN_MS", STT_MEDIAN_MS),
            stt_sigma=_as_float(source, "VOICE_CASCADE_STT_SIGMA", STT_SIGMA),
            llm_median_ms=_as_float(source, "VOICE_CASCADE_LLM_MEDIAN_MS", LLM_MEDIAN_MS),
            llm_sigma=_as_float(source, "VOICE_CASCADE_LLM_SIGMA", LLM_SIGMA),
            tts_median_ms=_as_float(source, "VOICE_CASCADE_TTS_MEDIAN_MS", TTS_MEDIAN_MS),
            tts_sigma=_as_float(source, "VOICE_CASCADE_TTS_SIGMA", TTS_SIGMA),
            tool_median_ms=_as_float(source, "VOICE_CASCADE_TOOL_MEDIAN_MS", TOOL_MEDIAN_MS),
            tool_sigma=_as_float(source, "VOICE_CASCADE_TOOL_SIGMA", TOOL_SIGMA),
            replay_median_ms=_as_float(source, "VOICE_CASCADE_REPLAY_MEDIAN_MS", REPLAY_MEDIAN_MS),
            replay_sigma=_as_float(source, "VOICE_CASCADE_REPLAY_SIGMA", REPLAY_SIGMA),
            vad_sigma=_as_float(source, "VOICE_CASCADE_VAD_SIGMA", VAD_SIGMA),
        )

    def latency_law(self) -> LatencyLaw:
        return LatencyLaw(
            stt_median_ms=self.stt_median_ms,
            stt_sigma=self.stt_sigma,
            llm_median_ms=self.llm_median_ms,
            llm_sigma=self.llm_sigma,
            tts_median_ms=self.tts_median_ms,
            tts_sigma=self.tts_sigma,
            tool_median_ms=self.tool_median_ms,
            tool_sigma=self.tool_sigma,
            replay_median_ms=self.replay_median_ms,
            replay_sigma=self.replay_sigma,
            vad_sigma=self.vad_sigma,
        )
