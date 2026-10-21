"""VAD backends. The decision layer calls ``speech_prob`` and nothing else.

``energy`` is stdlib RMS and is what CI runs. ``silero`` is an optional marker:
the flag defaults off, and opting in still does not download weights or call
a provider.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Protocol

from voice_cascade.pcm import WINDOW_SAMPLES, normalized_rms

ENERGY_FLOOR = 0.05


class VadBackend(Protocol):
    name: str

    def reset(self) -> None:
        """Clear backend state between calls."""

    def speech_prob(self, window: Sequence[int]) -> float:
        """Probability in [0, 1] for one 512-sample window."""


class EnergyVadBackend:
    """Port of the RMS rule. Output is 0 or 1 against a fixed energy floor.

    Profile thresholds live in the state machine, not here, so a later backend
    can return a real probability without a second decision layer.
    """

    name = "energy"

    def reset(self) -> None:
        return None

    def speech_prob(self, window: Sequence[int]) -> float:
        if len(window) != WINDOW_SAMPLES:
            raise ValueError(f"expected {WINDOW_SAMPLES} samples, got {len(window)}")
        return 1.0 if normalized_rms(window) >= ENERGY_FLOOR else 0.0


class SileroUnavailable(RuntimeError):
    """The optional Silero lane is not active. No model was loaded."""


def load_silero(env: Mapping[str, str] | None = None) -> VadBackend:
    """Return a Silero backend only when explicitly opted in.

    Default is off. Even with the flag, this build does not import torch and
    does not download weights. Decision D4 (whether a CI lane should run it)
    stays open. The manual marker is documented in ``docs/voice/SILERO.md``.
    """

    source = os.environ if env is None else env
    if source.get("VOICE_CASCADE_ENABLE_SILERO", "0") != "1":
        raise SileroUnavailable(
            "Silero VAD is an optional extra and is off by default. "
            "No model is loaded. CI does not run this lane."
        )
    raise SileroUnavailable(
        "Silero VAD was opted in, but this build does not load model weights "
        "and does not download them. The optional lane stays a marker until "
        "D4 is resolved. No network call was made."
    )
