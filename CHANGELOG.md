# Changelog

## [0.1.1] - 2026-10-17

- SIMULATED clock charges are seeded lognormal draws with [EST] parameters, so p50 and p95 differ and the budget gate can fail.
- Optional `python -m voice_cascade live` measures wall-clock time-to-first-byte and total time. Off unless `LIVE_MODE=1`. Exits 2 with no request when config or the spend cap fails. Not part of CI.
- Secret scanner covers the shared key shapes. `docs/PROVENANCE.md` records the vendored file's sha256.

## [0.1.0] - 2026-10-17

- Offline STT → LLM → TTS cascade with a simulated clock and fake providers.
- Three VAD profiles, barge-in metrics, and a 49-conversation synthetic script for Clínica Aurora.
- Local webhook tools with HMAC, idempotency, bounded retries, and a JSONL dead-letter queue.
- Invariant eval gate and a forced regression that must fail.
