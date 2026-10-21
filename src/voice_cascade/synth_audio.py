"""Seeded DSP audio for the energy VAD. No microphone and no paid TTS.

Speech is a harmonic stack with syllable-rate amplitude modulation. Noise,
echo, and backchannels are synthetic. Ground-truth regions are exact sample
ranges because every region is concatenated, not detected.
"""

from __future__ import annotations

import json
import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from voice_cascade.pcm import SAMPLE_RATE, WINDOW_MS, samples_for_ms, write_pcm_wav

SPEECH_AMP = 0.55
NOISE_AMP = 0.03
ECHO_GAIN = 0.30
ECHO_LAG_MS = 80


def _tone(n: int, freq_hz: float, amp: float, phase: float = 0.0) -> list[int]:
    if n <= 0:
        return []
    step = freq_hz / SAMPLE_RATE
    cursor = phase
    scale = amp * 32767.0
    samples: list[int] = []
    for index in range(n):
        envelope = 0.70 + 0.30 * math.sin(math.tau * 5.0 * index / SAMPLE_RATE)
        sample = envelope * scale * math.sin(math.tau * cursor)
        harmonic = 0.35 * envelope * scale * math.sin(math.tau * cursor * 2.0)
        samples.append(max(-32767, min(32767, round(sample + harmonic))))
        cursor += step
        if cursor >= 1.0:
            cursor -= 1.0
    return samples


def _silence(n: int) -> list[int]:
    return [0] * n


def _noise(n: int, rng: random.Random, kind: str) -> list[int]:
    if n <= 0:
        return []
    samples: list[int] = []
    leak = 0.0
    for _ in range(n):
        white = rng.uniform(-1.0, 1.0)
        if kind == "pink":
            leak = 0.97 * leak + 0.03 * white
            white = leak * 8.0
        elif kind == "babble":
            white = 0.5 * white
        samples.append(max(-32767, min(32767, round(white * NOISE_AMP * 32767.0))))
    return samples


def _scale(samples: Sequence[int], gain: float) -> list[int]:
    return [max(-32767, min(32767, round(sample * gain))) for sample in samples]


@dataclass(frozen=True)
class Region:
    label: str
    intended: str
    start: int
    end: int

    def as_dict(self) -> dict[str, object]:
        return {
            "label": self.label,
            "intended": self.intended,
            "start": self.start,
            "end": self.end,
        }


@dataclass
class SynthClip:
    mic: list[int]
    agent_out: list[int]
    regions: list[Region]
    speech_end: int
    barge_onset: int | None
    pause_spans: list[tuple[int, int]] = field(default_factory=list)
    condition: dict[str, object] = field(default_factory=dict)

    def sidecar(self) -> dict[str, object]:
        return {
            "sample_rate": SAMPLE_RATE,
            "window_ms": WINDOW_MS,
            "speech_end": self.speech_end,
            "barge_onset": self.barge_onset,
            "regions": [region.as_dict() for region in self.regions],
            "condition": self.condition,
            "provenance": "SIMULATED",
        }


def _append(
    buffer: list[int], samples: Sequence[int], regions: list[Region], label: str, intended: str
) -> None:
    start = len(buffer)
    buffer.extend(samples)
    regions.append(Region(label, intended, start, len(buffer)))


