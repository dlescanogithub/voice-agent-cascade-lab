# ADR 0004: Clinical guard before TTS

## Status

Accepted. 2026-10-17.

## Context

Clínica Aurora schedules. A caller who describes a symptom must not receive a dose, a drug name, or a diagnosis from the assistant. A cassette can be edited later by mistake. A prompt-only rule will not hold once a real model is swapped in.

## Decision

`contains_clinical_advice` scans the assistant text. If the guard is on, the text is replaced with a fixed escalation and the tool list is cleared before any webhook or TTS. The safe cassette is also free of those markers, so the guard is a backstop. The regression cassette sentence is used only when `eval-regression` turns the guard off.

User text may contain symptom words. Those words classify the intent as clinical. They are not themselves a failure. The failure is the assistant repeating advice.

## Consequences

The marker list is small and will miss paraphrases. It is a gate, not a clinical safety case. A real pilot needs a reviewed phrase list and a person on the escalation path.

## Alternatives

- Rely on the cassette wording alone. Rejected. The regression would have nothing to break.
- Classify with a second model. Out of scope, and it would be another vendor call.
