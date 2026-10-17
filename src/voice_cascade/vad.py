"""Energy VAD with three named turn-taking profiles. No neural model."""

from __future__ import annotations

from dataclasses import dataclass

from voice_cascade.audio import AudioFrame, words_of
from voice_cascade.budget import NOISE_RMS


@dataclass(frozen=True)
class VadProfile:
    name: str
    min_speech_ms: int
    end_silence_ms: int
    speech_threshold: float


PROFILES: dict[str, VadProfile] = {
    "aggressive": VadProfile(
        "aggressive", min_speech_ms=60, end_silence_ms=180, speech_threshold=0.30
    ),
    "balanced": VadProfile(
        "balanced", min_speech_ms=120, end_silence_ms=400, speech_threshold=0.50
    ),
    "patient": VadProfile("patient", min_speech_ms=220, end_silence_ms=800, speech_threshold=0.55),
}


def get_profile(name: str) -> VadProfile:
    try:
        return PROFILES[name]
    except KeyError as exc:
        known = ", ".join(PROFILES)
        raise KeyError(f"unknown VAD profile {name!r}; expected one of {known}") from exc


def is_activity(frame: AudioFrame, profile: VadProfile) -> bool:
    if frame.kind == "silence":
        return False
    return frame.rms >= profile.speech_threshold


@dataclass(frozen=True)
class EndpointResult:
    words: list[str]
    premature: bool
    endpoint_ms: int


def endpoint(frames: list[AudioFrame], profile: VadProfile) -> EndpointResult:
    words: list[str] = []
    speech_ms = 0
    silence_run = 0
    armed = False
    premature = False
    for index, frame in enumerate(frames):
        if is_activity(frame, profile):
            silence_run = 0
            speech_ms += frame.duration_ms
            words.extend(words_of(frame.text))
            if speech_ms >= profile.min_speech_ms:
                armed = True
            continue
        if armed:
            silence_run += frame.duration_ms
            if silence_run >= profile.end_silence_ms:
                rest = frames[index + 1 :]
                premature = any(is_activity(item, profile) for item in rest)
                break
    return EndpointResult(words=words, premature=premature, endpoint_ms=profile.end_silence_ms)


@dataclass(frozen=True)
class InterruptDecision:
    triggered: bool
    noise_only: bool
    latency_ms: int


def detect_interrupt(frames: list[AudioFrame], profile: VadProfile) -> InterruptDecision:
    run_ms = 0
    kinds: list[str] = []
    for frame in frames:
        if is_activity(frame, profile):
            run_ms += frame.duration_ms
            kinds.append(frame.kind)
            if run_ms >= profile.min_speech_ms:
                noise_only = all(kind == "noise" for kind in kinds) or (
                    profile.speech_threshold <= NOISE_RMS and "speech" not in kinds
                )
                return InterruptDecision(True, noise_only, profile.min_speech_ms)
        else:
            run_ms = 0
            kinds = []
    return InterruptDecision(False, False, 0)
