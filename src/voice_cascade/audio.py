"""Synthetic audio. Frames are timed tokens, not microphone samples."""

from __future__ import annotations

import re
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from voice_cascade.budget import NOISE_RMS, SILENCE_RMS, SPEECH_RMS

FrameKind = Literal["speech", "silence", "noise"]
WORD_RE = re.compile(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ']+")


@dataclass(frozen=True)
class AudioFrame:
    kind: FrameKind
    duration_ms: int
    text: str = ""
    rms: float = 0.0


def words_of(text: str) -> list[str]:
    return WORD_RE.findall(text)


def scripted_utterance(text: str, internal_pause_ms: int) -> list[AudioFrame]:
    tokens = words_of(text)
    if internal_pause_ms <= 0 or len(tokens) < 4:
        return [AudioFrame("speech", 240, " ".join(tokens), SPEECH_RMS)]
    left = " ".join(tokens[:2])
    right = " ".join(tokens[2:])
    return [
        AudioFrame("speech", 180, left, SPEECH_RMS),
        AudioFrame("silence", internal_pause_ms, "", SILENCE_RMS),
        AudioFrame("speech", 220, right, SPEECH_RMS),
    ]


def noise_burst(duration_ms: int) -> list[AudioFrame]:
    if duration_ms <= 0:
        return []
    return [AudioFrame("noise", duration_ms, "", NOISE_RMS)]


def barge_speech(duration_ms: int) -> list[AudioFrame]:
    if duration_ms <= 0:
        return []
    return [AudioFrame("speech", duration_ms, "perdon", SPEECH_RMS)]


def write_silence_wav(path: Path, duration_ms: int = 20, sample_rate: int = 8000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    n_samples = int(sample_rate * duration_ms / 1000)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * n_samples)


def load_wav_frames(path: Path, frame_ms: int = 20) -> list[AudioFrame]:
    """Map a WAV to energy frames. The committed fixture is silence."""
    with wave.open(str(path), "r") as handle:
        sample_rate = handle.getframerate()
        width = handle.getsampwidth()
        count = handle.getnframes()
        raw = handle.readframes(count)
    if width != 2:
        raise ValueError("only 16-bit PCM is supported")
    samples = [
        int.from_bytes(raw[index : index + 2], "little", signed=True)
        for index in range(0, len(raw), 2)
    ]
    frame_len = max(1, int(sample_rate * frame_ms / 1000))
    frames: list[AudioFrame] = []
    for start in range(0, len(samples), frame_len):
        chunk = samples[start : start + frame_len]
        if not chunk:
            continue
        mean_abs = sum(abs(sample) for sample in chunk) / len(chunk)
        rms = mean_abs / 32768
        kind: FrameKind = "speech" if rms >= 0.2 else "silence"
        frames.append(AudioFrame(kind, frame_ms, "", rms))
    return frames
