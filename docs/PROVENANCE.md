# Provenance

Small utilities in this repository follow the same shape as the other labs in this portfolio. They are maintained in parallel and kept aligned. Nothing here is copied from employer or client work.

## Shared across the portfolio

| Utility | Module here | Role |
| --- | --- | --- |
| Cassette provider | `llm.py`, `cassettes/clinic.json` | Fixed replies for scripted intents |
| Invariant checks | `evalkit.py` | Gate on effects, not on a golden transcript |
| JSON trace | `trace.py` | One JSON object per turn |
| Structured logging | `logging_setup.py` | JSON logs with redaction |
| Secret scanner | `secretscan.py` | Vendored copy, same pattern list |

## Adapted here

The cascade, the three turn-taking profiles, the booking webhook, and the optional live measurement command are specific to this lab. Stage times on the simulated clock are seeded lognormal draws. The medians and sigmas are marked **[EST]** in `src/voice_cascade/latency.py`. The live command stays off unless `LIVE_MODE=1` and is not part of CI.

## Vendored secret scanner

`src/voice_cascade/secretscan.py` is a vendored copy kept identical across the portfolio repos. The digest below is of that file's bytes.

sha256: ddcc57e54eb22c68d8c2414a573b1fdae5a8b22987cdba0ac3757e9edd690efb

`make secretscan-hash` recomputes the digest and exits non-zero on a mismatch. `tests/test_secretscan.py` checks the same value.
