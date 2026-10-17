"""Fake TTS. Chunks are text slices plus a simulated time-to-first-byte."""

from __future__ import annotations

from dataclasses import dataclass

from voice_cascade.budget import TTS_CHUNK_CHARS, TTS_CHUNK_MS, TTS_TTFB_MS


@dataclass
class Playback:
    chunks: list[str]
    ttfb_ms: int
    chunk_ms: int
    cancelled: bool = False
    cancel_latency_ms: int | None = None
    false_cut: bool = False

    @property
    def playback_ms(self) -> int:
        if self.cancelled:
            return self.cancel_latency_ms or 0
        return self.chunk_ms * len(self.chunks)


def synthesize(text: str) -> Playback:
    chunks = [
        text[index : index + TTS_CHUNK_CHARS] for index in range(0, len(text), TTS_CHUNK_CHARS)
    ]
    if not chunks:
        chunks = [""]
    return Playback(chunks=chunks, ttfb_ms=TTS_TTFB_MS, chunk_ms=TTS_CHUNK_MS)


def cancel(playback: Playback, latency_ms: int, *, false_cut: bool) -> None:
    playback.cancelled = True
    playback.cancel_latency_ms = latency_ms
    playback.false_cut = false_cut
