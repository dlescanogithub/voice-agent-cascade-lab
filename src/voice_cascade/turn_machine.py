"""Turn-taking state machine shared by every VAD backend.

Echo handling is a correlation heuristic on the lab's synthetic channels.
It is not acoustic echo cancellation.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from voice_cascade.pcm import SAMPLE_RATE, WINDOW_MS, WINDOW_SAMPLES
from voice_cascade.vad_backend import VadBackend

ECHO_CORR_EST = 0.6
ECHO_LAG_MS_EST = 120


@dataclass(frozen=True)
class TurnProfile:
    name: str
    on_threshold: float
    off_threshold: float
    min_speech_ms: int
    end_silence_ms: int
    barge_min_ms: int
    cancel_bound_ms: int = 300
    echo_corr: float = ECHO_CORR_EST
    echo_lag_ms: int = ECHO_LAG_MS_EST


TURN_PROFILES: dict[str, TurnProfile] = {
    "aggressive": TurnProfile("aggressive", 0.40, 0.25, 64, 192, 96),
    "balanced": TurnProfile("balanced", 0.50, 0.35, 128, 416, 192),
    "patient": TurnProfile("patient", 0.60, 0.45, 224, 800, 288),
}


def get_turn_profile(name: str) -> TurnProfile:
    try:
        return TURN_PROFILES[name]
    except KeyError as exc:
        known = ", ".join(TURN_PROFILES)
        raise KeyError(f"unknown turn profile {name!r}; expected one of {known}") from exc


def pearson(left: Sequence[int], right: Sequence[int]) -> float:
    n = len(left)
    if n == 0 or n != len(right):
        return 0.0
    mean_left = sum(left) / n
    mean_right = sum(right) / n
    numer = 0.0
    var_left = 0.0
    var_right = 0.0
    for a, b in zip(left, right, strict=True):
        da = a - mean_left
        db = b - mean_right
        numer += da * db
        var_left += da * da
        var_right += db * db
    if var_left <= 0.0 or var_right <= 0.0:
        return 0.0
    return numer / math.sqrt(var_left * var_right)


@dataclass
class TurnMachine:
    profile: TurnProfile
    backend: VadBackend
    assistant_text: str = ""
    playback_ms: int = 640
    echo_guard: bool = True
    state: str = "Listening"
    now_ms: int = 0
    speech_ms: int = 0
    silence_ms: int = 0
    barge_ms: int = 0
    played_ms: int = 0
    t_endpoint: int | None = None
    t_tts_first: int | None = None
    t_tts_stopped: int | None = None
    cancelled: bool = False
    cancel_cause: str = ""
    llm_cancelled: bool = False
    tts_stopped: bool = False
    draft_discarded: bool = False
    pending_tool: bool = True
    tool_cancelled: bool = False
    tool_sent: bool = False
    history: str = ""
    backchannels: int = 0
    echo_windows: int = 0
    events: list[dict[str, object]] = field(default_factory=list)
    _agent_hist: list[int] = field(default_factory=list)

    def reset(self) -> None:
        self.backend.reset()
        self.state = "Listening"
        self.now_ms = 0
        self.speech_ms = 0
        self.silence_ms = 0
        self.barge_ms = 0
        self.played_ms = 0
        self.t_endpoint = None
        self.t_tts_first = None
        self.t_tts_stopped = None
        self.cancelled = False
        self.cancel_cause = ""
        self.llm_cancelled = False
        self.tts_stopped = False
        self.draft_discarded = False
        self.pending_tool = True
        self.tool_cancelled = False
        self.tool_sent = False
        self.history = ""
        self.backchannels = 0
        self.echo_windows = 0
        self.events = []
        self._agent_hist = []

    def mark_tool_sent(self) -> None:
        self.tool_sent = True
        self.pending_tool = False

    def note_tts_first_byte(self) -> None:
        if self.state != "Thinking":
            return
        self.state = "Speaking"
        self.t_tts_first = self.now_ms
        self.events.append({"event": "tts_first_byte", "t_ms": self.now_ms})

    def push_window(self, mic: Sequence[int], agent: Sequence[int]) -> None:
        if len(mic) != WINDOW_SAMPLES or len(agent) != WINDOW_SAMPLES:
            raise ValueError("windows must be 512 samples")
        self._agent_hist.extend(agent)
        if len(self._agent_hist) > 8192:
            self._agent_hist = self._agent_hist[-8192:]
        prob = self.backend.speech_prob(mic)
        echo = False
        if self.echo_guard and self.state in {"Speaking", "BargeCandidate"} and self._is_echo(mic):
            echo = True
            self.echo_windows += 1
            self.events.append({"event": "echo_ignored", "t_ms": self.now_ms})
        self._step(prob, echo)
        if self.state == "Speaking":
            self.played_ms += WINDOW_MS
            self._sync_history()
        self.now_ms += WINDOW_MS

    def expected_played_text(self) -> str:
        if self.draft_discarded or not self.assistant_text or self.playback_ms <= 0:
            return ""
        fraction = min(1.0, self.played_ms / self.playback_ms)
        count = int(len(self.assistant_text) * fraction)
        return self.assistant_text[:count]

    def history_matches_playback(self) -> bool:
        return self.history == self.expected_played_text()

    def _sync_history(self) -> None:
        self.history = self.expected_played_text()

    def _is_echo(self, mic: Sequence[int]) -> bool:
        if not any(mic):
            return False
        lag_max = SAMPLE_RATE * self.profile.echo_lag_ms // 1000
        hist = self._agent_hist
        width = len(mic)
        best = 0.0
        for lag in range(0, lag_max + 1, 160):
            end = len(hist) - lag
            start = end - width
            if start < 0:
                break
            score = pearson(mic, hist[start:end])
            if score > best:
                best = score
        return best >= self.profile.echo_corr

    def _step(self, prob: float, echo: bool) -> None:
        heard = prob >= self.profile.on_threshold
        held = prob >= self.profile.off_threshold
        if self.state == "Listening":
            if heard:
                self.speech_ms += WINDOW_MS
                if self.speech_ms >= self.profile.min_speech_ms:
                    self.state = "UserSpeaking"
                    self.silence_ms = 0
            else:
                self.speech_ms = 0
            return
        if self.state == "UserSpeaking":
            if held:
                self.silence_ms = 0
                self.speech_ms += WINDOW_MS
            else:
                self.state = "Endpointing"
                self.silence_ms = WINDOW_MS
                self._check_endpoint()
            return
        if self.state == "Endpointing":
            if heard:
                self.state = "UserSpeaking"
                self.silence_ms = 0
                self.speech_ms += WINDOW_MS
            else:
                self.silence_ms += WINDOW_MS
                self._check_endpoint()
            return
        if self.state == "Thinking":
            if heard:
                self.speech_ms += WINDOW_MS
                if self.speech_ms >= self.profile.min_speech_ms:
                    self._discard_draft()
            else:
                self.speech_ms = 0
            return
        if self.state == "Speaking":
            if echo or not heard:
                self.barge_ms = 0
                return
            self.state = "BargeCandidate"
            self.barge_ms = WINDOW_MS
            self._check_barge()
            return
        if self.state == "BargeCandidate":
            if echo:
                self.barge_ms = 0
                self.state = "Speaking"
                return
            if held:
                self.barge_ms += WINDOW_MS
                self._check_barge()
                return
            self.backchannels += 1
            self.events.append(
                {"event": "backchannel_ignored", "t_ms": self.now_ms, "run_ms": self.barge_ms}
            )
            self.barge_ms = 0
            self.state = "Speaking"

    def _check_endpoint(self) -> None:
        if self.silence_ms >= self.profile.end_silence_ms:
            self.state = "Thinking"
            self.t_endpoint = self.now_ms + WINDOW_MS
            self.speech_ms = 0
            self.events.append({"event": "endpoint", "t_ms": self.t_endpoint})

    def _check_barge(self) -> None:
        if self.barge_ms >= self.profile.barge_min_ms:
            self._cancel("speech")

    def _discard_draft(self) -> None:
        self.draft_discarded = True
        self.llm_cancelled = True
        if self.pending_tool and not self.tool_sent:
            self.tool_cancelled = True
            self.pending_tool = False
        self.assistant_text = ""
        self.history = ""
        self.state = "UserSpeaking"
        self.silence_ms = 0
        self.events.append({"event": "draft_discarded", "t_ms": self.now_ms + WINDOW_MS})

    def _cancel(self, cause: str) -> None:
        self.cancelled = True
        self.cancel_cause = cause
        self.tts_stopped = True
        self.llm_cancelled = True
        if self.pending_tool and not self.tool_sent:
            self.tool_cancelled = True
            self.pending_tool = False
        self.t_tts_stopped = self.now_ms + WINDOW_MS
        self._sync_history()
        self.state = "UserSpeaking"
        self.silence_ms = 0
        self.speech_ms = self.barge_ms
        self.events.append({"event": "cancelled", "cause": cause, "t_ms": self.t_tts_stopped})
