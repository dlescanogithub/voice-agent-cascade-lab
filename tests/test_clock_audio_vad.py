from __future__ import annotations

from pathlib import Path

import pytest

from voice_cascade.audio import (
    barge_speech,
    load_wav_frames,
    noise_burst,
    scripted_utterance,
    write_silence_wav,
)
from voice_cascade.clock import SimulatedClock
from voice_cascade.vad import detect_interrupt, endpoint, get_profile


def test_clock_advances_and_rejects_negative() -> None:
    clock = SimulatedClock()
    clock.advance(5)
    assert clock.now_ms == 5
    with pytest.raises(ValueError):
        clock.advance(-1)


def test_scripted_pause_splits_after_two_tokens() -> None:
    frames = scripted_utterance("Necesito cancelar el turno reservado", 300)
    assert [frame.kind for frame in frames] == ["speech", "silence", "speech"]
    assert frames[0].text == "Necesito cancelar"
    assert frames[1].duration_ms == 300


def test_short_utterance_stays_one_frame() -> None:
    frames = scripted_utterance("hola", 300)
    assert len(frames) == 1


def test_empty_bursts() -> None:
    assert noise_burst(0) == []
    assert barge_speech(0) == []


def test_wav_silence_loads_as_silence(tmp_path: Path) -> None:
    path = tmp_path / "silence.wav"
    write_silence_wav(path, duration_ms=40)
    frames = load_wav_frames(path, frame_ms=20)
    assert frames
    assert all(frame.kind == "silence" for frame in frames)


def test_wav_rejects_non_pcm16(tmp_path: Path) -> None:
    path = tmp_path / "odd.wav"
    import wave

    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(1)
        handle.setframerate(8000)
        handle.writeframes(b"\x00" * 8)
    with pytest.raises(ValueError):
        load_wav_frames(path)


def test_unknown_profile() -> None:
    with pytest.raises(KeyError):
        get_profile("sleepy")


def test_endpoint_profiles_on_internal_pause() -> None:
    frames = scripted_utterance("Necesito cancelar el turno reservado soy Nube", 300)
    aggressive = endpoint(frames, get_profile("aggressive"))
    balanced = endpoint(frames, get_profile("balanced"))
    patient = endpoint(frames, get_profile("patient"))
    assert aggressive.premature is True
    assert aggressive.words[:2] == ["Necesito", "cancelar"]
    assert balanced.premature is False
    assert "Nube" in balanced.words
    assert patient.premature is False
    assert aggressive.endpoint_ms == 180
    assert balanced.endpoint_ms == 400
    assert patient.endpoint_ms == 800


def test_interrupt_thresholds() -> None:
    noise = noise_burst(100)
    short = barge_speech(80)
    long = barge_speech(250)
    aggressive = get_profile("aggressive")
    balanced = get_profile("balanced")
    patient = get_profile("patient")
    assert detect_interrupt(noise, aggressive).triggered is True
    assert detect_interrupt(noise, aggressive).noise_only is True
    assert detect_interrupt(noise, balanced).triggered is False
    assert detect_interrupt(noise, patient).triggered is False
    assert detect_interrupt(short, aggressive).triggered is True
    assert detect_interrupt(short, balanced).triggered is False
    assert detect_interrupt(long, patient).latency_ms == 220
    assert detect_interrupt([], balanced).triggered is False


def test_activity_resets_on_silence_gap() -> None:
    from voice_cascade.audio import AudioFrame

    frames = [
        AudioFrame("speech", 50, "hola", 0.8),
        AudioFrame("silence", 50, "", 0.02),
        AudioFrame("speech", 50, "chau", 0.8),
    ]
    decision = detect_interrupt(frames, get_profile("aggressive"))
    assert decision.triggered is False
    heard = endpoint(frames, get_profile("aggressive"))
    assert heard.premature is False
    assert heard.words == ["hola", "chau"]
