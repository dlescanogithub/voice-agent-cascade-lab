"""16 kHz PCM windows for the offline turn-taking lab.

Mono, 16-bit, 32 ms frames (512 samples). This is the audio contract in the
voice extension. It does not read a microphone.
"""

from __future__ import annotations

import math
import wave
from collections.abc import Sequence
from pathlib import Path

SAMPLE_RATE = 16_000
WINDOW_SAMPLES = 512
WINDOW_MS = 32
SAMPLE_SCALE = 32_768


def normalized_rms(window: Sequence[int]) -> float:
    if not window:
        return 0.0
    total = 0.0
    for sample in window:
        total += float(sample) * float(sample)
    return math.sqrt(total / len(window)) / SAMPLE_SCALE


def samples_for_ms(duration_ms: int) -> int:
    if duration_ms < 0:
        raise ValueError("duration_ms must be non-negative")
    if duration_ms % WINDOW_MS != 0:
        raise ValueError("duration_ms must be a multiple of 32")
    return SAMPLE_RATE * duration_ms // 1000


def split_windows(samples: Sequence[int]) -> list[list[int]]:
    if len(samples) % WINDOW_SAMPLES != 0:
        raise ValueError("sample count must be a multiple of 512")
    return [
        list(samples[start : start + WINDOW_SAMPLES])
        for start in range(0, len(samples), WINDOW_SAMPLES)
    ]


def ms_at(sample_index: int) -> int:
    return sample_index * 1000 // SAMPLE_RATE


def write_pcm_wav(path: Path, samples: Sequence[int], sample_rate: int = SAMPLE_RATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = b"".join(int(sample).to_bytes(2, "little", signed=True) for sample in samples)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(frames)


def read_pcm_wav(path: Path) -> tuple[list[int], int]:
    with wave.open(str(path), "r") as handle:
        if handle.getnchannels() != 1 or handle.getsampwidth() != 2:
            raise ValueError("only mono 16-bit PCM is supported")
        sample_rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    samples = [
        int.from_bytes(raw[index : index + 2], "little", signed=True)
        for index in range(0, len(raw), 2)
    ]
    return samples, sample_rate
