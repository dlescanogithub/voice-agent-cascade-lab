"""Run one synthetic clip through the turn-taking machine.

Timings here are computed on synthetic PCM. They are SIMULATED. They are not
a measurement of a caller, a provider, or a telephone.
"""

from __future__ import annotations

from dataclasses import dataclass

from voice_cascade.pcm import SAMPLE_RATE, WINDOW_SAMPLES, split_windows
from voice_cascade.synth_audio import SynthClip
from voice_cascade.turn_machine import TurnMachine, TurnProfile
from voice_cascade.vad_backend import EnergyVadBackend

ASSISTANT_TEXT = "Done. The booking is waiting for the system to confirm."
PLAYBACK_MS = 640


@dataclass(frozen=True)
class TurnObservation:
    endpoint_delay_ms: int
    reaction_ms: int | None
    premature: bool
    has_internal_pause: bool
    true_barge: bool
    barge_cancelled: bool
    distractor: bool
    false_cancel: bool
    history_ok: bool
    cancelled: bool
    backchannels: int
    echo_windows: int
    state: str
    t_endpoint: int | None
    t_tts_stopped: int | None


def _user_end(clip: SynthClip) -> int:
    for region in clip.regions:
        if region.label not in {"speech", "pause", "silence"}:
            return region.start
    return len(clip.mic)


def run_clip(
    clip: SynthClip,
    profile: TurnProfile,
    *,
    echo_guard: bool = True,
) -> TurnObservation:
    machine = TurnMachine(
        profile=profile,
        backend=EnergyVadBackend(),
        assistant_text=ASSISTANT_TEXT,
        playback_ms=PLAYBACK_MS,
        echo_guard=echo_guard,
    )
    mic_windows = split_windows(clip.mic)
    agent_windows = split_windows(clip.agent_out)
    user_windows = _user_end(clip) // WINDOW_SAMPLES
    for mic, agent in zip(mic_windows[:user_windows], agent_windows[:user_windows], strict=True):
        machine.push_window(mic, agent)
    if machine.state == "Thinking":
        machine.note_tts_first_byte()
    for mic, agent in zip(mic_windows[user_windows:], agent_windows[user_windows:], strict=True):
        if machine.cancelled:
            break
        machine.push_window(mic, agent)
        if machine.cancelled:
            break
    if machine.state == "Speaking":
        machine.state = "Listening"
        machine.events.append({"event": "playback_done", "t_ms": machine.now_ms})
        machine._sync_history()

    speech_end_ms = clip.speech_end * 1000 // SAMPLE_RATE
    endpoint = machine.t_endpoint if machine.t_endpoint is not None else speech_end_ms
    delay = endpoint - speech_end_ms
    premature = False
    if machine.t_endpoint is not None:
        for start, end in clip.pause_spans:
            start_ms = start * 1000 // SAMPLE_RATE
            end_ms = end * 1000 // SAMPLE_RATE
            if start_ms <= machine.t_endpoint < end_ms:
                premature = True
    event = str(clip.condition.get("agent_event", "none"))
    true_barge = event == "barge"
    distractor = event in {"noise", "echo", "backchannel"}
    reaction: int | None = None
    if true_barge and machine.t_tts_stopped is not None and clip.barge_onset is not None:
        onset_ms = clip.barge_onset * 1000 // SAMPLE_RATE
        reaction = machine.t_tts_stopped - onset_ms
    return TurnObservation(
        endpoint_delay_ms=delay,
        reaction_ms=reaction,
        premature=premature,
        has_internal_pause=bool(clip.pause_spans),
        true_barge=true_barge,
        barge_cancelled=true_barge and machine.cancelled,
        distractor=distractor,
        false_cancel=machine.cancelled and distractor,
        history_ok=machine.history_matches_playback(),
        cancelled=machine.cancelled,
        backchannels=machine.backchannels,
        echo_windows=machine.echo_windows,
        state=machine.state,
        t_endpoint=machine.t_endpoint,
        t_tts_stopped=machine.t_tts_stopped,
    )
