"""One simulated call: VAD, STT, cassette LLM, webhook tools, TTS, barge-in."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from voice_cascade.audio import barge_speech, noise_burst, scripted_utterance
from voice_cascade.booking import BookingStore
from voice_cascade.clock import SimulatedClock
from voice_cascade.config import Settings
from voice_cascade.latency import LatencySampler
from voice_cascade.llm import (
    SAFE_DLQ,
    SAFE_SLOT,
    apply_clinical_guard,
    plan_for,
)
from voice_cascade.logging_setup import ListHandler, log_event
from voice_cascade.pii import add_sensitive, reset_denylist
from voice_cascade.scenarios import Scenario
from voice_cascade.stt import transcribe
from voice_cascade.trace import append_trace, read_traces
from voice_cascade.tts import Playback, cancel, synthesize
from voice_cascade.vad import InterruptDecision, VadProfile, detect_interrupt, endpoint, get_profile
from voice_cascade.webhook import (
    SERVICE,
    FaultPlan,
    InProcessTransport,
    JsonlDeadLetterQueue,
    WebhookApp,
    WebhookClient,
)


@dataclass
class ScenarioRun:
    scenario_id: str
    cohort: str
    intent: str
    classified_intent: str
    outcome: str
    assistant_text: str
    transcript: str
    spans: dict[str, int]
    premature: bool
    cancelled: bool
    false_cut: bool
    cancel_latency_ms: int | None
    missed_eligible: bool
    expect_dlq: bool
    call_id: str
    noise_ms: int
    barge_in_ms: int
    internal_pause_ms: int
    tool_names: list[str] = field(default_factory=list)


@dataclass
class SuiteResult:
    runs: list[ScenarioRun]
    active_bookings: dict[str, int]
    dlq_records: list[dict[str, object]]
    log_text: str
    trace_text: str
    profile: str
    regression: bool


def _envelope(
    scenario: Scenario,
    tool: str,
    *,
    key_suffix: str = "",
    patient_ref: str | None = None,
) -> dict[str, object]:
    if tool == "find_slots":
        args: dict[str, object] = {"date": scenario.date, "service": SERVICE}
    elif tool == "book_appointment":
        args = {
            "slot_id": scenario.slot_id,
            "patient_ref": patient_ref or scenario.patient_ref,
        }
    elif tool == "cancel_appointment":
        args = {"booking_id": scenario.booking_id}
    else:
        args = {}
    return {
        "tool": tool,
        "args": args,
        "idempotency_key": f"{scenario.id}:{tool}:{scenario.slot_id}{key_suffix}",
        "call_id": scenario.id,
    }


def _outcome(classified: str, results: list[dict[str, object]]) -> str:
    if classified in {"clinical", "unclear"}:
        return "escalated"
    if any(item.get("error") == "dead_lettered" for item in results):
        return "escalated"
    if classified == "book":
        books = [item for item in results if item.get("tool") == "book_appointment"]
        if books and books[-1].get("ok") is True:
            return "booked"
        return "escalated"
    if classified == "find":
        if any(item.get("tool") == "find_slots" and item.get("ok") is True for item in results):
            return "slots_offered"
        return "escalated"
    if classified == "cancel":
        if any(
            item.get("tool") == "cancel_appointment" and item.get("ok") is True for item in results
        ):
            return "cancelled"
        return "escalated"
    return "escalated"


def _assistant_text(plan_text: str, results: list[dict[str, object]]) -> str:
    if any(item.get("error") == "dead_lettered" for item in results):
        return SAFE_DLQ
    books = [item for item in results if item.get("tool") == "book_appointment"]
    if books and books[-1].get("error") == "slot_unavailable":
        return SAFE_SLOT
    return plan_text


def _apply_playback_events(
    playback: Playback,
    scenario: Scenario,
    profile: VadProfile,
) -> tuple[bool, bool, int | None, bool]:
    noise = (
        detect_interrupt(noise_burst(scenario.noise_ms), profile)
        if scenario.noise_ms
        else InterruptDecision(False, False, 0)
    )
    speech = (
        detect_interrupt(barge_speech(scenario.barge_in_ms), profile)
        if scenario.barge_in_ms
        else InterruptDecision(False, False, 0)
    )
    cancelled = False
    false_cut = False
    latency: int | None = None
    if noise.triggered:
        cancel(playback, noise.latency_ms, false_cut=True)
        cancelled = True
        false_cut = True
        latency = noise.latency_ms
    if speech.triggered:
        cancel(playback, speech.latency_ms, false_cut=False)
        cancelled = True
        false_cut = False
        latency = speech.latency_ms
    eligible = scenario.barge_in_ms >= profile.min_speech_ms and scenario.barge_in_ms > 0
    missed = eligible and not speech.triggered
    return cancelled, false_cut, latency, missed


def run_suite(
    scenarios: list[Scenario],
    *,
    data_dir: Path,
    settings: Settings,
    profile_name: str = "balanced",
    regression: bool = False,
) -> SuiteResult:
    profile = get_profile(profile_name)
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "clinic.sqlite"
    if db_path.exists():
        db_path.unlink()
    trace_path = data_dir / "trace.jsonl"
    if trace_path.exists():
        trace_path.unlink()
    reset_denylist()
    for scenario in scenarios:
        add_sensitive([scenario.patient_name, scenario.phone])

    logger = logging.getLogger("voice_cascade.turn")
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = ListHandler()
    logger.addHandler(handler)

    store = BookingStore(db_path)
    dlq = JsonlDeadLetterQueue(data_dir / "dlq.jsonl")
    # A previous file in this directory should not leak into the run.
    dlq.replace_all([])
    app = WebhookApp(store, settings.hmac_secret)
    transport = InProcessTransport(app)
    runs: list[ScenarioRun] = []
    try:
        for scenario in scenarios:
            runs.append(
                _run_scenario(
                    scenario,
                    store=store,
                    transport=transport,
                    dlq=dlq,
                    settings=settings,
                    profile=profile,
                    logger=logger,
                    trace_path=trace_path,
                    regression=regression,
                )
            )
        active = store.active_counts()
        records = dlq.read_all()
    finally:
        store.close()
    trace_text = trace_path.read_text(encoding="utf-8") if trace_path.exists() else ""
    return SuiteResult(
        runs=runs,
        active_bookings=active,
        dlq_records=records,
        log_text="\n".join(handler.lines),
        trace_text=trace_text,
        profile=profile.name,
        regression=regression,
    )


def _run_scenario(
    scenario: Scenario,
    *,
    store: BookingStore,
    transport: InProcessTransport,
    dlq: JsonlDeadLetterQueue,
    settings: Settings,
    profile: VadProfile,
    logger: logging.Logger,
    trace_path: Path,
    regression: bool,
) -> ScenarioRun:
    clock = SimulatedClock()
    sampler = LatencySampler(settings.seed, scenario.id, settings.latency_law())
    store.ensure_slot(scenario.slot_id, scenario.date, SERVICE)
    if scenario.prebooked:
        store.seed_booking(
            scenario.slot_id,
            scenario.date,
            SERVICE,
            scenario.patient_ref,
            scenario.booking_id,
        )
    heard = endpoint(scripted_utterance(scenario.utterance, scenario.internal_pause_ms), profile)
    # The endpoint decision stays on the profile thresholds. The clock charge is a
    # seeded draw whose median is that profile's end-silence. [EST] sigma.
    vad_ms = sampler.draw("vad", median_ms=float(profile.end_silence_ms))
    clock.advance(vad_ms)
    stt = transcribe(heard.words, seed=settings.seed, scenario_id=scenario.id, wer=scenario.wer)
    stt_ms = sampler.draw("stt")
    clock.advance(stt_ms)
    plan = apply_clinical_guard(
        plan_for(stt.text, regression=regression),
        enabled=not settings.disable_clinical_guard and not regression,
    )
    llm_ms = sampler.draw("llm")
    clock.advance(llm_ms)
    fault = None
    if scenario.fault_mode and scenario.fault_tool:
        fault = FaultPlan(scenario.fault_tool, scenario.fault_mode, scenario.fault_times)

    def elapsed_for(payload: dict[str, object]) -> int:
        if payload.get("idempotent_replay") is True:
            return sampler.draw("replay")
        return sampler.draw("tool")

    client = WebhookClient(transport, clock, dlq, settings, elapsed_for=elapsed_for)
    before_tools = clock.now_ms
    results: list[dict[str, object]] = []
    for tool in plan.tools:
        results.append(client.invoke(_envelope(scenario, tool), fault))
    if scenario.duplicate_submit:
        results.append(client.invoke(_envelope(scenario, "book_appointment"), fault))
    if scenario.conflict_submit:
        results.append(
            client.invoke(
                _envelope(
                    scenario,
                    "book_appointment",
                    key_suffix=":conflict",
                    patient_ref=f"{scenario.patient_ref}-b",
                ),
                fault,
            )
        )
    tool_ms = clock.now_ms - before_tools
    text = _assistant_text(plan.text, results)
    playback = synthesize(text)
    tts_ms = sampler.draw("tts")
    clock.advance(tts_ms)
    cancelled, false_cut, cancel_latency, missed = _apply_playback_events(
        playback, scenario, profile
    )
    outcome = _outcome(plan.intent, results)
    spans = {
        "vad_endpoint_ms": vad_ms,
        "stt_final_ms": stt_ms,
        "llm_ttft_ms": llm_ms,
        "tool_webhook_ms": tool_ms,
        "tts_ttfb_ms": tts_ms,
    }
    spans["e2e_ms"] = sum(spans.values())
    log_event(
        logger,
        "turn_complete",
        "turn complete",
        {
            "scenario_id": scenario.id,
            "patient_name": scenario.patient_name,
            "phone": scenario.phone,
            "transcript": stt.text,
            "outcome": outcome,
            "assistant_text": text,
        },
    )
    record: dict[str, object] = {
        "scenario_id": scenario.id,
        "patient_name": scenario.patient_name,
        "phone": scenario.phone,
        "transcript": stt.text,
        "assistant_text": text,
        "outcome": outcome,
        "partials": len(stt.partials),
        "spans": spans,
        "false_cut": false_cut,
        "cancelled": cancelled,
    }
    append_trace(trace_path, record)
    return ScenarioRun(
        scenario_id=scenario.id,
        cohort=scenario.cohort,
        intent=scenario.intent,
        classified_intent=plan.intent,
        outcome=outcome,
        assistant_text=text,
        transcript=stt.text,
        spans=spans,
        premature=heard.premature,
        cancelled=cancelled,
        false_cut=false_cut,
        cancel_latency_ms=cancel_latency,
        missed_eligible=missed,
        expect_dlq=scenario.expect_dlq,
        call_id=scenario.id,
        noise_ms=scenario.noise_ms,
        barge_in_ms=scenario.barge_in_ms,
        internal_pause_ms=scenario.internal_pause_ms,
        tool_names=[str(item.get("tool", "")) for item in results],
    )


def load_trace_text(path: Path) -> str:
    rows = read_traces(path)
    return "\n".join(str(row) for row in rows)
