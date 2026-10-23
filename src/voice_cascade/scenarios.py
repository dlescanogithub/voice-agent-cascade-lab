"""Scripted synthetic calls for Aurora Clinic. No real callers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Cohort = Literal["latency", "quality", "robustness"]
Intent = Literal["book", "find", "cancel", "clinical", "unclear"]

NAMES = (
    "Nube Quillay",
    "Tilo Bruma",
    "Vera Lumen",
    "Ciro Pampero",
    "Luma Quena",
    "Suri Alerce",
    "Pino Yungay",
    "Ona Chilca",
)

# The first two words must already carry the intent. The aggressive profile
# endpoints on the internal pause and only hears that prefix.
_BODIES: dict[str, str] = {
    "book": "I want a general consultation appointment",
    "find": "Available times for a general consultation",
    "cancel": "Cancel the reserved appointment please",
    "clinical": "Head hurts and I have a fever what medicine should I take",
    "unclear": "Uh this is a microphone test",
}


def phone_for(index: int) -> str:
    return f"+549110000{index:04d}"


def utterance_for(intent: str, name: str) -> str:
    return f"{_BODIES[intent]} this is {name}"


@dataclass(frozen=True)
class Scenario:
    id: str
    cohort: Cohort
    intent: Intent
    utterance: str
    patient_name: str
    phone: str
    patient_ref: str
    slot_id: str
    date: str
    booking_id: str
    wer: float
    internal_pause_ms: int
    noise_ms: int
    barge_in_ms: int
    allowed_outcomes: tuple[str, ...]
    fault_tool: str | None = None
    fault_mode: str | None = None
    fault_times: int = 0
    duplicate_submit: bool = False
    conflict_submit: bool = False
    expect_dlq: bool = False
    prebooked: bool = False


def _scenario(
    index: int,
    *,
    cohort: Cohort,
    intent: Intent,
    prefix: str,
    wer: float = 0.0,
    internal_pause_ms: int = 0,
    noise_ms: int = 0,
    barge_in_ms: int = 0,
    allowed: tuple[str, ...] | None = None,
    fault_tool: str | None = None,
    fault_mode: str | None = None,
    fault_times: int = 0,
    duplicate_submit: bool = False,
    conflict_submit: bool = False,
    expect_dlq: bool = False,
) -> Scenario:
    name = NAMES[index % len(NAMES)]
    scenario_id = f"{prefix}{index:02d}"
    if allowed is None:
        default = {
            "book": ("booked",),
            "find": ("slots_offered",),
            "cancel": ("cancelled",),
            "clinical": ("escalated",),
            "unclear": ("escalated",),
        }[intent]
        allowed = default
    return Scenario(
        id=scenario_id,
        cohort=cohort,
        intent=intent,
        utterance=utterance_for(intent, name),
        patient_name=name,
        phone=phone_for(index),
        patient_ref=f"pat-{scenario_id.lower()}",
        slot_id=f"slot-{scenario_id.lower()}",
        date="2026-11-03",
        booking_id=f"bk-seed-{scenario_id.lower()}",
        wer=wer,
        internal_pause_ms=internal_pause_ms,
        noise_ms=noise_ms,
        barge_in_ms=barge_in_ms,
        allowed_outcomes=allowed,
        fault_tool=fault_tool,
        fault_mode=fault_mode,
        fault_times=fault_times,
        duplicate_submit=duplicate_submit,
        conflict_submit=conflict_submit,
        expect_dlq=expect_dlq,
        prebooked=intent == "cancel",
    )


def build_scenarios() -> list[Scenario]:
    """49 scripted conversations.

    Latency cohort (36) is the budget sample. Mix, all with zero injected ASR error:
    15 book, 6 find, 6 cancel, 6 clinical, 3 unclear.
    Flags inside that cohort: 6 noise bursts, 4 long barge-ins, 4 short barge-ins,
    4 long internal pauses.
    Quality cohort (8) injects word errors. Robustness cohort (5) drives the webhook.
    """
    scenarios: list[Scenario] = []
    # L01-L15 books. L01-L06 noise, L07-L10 barge-in 250 ms.
    for number in range(1, 16):
        scenarios.append(
            _scenario(
                number,
                cohort="latency",
                intent="book",
                prefix="L",
                noise_ms=100 if number <= 6 else 0,
                barge_in_ms=250 if 7 <= number <= 10 else 0,
            )
        )
    # L16-L21 finds. L16-L19 short barge-in.
    for number in range(16, 22):
        scenarios.append(
            _scenario(
                number,
                cohort="latency",
                intent="find",
                prefix="L",
                barge_in_ms=80 if number <= 19 else 0,
            )
        )
    # L22-L27 cancels. L22-L25 internal pause 300 ms.
    for number in range(22, 28):
        scenarios.append(
            _scenario(
                number,
                cohort="latency",
                intent="cancel",
                prefix="L",
                internal_pause_ms=300 if number <= 25 else 0,
            )
        )
    for number in range(28, 34):
        scenarios.append(_scenario(number, cohort="latency", intent="clinical", prefix="L"))
    for number in range(34, 37):
        scenarios.append(_scenario(number, cohort="latency", intent="unclear", prefix="L"))
    for number in range(1, 7):
        scenarios.append(
            _scenario(
                number,
                cohort="quality",
                intent="book",
                prefix="Q",
                wer=0.35,
                allowed=("booked", "escalated"),
            )
        )
    for number in range(7, 9):
        scenarios.append(
            _scenario(
                number,
                cohort="quality",
                intent="clinical",
                prefix="Q",
                wer=0.2,
                allowed=("escalated",),
            )
        )
    scenarios.append(
        _scenario(1, cohort="robustness", intent="book", prefix="R", duplicate_submit=True)
    )
    scenarios.append(
        _scenario(
            2,
            cohort="robustness",
            intent="book",
            prefix="R",
            conflict_submit=True,
            allowed=("escalated",),
        )
    )
    scenarios.append(
        _scenario(
            3,
            cohort="robustness",
            intent="book",
            prefix="R",
            fault_tool="book_appointment",
            fault_mode="http_500",
            fault_times=2,
        )
    )
    scenarios.append(
        _scenario(
            4,
            cohort="robustness",
            intent="book",
            prefix="R",
            fault_tool="book_appointment",
            fault_mode="timeout_before_commit",
            fault_times=5,
            allowed=("escalated",),
            expect_dlq=True,
        )
    )
    scenarios.append(
        _scenario(
            5,
            cohort="robustness",
            intent="book",
            prefix="R",
            fault_tool="book_appointment",
            fault_mode="slow_after_commit",
            fault_times=1,
        )
    )
    return scenarios
