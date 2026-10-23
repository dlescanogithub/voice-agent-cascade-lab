"""Fake streaming STT. Errors are injected; nothing is recognized from audio."""

from __future__ import annotations

import random
import unicodedata
from dataclasses import dataclass

from voice_cascade.budget import STT_FINAL_MS, STT_PARTIAL_MS

SUBSTITUTIONS = {
    "book": "bok",
    "appointment": "apointment",
    "cancel": "cansel",
    "available": "availabe",
    "consultation": "consultaton",
    "want": "wnt",
    "fever": "fevor",
    "medicine": "medcine",
    "hurts": "hurst",
}


def fold(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


@dataclass(frozen=True)
class SttResult:
    partials: list[str]
    text: str
    final_ms: int
    partial_ms_each: int


def transcribe(words: list[str], *, seed: int, scenario_id: str, wer: float) -> SttResult:
    rng = random.Random(f"{seed}:{scenario_id}:stt")
    emitted: list[str] = []
    for word in words:
        folded = fold(word)
        if wer > 0 and rng.random() < wer:
            emitted.append(SUBSTITUTIONS.get(folded, "xxxx"))
        else:
            emitted.append(folded)
    partials: list[str] = []
    running: list[str] = []
    for word in emitted:
        running.append(word)
        partials.append(" ".join(running))
    return SttResult(
        partials=partials,
        text=" ".join(emitted),
        final_ms=STT_FINAL_MS,
        partial_ms_each=STT_PARTIAL_MS,
    )
