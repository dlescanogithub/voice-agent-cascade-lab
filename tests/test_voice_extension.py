"""Offline voice extension. No provider, no socket, no model download."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from voice_cascade.cli import main
from voice_cascade.config import Settings
from voice_cascade.cost_estimate import dry_run_plan
from voice_cascade.fault_cohort import run_fault_cohort
from voice_cascade.metrics import assert_uniform_provenance
from voice_cascade.pcm import read_pcm_wav, samples_for_ms, write_pcm_wav
from voice_cascade.synth_audio import render_turn
from voice_cascade.turn_machine import TurnMachine, get_turn_profile
from voice_cascade.turn_session import run_clip
from voice_cascade.vad_backend import EnergyVadBackend, SileroUnavailable, load_silero
from voice_cascade.voice_cohort import FALSE_BARGE_MAX, run_cohort
from voice_cascade.voice_report import render_markdown
from voice_cascade.webhook import (
    SIMULATED_UNIX_S,
    classify_http,
    delay_for,
    sign,
    sign_v2,
)


class ScriptedBackend:
    name = "scripted"

    def __init__(self, probs: list[float]) -> None:
        self.probs = probs
        self.index = 0

    def reset(self) -> None:
        self.index = 0

    def speech_prob(self, window: Sequence[int]) -> float:
        del window
        value = self.probs[self.index]
        self.index += 1
        return value


def _zeros() -> list[int]:
    return [0] * 512


def test_sidecar_bounds_match_samples() -> None:
    clip = render_turn(seed=7, pause_ms=224, agent_event="barge", trailing_silence_ms=416)
    assert len(clip.mic) == len(clip.agent_out)
    assert len(clip.mic) % 512 == 0
    assert clip.regions[0].start == 0
    assert clip.regions[0].label == "speech"
    speech = clip.mic[clip.regions[0].start : clip.regions[0].end]
    assert any(sample != 0 for sample in speech)
    pause = next(region for region in clip.regions if region.label == "pause")
    assert clip.mic[pause.start : pause.end] == [0] * (pause.end - pause.start)
    assert clip.speech_end == pause.end + (clip.regions[2].end - clip.regions[2].start)
    assert clip.barge_onset is not None
    sidecar = clip.sidecar()
    assert sidecar["provenance"] == "SIMULATED"
    committed = json.loads(Path("tests/fixtures/dsp_window.json").read_text(encoding="utf-8"))
    again = render_turn(seed=7, pause_ms=224, agent_event="none", trailing_silence_ms=416)
    assert again.mic[:512] == committed["samples"]


def test_wav_roundtrip(tmp_path: Path) -> None:
    clip = render_turn(seed=3, pause_ms=256, trailing_silence_ms=416)
    path = tmp_path / "clip.wav"
    write_pcm_wav(path, clip.mic[:512])
    samples, rate = read_pcm_wav(path)
    assert rate == 16000
    assert samples == clip.mic[:512]
    with pytest.raises(ValueError):
        samples_for_ms(10)


def test_energy_backend_is_binary_and_rejects_short_windows() -> None:
    backend = EnergyVadBackend()
    speech = render_turn(seed=1, pause_ms=256, trailing_silence_ms=416).mic[:512]
    assert backend.speech_prob(speech) == 1.0
    assert backend.speech_prob([0] * 512) == 0.0
    with pytest.raises(ValueError):
        backend.speech_prob([1, 2, 3])


def test_hysteresis_holds_between_thresholds() -> None:
    profile = get_turn_profile("balanced")
    backend = ScriptedBackend([1.0, 1.0, 1.0, 1.0, 0.40, 0.40, 0.0])
    machine = TurnMachine(profile, backend, assistant_text="hola")
    for _ in range(4):
        machine.push_window(_zeros(), _zeros())
    assert machine.state == "UserSpeaking"
    machine.push_window(_zeros(), _zeros())
    machine.push_window(_zeros(), _zeros())
    assert machine.state == "UserSpeaking"
    machine.push_window(_zeros(), _zeros())
    assert machine.state == "Endpointing"


def test_thinking_discards_draft_and_unsent_tool() -> None:
    profile = get_turn_profile("balanced")
    speech = [1.0] * 4
    silence = [0.0] * 13
    more = [1.0] * 4
    machine = TurnMachine(
        profile,
        ScriptedBackend(speech + silence + more),
        assistant_text="abcdefghij",
        playback_ms=640,
    )
    for _ in range(17):
        machine.push_window(_zeros(), _zeros())
    assert machine.state == "Thinking"
    for _ in range(4):
        machine.push_window(_zeros(), _zeros())
    assert machine.draft_discarded is True
    assert machine.llm_cancelled is True
    assert machine.tool_cancelled is True
    assert machine.history == ""
    assert machine.t_tts_first is None
    assert machine.history_matches_playback()


def test_played_text_tracks_playback_and_sent_tool_stays() -> None:
    profile = get_turn_profile("balanced")
    speech = [1.0] * 4
    silence = [0.0] * 13
    quiet = [0.0] * 10
    machine = TurnMachine(
        profile,
        ScriptedBackend(speech + silence + quiet),
        assistant_text="abcdefghij",
        playback_ms=640,
    )
    for _ in range(17):
        machine.push_window(_zeros(), _zeros())
    machine.mark_tool_sent()
    machine.note_tts_first_byte()
    assert machine.state == "Speaking"
    for _ in range(10):
        machine.push_window(_zeros(), _zeros())
    assert machine.history == "abcde"
    assert machine.history_matches_playback()
    assert machine.tool_sent is True
    assert machine.tool_cancelled is False


def test_echo_guard_and_barge_reaction_on_dsp() -> None:
    profile = get_turn_profile("balanced")
    echo = render_turn(seed=4, pause_ms=320, agent_event="echo", trailing_silence_ms=416)
    heard = run_clip(echo, profile, echo_guard=True)
    assert heard.false_cancel is False
    assert heard.echo_windows > 0
    assert heard.history_ok is True
    exposed = run_clip(echo, profile, echo_guard=False)
    assert exposed.false_cancel is True
    barge = render_turn(seed=4, pause_ms=320, agent_event="barge", trailing_silence_ms=416)
    cut = run_clip(barge, profile, echo_guard=True)
    assert cut.barge_cancelled is True
    assert cut.reaction_ms is not None
    assert cut.reaction_ms <= profile.cancel_bound_ms
    assert cut.history_ok is True
    back = render_turn(seed=4, pause_ms=320, agent_event="backchannel", trailing_silence_ms=416)
    ignored = run_clip(back, profile, echo_guard=True)
    assert ignored.cancelled is False
    assert ignored.backchannels == 1


def test_small_cohort_meets_estimated_gates() -> None:
    report = run_cohort(seed=42, n_calls=6, profile_name="balanced")
    assert report.passed, report.failures
    assert report.n_turns == 24
    rates = [item.false_cancel for item in report.observations if item.distractor]
    assert (sum(rates) / len(rates) if rates else 0) <= FALSE_BARGE_MAX


def test_mixed_provenance_is_rejected() -> None:
    assert_uniform_provenance([{"provenance": "SIMULATED"}, {"provenance": "SIMULATED"}])
    with pytest.raises(ValueError, match="mixed"):
        assert_uniform_provenance([{"provenance": "SIMULATED"}, {"provenance": "MEASURED"}])


def test_silero_stays_off_without_a_download() -> None:
    with pytest.raises(SileroUnavailable, match="off by default"):
        load_silero({})
    with pytest.raises(SileroUnavailable, match="does not download"):
        load_silero({"VOICE_CASCADE_ENABLE_SILERO": "1"})


def test_full_jitter_property() -> None:
    for index in range(1000):
        attempt = index % 6
        delay = delay_for(attempt, seed=42, key=f"k{index}", base=40, cap=500, jitter=20)
        bound = min(500, 40 * (1 << attempt))
        assert 0 <= delay <= bound
    assert delay_for(3, seed=1, key="stable", base=40, cap=500, jitter=0) == 320


def test_retry_classification_table() -> None:
    assert classify_http(500, {"error": "down"}) == ("http_5xx", True)
    assert classify_http(503, {"retry_after_s": 2}) == ("throttled", True)
    assert classify_http(429, {}) == ("throttled", True)
    assert classify_http(400, {"error": "bad_json"}) == ("poison_payload", False)
    assert classify_http(400, {"error": "bad_args"}) == ("poison_payload", False)
    assert classify_http(400, {"error": "missing_idempotency_key"}) == ("poison_payload", False)
    assert classify_http(401, {"error": "stale_timestamp"}) == ("auth_failed", False)
    assert classify_http(401, {"error": "bad_signature"}) == ("auth_failed", False)
    assert classify_http(409, {"error": "slot_unavailable"}) == ("slot_unavailable", False)
    assert classify_http(200, {"ok": True}) == ("ok", False)


def test_signature_v2_window_and_v1_flag(tmp_path: Path) -> None:
    from voice_cascade.booking import BookingStore
    from voice_cascade.webhook import WebhookApp

    store = BookingStore(tmp_path / "clinic.sqlite")
    secret = "test-only-hmac-secret"
    previous = "test-only-previous-secret"
    body = sign_body = json.dumps(
        {"args": {}, "idempotency_key": "find-edge", "tool": "find_slots"},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    fresh = WebhookApp(store, secret, previous_secret=previous, now_s=lambda: SIMULATED_UNIX_S)
    edge = sign_v2(secret, body, SIMULATED_UNIX_S - 300)
    status, payload = fresh.handle(body, {"X-Voice-Signature": edge})
    assert status == 200, payload
    stale = sign_v2(secret, body, SIMULATED_UNIX_S - 301)
    status, payload = fresh.handle(body, {"X-Voice-Signature": stale})
    assert status == 401
    assert payload["error"] == "stale_timestamp"
    rotated = sign_v2(previous, body, SIMULATED_UNIX_S)
    status, payload = fresh.handle(body, {"X-Voice-Signature": rotated})
    assert status == 200
    v1 = sign(secret, sign_body)
    status, _payload = fresh.handle(body, {"X-Voice-Signature": v1})
    assert status == 200
    closed = WebhookApp(store, secret, accept_v1=False, now_s=lambda: SIMULATED_UNIX_S)
    status, payload = closed.handle(body, {"X-Voice-Signature": v1})
    assert status == 401
    assert payload["error"] == "bad_signature"
    store.close()


def test_fault_cohort_and_log_fields(tmp_path: Path) -> None:
    settings = Settings(jitter_ms=0, tool_deadline_ms=1500, hmac_secret="test-only-hmac-secret")
    cases = run_fault_cohort(tmp_path, settings)
    assert [case.case_id for case in cases] == [f"W{index:02d}" for index in range(1, 13)]
    assert all(case.passed for case in cases), cases
    log_text = (tmp_path / "fault.log").read_text(encoding="utf-8")
    assert "test-only-hmac-secret" not in log_text
    assert '"call_id"' in log_text
    assert '"turn_id"' in log_text
    assert "sha256:" in log_text


def test_markdown_labels_simulated_only() -> None:
    cohort = run_cohort(seed=1, n_calls=2)
    text = render_markdown(cohort, [], decisions_note="D1-D5 remain open.")
    assert "SIMULATED" in text
    assert "MEASURED" not in text
    assert "/home/" not in text
    assert "/workspace" not in text


def test_dry_run_prints_estimate_and_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def explode(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise AssertionError("dry-run must not call the live client")

    monkeypatch.setattr("voice_cascade.cli.run_live", explode)
    monkeypatch.delenv("MAX_LIVE_SPEND_USD", raising=False)
    assert main(["live", "--dry-run"]) == 2
    monkeypatch.setenv("MAX_LIVE_SPEND_USD", "10")
    assert main(["live", "--dry-run"]) == 0
    captured = capsys.readouterr().out
    assert "[EST]" in captured
    assert "request_sent=False" in captured
    assert "No request was sent." in captured
    plan = dry_run_plan(0.0)
    assert plan["over_cap"] is True
    assert plan["request_sent"] is False


def test_cli_regressions_synth_and_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("VOICE_CASCADE_DATA_DIR", str(tmp_path / "data"))
    assert main(["eval-regression", "--turn-taking"]) == 1
    assert main(["eval-regression", "--webhook"]) == 1
    out = tmp_path / "synth"
    assert main(["synth-audio", "--calls", "1", "--out", str(out), "--seed", "3"]) == 0
    assert list(out.glob("*.json"))
    assert main(["trace", "--turn", "missing", "--log", str(tmp_path / "nope.log")]) == 1
    log = tmp_path / "tool.log"
    log.write_text(
        json.dumps(
            {
                "event": "tool.attempt.failed",
                "call_id": "w01",
                "turn_id": "w01:t01",
                "error_class": "timeout",
                "attempt": 1,
                "provenance": "SIMULATED",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert main(["trace", "--turn", "w01:t01", "--log", str(log)]) == 0
    printed = capsys.readouterr().out
    assert "w01:t01" in printed
    assert "timeout" in printed
