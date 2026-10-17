"""Simulated stage times and the operating budget.

Every duration here is simulated. The harness advances SimulatedClock by these
constants. It does not measure wall-clock time.
"""

from __future__ import annotations

from dataclasses import dataclass

STT_PARTIAL_MS = 30
STT_FINAL_MS = 160
LLM_TTFT_MS = 140
TOOL_SUCCESS_MS = 90
TOOL_REPLAY_MS = 15
TTS_TTFB_MS = 70
TTS_CHUNK_CHARS = 24
TTS_CHUNK_MS = 40
CANCEL_BOUND_MS = 300
NOISE_RMS = 0.35
SPEECH_RMS = 0.8
SILENCE_RMS = 0.02


@dataclass(frozen=True)
class StageBudget:
    vad_endpoint_ms: int = 900
    stt_final_ms: int = 400
    llm_ttft_ms: int = 350
    tool_webhook_ms: int = 800
    tts_ttfb_ms: int = 250
    e2e_ms: int = 2500

    def limit_for(self, stage: str) -> int:
        return {
            "vad_endpoint_ms": self.vad_endpoint_ms,
            "stt_final_ms": self.stt_final_ms,
            "llm_ttft_ms": self.llm_ttft_ms,
            "tool_webhook_ms": self.tool_webhook_ms,
            "tts_ttfb_ms": self.tts_ttfb_ms,
            "e2e_ms": self.e2e_ms,
        }[stage]


DEFAULT_BUDGET = StageBudget()
STAGE_NAMES = (
    "vad_endpoint_ms",
    "stt_final_ms",
    "llm_ttft_ms",
    "tool_webhook_ms",
    "tts_ttfb_ms",
    "e2e_ms",
)
