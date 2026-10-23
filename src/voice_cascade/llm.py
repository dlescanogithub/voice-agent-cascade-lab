"""Cassette LLM. Intent is a keyword fold, then a fixed tool plan. Not a model."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from voice_cascade.budget import LLM_TTFT_MS
from voice_cascade.stt import fold

CASSETTE_PATH = Path(__file__).with_name("cassettes") / "clinic.json"
SAFE_CLINICAL = (
    "I can't help with a health question. I'm transferring you to someone on the scheduling team."
)
SAFE_UNCLEAR = "I didn't catch the request. I'm transferring you to someone on the scheduling team."
SAFE_SLOT = (
    "That time is no longer open. I'm transferring you to the scheduling team to find another."
)
SAFE_DLQ = (
    "I couldn't confirm the request because of a system problem. "
    "I'm transferring you to a person. No new booking was saved."
)

_ADVICE_PHRASES = (
    "ibuprofen",
    "acetaminophen",
    "antibiotic",
    "i prescribe",
    "dose",
    "take ",
    "likely diagnosis",
)


@dataclass(frozen=True)
class LlmPlan:
    intent: str
    text: str
    tools: tuple[str, ...]
    ttft_ms: int
    guard_replaced: bool


def contains_clinical_advice(text: str) -> bool:
    folded = fold(text)
    if any(phrase in folded for phrase in _ADVICE_PHRASES):
        return True
    return re.search(r"\b\d+\s*mg\b", folded) is not None


def classify(text: str) -> str:
    folded = fold(text)
    clinical_tokens = (
        "hurt",
        "pain",
        "fever",
        "fevor",
        "medicine",
        "medication",
        "symptom",
        "prescription",
        "dose",
        "diagnos",
    )
    if any(token in folded for token in clinical_tokens):
        return "clinical"
    if any(token in folded for token in ("cancel", "cansel")):
        return "cancel"
    if any(token in folded for token in ("book", "bok", "schedul", "reserv", "want")):
        return "book"
    if any(token in folded for token in ("time", "hour", "availab", "opening")):
        return "find"
    return "unclear"


@lru_cache(maxsize=1)
def load_cassette() -> dict[str, dict[str, object]]:
    raw: object = json.loads(CASSETTE_PATH.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("cassette root must be an object")
    parsed: dict[str, dict[str, object]] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            raise ValueError(f"cassette entry {key} must be an object")
        parsed[str(key)] = {str(item_key): item for item_key, item in value.items()}
    return parsed


def _tools(entry: dict[str, object]) -> tuple[str, ...]:
    raw = entry.get("tools", [])
    if not isinstance(raw, list):
        return ()
    return tuple(str(item) for item in raw)


def plan_for(transcript: str, *, regression: bool) -> LlmPlan:
    cassette = load_cassette()
    intent = classify(transcript)
    entry = cassette[intent]
    text = str(entry["text"])
    if regression and intent == "clinical":
        text = str(cassette["regression_clinical"]["text"])
    return LlmPlan(
        intent=intent,
        text=text,
        tools=_tools(entry),
        ttft_ms=LLM_TTFT_MS,
        guard_replaced=False,
    )


def apply_clinical_guard(plan: LlmPlan, *, enabled: bool) -> LlmPlan:
    if not enabled or not contains_clinical_advice(plan.text):
        return plan
    return LlmPlan(
        intent=plan.intent,
        text=SAFE_CLINICAL,
        tools=(),
        ttft_ms=plan.ttft_ms,
        guard_replaced=True,
    )
