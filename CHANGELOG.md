# Changelog

## [0.1.5] - 2026-10-17

- `unsupported_availability_claim` also flags "quedás anotado", "te recibe" with a relative day, "disponibilidad" with a time reference, "nos vemos el viernes 23", "there's availability", "I booked you in", and "for the 5th". A cancellation policy ("hasta 24 horas antes", "up to 24 hours before") is not a slot. On 2026-10-17 a handwritten sample of new phrases caught 14 of 20 claims and 1 of 18 clean sentences, before these patterns. That recall was not remeasured.

## [0.1.4] - 2026-10-17

- `unsupported_availability_claim` also flags a calendar date ("el 20 de octubre", "el 22", `dd/mm`), a confirmation ("agendé", "agendada", "te reservé", "confirmado"), and an English slot ("opening", "book you", "available", "3 pm", "10am", "Tuesday"). A negation ("no puedo", "no tengo", "I can't", "we don't have") or a general office range ("de lunes a viernes") does not count. False negatives and false positives remain possible.
- `provider_reported_usd` is omitted unless `usage.cost_in_usd_ticks` is an integer tick count (1 tick = 1e-10 USD). A tokens×price figure, `usage.cost`, or a dollar amount copied into that field stays in `estimated_usd` only. The rollup reads the raw tick count, not a pre-filled dollar field.

## [0.1.3] - 2026-10-17

- `unsupported_availability_claim` is a wider heuristic: clock times, "N hs", "N horas", "a las N", Spanish hour words, and a weekday or "hoy"/"mañana" together with an offer. It fires only when that turn did not call a calendar or availability tool. It can miss a paraphrase and does not replace a human review.
- `cost.estimated_usd` is tokens times the env price (`cost_basis`: `tokens_x_price, cached tokens priced separately`). `provider_reported_usd` is written only when the response includes `usage.cost_in_usd_ticks` (1 tick = 1e-10 USD).

## [0.1.2] - 2026-10-17

- Live results label each stage `real` or `stub`. The title `Measured with real providers` is used only when speech, language, and synthesis are all real. Stub timings stay out of the end-to-end summary.
- Samples smaller than 20 report min, max, and n. They do not report p50 or p95.
- Live mode records token counts, a token estimate, and provider-reported cost when `usage` includes them. The estimate ignores cached tokens unless the response reports them and a cached price is set.
- A reply that invents clock times or says "tengo disponible" without a calendar tool fails `unsupported_availability_claim`.

## [0.1.1] - 2026-10-17

- SIMULATED clock charges are seeded lognormal draws with [EST] parameters, so p50 and p95 differ and the budget gate can fail.
- Optional `python -m voice_cascade live` measures wall-clock time-to-first-byte and total time. Off unless `LIVE_MODE=1`. Exits 2 with no request when config or the spend cap fails. Not part of CI.
- Secret scanner covers the shared key shapes. `docs/PROVENANCE.md` records the vendored file's sha256.

## [0.1.0] - 2026-10-17

- Offline STT → LLM → TTS cascade with a simulated clock and fake providers.
- Three VAD profiles, barge-in metrics, and a 49-conversation synthetic script for Clínica Aurora.
- Local webhook tools with HMAC, idempotency, bounded retries, and a JSONL dead-letter queue.
- Invariant eval gate and a forced regression that must fail.
