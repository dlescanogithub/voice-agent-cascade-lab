"""Provider seams. Fakes are the default. Real adapters are stubs and never send traffic."""

from __future__ import annotations

from typing import Protocol

from voice_cascade.config import Settings
from voice_cascade.stt import SttResult
from voice_cascade.tts import Playback


class RealProviderError(RuntimeError):
    """Raised before any network call. The stub has no HTTP client."""


class SpeechToText(Protocol):
    def transcribe(self, words: list[str], *, seed: int, scenario_id: str, wer: float) -> SttResult:
        """Return a transcript for already-tokenized synthetic speech."""


class SpeechSynth(Protocol):
    def synthesize(self, text: str) -> Playback:
        """Return playback chunks for assistant text."""


def _refuse(enabled: bool, key: str, env_flag: str, env_key: str, role: str) -> None:
    if not enabled:
        raise RealProviderError(
            f"Real {role} adapter is off. Set {env_flag}=1 to inspect the stub. No request was sent."
        )
    if not key:
        raise RealProviderError(f"{env_key} is missing. No request was sent.")
    raise RealProviderError(
        f"Real {role} adapter is a stub with no HTTP client. "
        "No vendor was called. Measured with real providers: none yet."
    )


def build_real_stt(settings: Settings) -> None:
    _refuse(
        settings.enable_real_stt,
        settings.stt_api_key,
        "VOICE_CASCADE_ENABLE_REAL_STT",
        "VOICE_CASCADE_STT_API_KEY",
        "STT",
    )


def build_real_llm(settings: Settings) -> None:
    _refuse(
        settings.enable_real_llm,
        settings.llm_api_key,
        "VOICE_CASCADE_ENABLE_REAL_LLM",
        "VOICE_CASCADE_LLM_API_KEY",
        "LLM",
    )


def build_real_tts(settings: Settings) -> None:
    _refuse(
        settings.enable_real_tts,
        settings.tts_api_key,
        "VOICE_CASCADE_ENABLE_REAL_TTS",
        "VOICE_CASCADE_TTS_API_KEY",
        "TTS",
    )