def render_turn(
    *,
    seed: int,
    pause_ms: int,
    noise_kind: str = "white",
    agent_event: str = "none",
    speech_ms: int = 640,
    trailing_silence_ms: int = 416,
) -> SynthClip:
    """One caller utterance plus an agent playback region.

    ``agent_event`` is ``none``, ``noise``, ``echo``, ``backchannel``, or ``barge``.
    Durations are multiples of 32 ms. The pause sits inside the caller utterance
    and is shorter than the balanced end-silence in the gated corpus.
    """

    rng = random.Random(seed)
    user: list[int] = []
    regions: list[Region] = []
    left = samples_for_ms(speech_ms // 2)
    right = samples_for_ms(speech_ms - speech_ms // 2)
    pause_n = samples_for_ms(pause_ms)
    _append(user, _tone(left, 140.0, SPEECH_AMP), regions, "speech", "speech")
    pause_start = len(user)
    _append(user, _silence(pause_n), regions, "pause", "pause")
    pause_end = len(user)
    _append(user, _tone(right, 180.0, SPEECH_AMP, phase=0.2), regions, "speech", "turn_end")
    speech_end = len(user)
    _append(user, _silence(samples_for_ms(trailing_silence_ms)), regions, "silence", "turn_end")

    agent_ms = 640
    agent_n = samples_for_ms(agent_ms)
    agent_tone = _tone(agent_n, 110.0, SPEECH_AMP, phase=0.4)
    agent_user = _silence(len(user))
    mic_agent: list[int] = []
    agent_regions_base = len(user)
    barge_onset: int | None = None

    if agent_event == "none":
        mic_agent = _silence(agent_n)
        regions.append(
            Region("agent_silence", "playback", agent_regions_base, agent_regions_base + agent_n)
        )
    elif agent_event == "noise":
        mic_agent = _noise(agent_n, rng, noise_kind)
        regions.append(Region("noise", "noise", agent_regions_base, agent_regions_base + agent_n))
    elif agent_event == "echo":
        lag = SAMPLE_RATE * ECHO_LAG_MS // 1000
        delayed = _silence(lag) + _scale(agent_tone, ECHO_GAIN)
        mic_agent = delayed[:agent_n]
        if len(mic_agent) < agent_n:
            mic_agent.extend(_silence(agent_n - len(mic_agent)))
        regions.append(Region("echo", "echo", agent_regions_base, agent_regions_base + agent_n))
    elif agent_event == "backchannel":
        burst = samples_for_ms(64)
        mic_agent = _tone(burst, 200.0, SPEECH_AMP) + _silence(agent_n - burst)
        regions.append(
            Region("backchannel", "backchannel", agent_regions_base, agent_regions_base + burst)
        )
    elif agent_event == "barge":
        onset = samples_for_ms(128)
        burst = samples_for_ms(320)
        mic_agent = (
            _silence(onset) + _tone(burst, 210.0, SPEECH_AMP) + _silence(agent_n - onset - burst)
        )
        barge_onset = agent_regions_base + onset
        regions.append(Region("barge_in", "barge_in", barge_onset, barge_onset + burst))
    else:
        raise ValueError(f"unknown agent_event {agent_event!r}")

    mic = user + mic_agent
    agent_out = agent_user + agent_tone
    if len(agent_out) != len(mic):
        raise RuntimeError("mic and agent_out length mismatch")
    return SynthClip(
        mic=mic,
        agent_out=agent_out,
        regions=regions,
        speech_end=speech_end,
        barge_onset=barge_onset,
        pause_spans=[(pause_start, pause_end)],
        condition={
            "pause_ms": pause_ms,
            "noise_kind": noise_kind,
            "agent_event": agent_event,
            "speech_ms": speech_ms,
            "echo_lag_ms": ECHO_LAG_MS if agent_event == "echo" else 0,
            "echo_gain": ECHO_GAIN if agent_event == "echo" else 0.0,
            "provenance": "SIMULATED",
        },
    )


@dataclass(frozen=True)
class CallDraw:
    call_id: str
    pause_ms: int
    noise_kind: str
    snr_db: int
    events: tuple[str, str, str, str]


PAUSES_MS = (224, 256, 288, 320, 352, 384)
NOISE_KINDS = ("white", "pink", "babble")
SNR_DB = (20, 10, 5)
EVENTS = ("none", "noise", "echo", "backchannel", "barge")


def draw_calls(seed: int, n_calls: int = 100, turns: int = 4) -> list[CallDraw]:
    """Offline default draw. Pauses stay under the balanced end-silence (416 ms).

    The design envelope mentions pauses up to 900 ms. That wider range is not
    the gated corpus: a pause longer than end-silence is an endpoint by the
    profile rule. SNR is recorded as a condition tag. The energy-floor noise
    bed does not rise with the tag. See the report note.
    """

    rng = random.Random(seed)
    calls: list[CallDraw] = []
    for index in range(n_calls):
        events = [rng.choice(EVENTS) for _ in range(turns)]
        if "barge" not in events:
            events[index % turns] = "barge"
        if "echo" not in events:
            events[(index + 1) % turns] = "echo"
        calls.append(
            CallDraw(
                call_id=f"c-{index + 1:04d}",
                pause_ms=rng.choice(PAUSES_MS),
                noise_kind=rng.choice(NOISE_KINDS),
                snr_db=rng.choice(SNR_DB),
                events=(events[0], events[1], events[2], events[3]),
            )
        )
    return calls


def write_clip(path: Path, clip: SynthClip) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_pcm_wav(path.with_suffix(".wav"), clip.mic)
    write_pcm_wav(path.with_name(path.stem + "_agent.wav"), clip.agent_out)
    path.with_suffix(".json").write_text(
        json.dumps(clip.sidecar(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
