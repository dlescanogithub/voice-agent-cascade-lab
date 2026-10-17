# Changelog

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
