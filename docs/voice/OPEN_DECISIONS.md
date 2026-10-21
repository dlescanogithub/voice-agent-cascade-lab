# Open decisions D1–D5

These are **not resolved**. Each row is the cheapest offline default that lets the lab run with no paid call. The owner can still pick the other side.

| Id | Question | Default used here | Why this default | Still open |
| --- | --- | --- | --- | --- |
| D1 | Live run size: 100×1 turn (L1) or 100×4 turns (L4) | L1 | The dry-run estimate prices one turn per call. No live run is executed. | Yes |
| D2 | Voice-tier fixtures: offline TTS or one cached paid batch | Offline DSP (harmonic stack) | Zero cost, deterministic, no network. Silero is not scored on this audio. | Yes |
| D3 | Provider bundle for a future live run | Bundle D, lowest list in `docs/design/COST_ESTIMATE.md` | The dry-run prints that **[EST]** and does not call a provider. Prices dated 2026-10-19. | Yes |
| D4 | Silero CI: every PR or manual only | Manual only | CI is unchanged (no workflow edit). The extra is an empty marker. See [SILERO.md](SILERO.md). | Yes |
| D5 | v1 signatures accepted in 0.2.0 | Accepted by default, deprecated | Keeps current v1 callers and tests working. Flag `VOICE_CASCADE_ACCEPT_V1_SIGNATURE`. ADR 0006. | Yes |

Nothing in this file is a production rollout decision.
