from __future__ import annotations

from voice_cascade.budget import LLM_TTFT_MS, STT_FINAL_MS, TTS_TTFB_MS
from voice_cascade.llm import (
    SAFE_CLINICAL,
    apply_clinical_guard,
    classify,
    contains_clinical_advice,
    load_cassette,
    plan_for,
)
from voice_cascade.stt import transcribe
from voice_cascade.tts import cancel, synthesize


def test_stt_partials_and_deterministic_errors() -> None:
    words = ["Quiero", "agendar", "un", "turno"]
    clean = transcribe(words, seed=42, scenario_id="L11", wer=0)
    assert clean.partials[-1] == "quiero agendar un turno"
    assert clean.final_ms == STT_FINAL_MS
    noisy_a = transcribe(words, seed=42, scenario_id="Q01", wer=1)
    noisy_b = transcribe(words, seed=42, scenario_id="Q01", wer=1)
    assert noisy_a.text == noisy_b.text
    assert "xxxx" in noisy_a.text or "ajendar" in noisy_a.text or "torno" in noisy_a.text


def test_classifier_priority() -> None:
    assert classify("Me duele la cabeza y quiero agendar") == "clinical"
    assert classify("Necesito cancelar el turno") == "cancel"
    assert classify("Quiero agendar un turno") == "book"
    assert classify("Hay horarios disponibles") == "find"
    assert classify("eh una prueba de microfono") == "unclear"


def test_cassette_has_no_clinical_advice() -> None:
    cassette = load_cassette()
    for name, entry in cassette.items():
        if name == "regression_clinical":
            assert contains_clinical_advice(str(entry["text"]))
            continue
        assert contains_clinical_advice(str(entry["text"])) is False


def test_guard_replaces_advice_and_can_be_disabled() -> None:
    poisoned = plan_for("me duele la cabeza", regression=True)
    assert contains_clinical_advice(poisoned.text)
    guarded = apply_clinical_guard(poisoned, enabled=True)
    assert guarded.text == SAFE_CLINICAL
    assert guarded.tools == ()
    assert guarded.guard_replaced is True
    open_guard = apply_clinical_guard(poisoned, enabled=False)
    assert contains_clinical_advice(open_guard.text)
    normal = plan_for("Quiero agendar un turno", regression=False)
    assert normal.tools == ("find_slots", "book_appointment")
    assert normal.ttft_ms == LLM_TTFT_MS
    assert apply_clinical_guard(normal, enabled=True).text == normal.text


def test_tts_chunks_and_cancel() -> None:
    playback = synthesize("Listo. El turno quedó reservado para la fecha pedida.")
    assert playback.ttfb_ms == TTS_TTFB_MS
    assert len(playback.chunks) > 1
    cancel(playback, 120, false_cut=False)
    assert playback.cancelled is True
    assert playback.playback_ms == 120
    empty = synthesize("")
    assert empty.chunks == [""]
