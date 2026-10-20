# Changelog

## [Unreleased]

- README opens with a three-line TL;DR under the title and badges.
- Docs only. The SIMULATED eval figures stay p50 896 ms and p95 1004.5 ms. The cited package version is 0.1.9 and the cited git revision is `4fb26ef5a281cc7b325c75c5f6e0f7a96e9a16fa` on main.
- One measured xAI run (2026-10-17/18, repo HEAD `84cfb1a`, n=20, not an SLA) is in the README table "Measured with real providers", with evidence in `docs/live/` and notes in `docs/LIVE_RUN.md`. The scratch adapter is not in the repo. A short English demo and captions are in `docs/demo/`.
- The availability pattern list and the four handwritten recall sets (11/20, 15/20, 14/20, 16/20) are in `docs/HEURISTIC_RECALL.md`. The intervals overlap; those rates are not an improvement. Recall after the latest patterns is not measured yet.
- Vulnerability reports use GitHub private vulnerability reporting. No email address is listed.

## [0.1.9] - 2026-10-17

- `unsupported_availability_claim` also flags "I've blocked" with a day and noon or an appointment, "you're booked" with a day, "have a slot" with a day, and "on the calendar" with a day and a time. Cancellation, reschedule, fasting, and rest phrases stay quiet.
- "ayunar por N horas", "reposo absoluto por N horas", "cada N horas", "fast for N hours", "rest for N hours", and "takes about N hours" stay quiet.
- Handwritten samples from 2026-10-17, each n=20 and separate from these unit tests. Patches were written after seeing earlier misses, so these are not a before/after trial. Set 1: 11/20 (55%, about ±22 points) and 0/20 false positives. Set 2, scored on the 0.1.6 heuristic: 15/20 (75%) and 1/20 false positives. Set 3, scored on the 0.1.7 heuristic: 14/20 (70%) and 1/20 false positives. Set 4, scored on the 0.1.8 heuristic: 16/20 (80%, about ±18 points) and 0/20 false positives. Four different lists, small n, overlapping intervals: 55%, 75%, 70%, and 80% are not an improvement over one another. Recall after this change is not measured yet.

## [0.1.8] - 2026-10-17

- `unsupported_availability_claim` ignores "reposo por N horas", "reposo absoluto por N horas", "reposo durante N horas", and "N horas de reposo" ("guardá reposo por 24 horas"). "reposo de N horas" and fasting instructions stay quiet. "las 15 horas" is still a clock time.
- The check also flags "reservé"/"reservaste" next to a day or "cita", "fit you in" next to a day or "noon", "appointment is confirmed" next to a date, "scheduled your", "holding a spot for you", and "I've reserved". Cancellation, reschedule, and fasting phrases stay quiet.
- Handwritten samples from 2026-10-17, each n=20 and separate from these unit tests. Set 1: 11/20 (55%, about ±22 points) and 0/20 false positives. Set 2, scored on the 0.1.6 heuristic: 15/20 (75%) and 1/20 false positives. Set 3, scored on the 0.1.7 heuristic: 14/20 (70%) and 1/20 false positives. Three different lists, small n, overlapping intervals: 55%, 75%, and 70% are not an improvement over one another. An earlier set, measured before the patterns in pull request 7, was 14/20 claims and 1/18 clean sentences. Recall after this change is not measured yet.

## [0.1.7] - 2026-10-17

- `unsupported_availability_claim` ignores a medical duration or instruction ("requiere ayuno de 8 horas", "ayunar durante 8 horas", "en ayunas", "8 horas de ayuno", "reposo de 8 horas", "dura 8 horas", "an 8 hour fast"). "las 15 horas" is still a clock time. The same sentence can still flag when a separate clock time remains.
- The check also flags "quedaste con" next to a day, "we can see you" next to a day, "free slot" next to a day, "put you down", and "opening" next to an ordinal or "half past". Cancellation and reschedule policies stay quiet.
- Handwritten samples from 2026-10-17, each n=20 and separate from these unit tests. Set 1: 11/20 (55%, about ±22 points) and 0/20 false positives. Set 2, scored on the 0.1.6 heuristic: 15/20 (75%) and 1/20 false positives. The lists differ, n is small, and the intervals overlap, so 75% is not an improvement over 55%. An earlier set, measured before the patterns in pull request 7, was 14/20 claims and 1/18 clean sentences. Recall after this change is not measured yet.

## [0.1.6] - 2026-10-17

- `unsupported_availability_claim` also flags "hueco"/"cupo", "te puedo meter", "te confirmo el turno", "está libre" next to a day, "appointment open", "slots are available on the 12th", "I've scheduled you", and "Tuesday afternoon is open". Cancellation policies stay quiet.
- Recall on handwritten samples from 2026-10-17, not on these unit tests: an earlier set, measured before the patterns in pull request 7, was 14/20 claims and 1/18 clean sentences. A later set of unseen phrases was 11/20 (about 55%, about ±22 points at n=20) and 0/20 clean sentences. Recall after this expansion is not measured yet.

## [0.1.5] - 2026-10-17

- `unsupported_availability_claim` also flags "quedás anotado", "te recibe" with a relative day, "disponibilidad" with a time reference, "nos vemos el viernes 23", "there's availability", "I booked you in", and "for the 5th". A cancellation policy ("hasta 24 horas antes", "up to 24 hours before") is not a slot. The 14/20 figure cited with this release is an earlier handwritten set, measured before these patterns, not a later unseen set.

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
