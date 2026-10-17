# Metrics

Two layers. The first is what this repository measures. The second is what a pilot would add. Do not mix them in a slide without the label.

## Measured here (simulated)

Command: `python -m voice_cascade eval` and `python -m voice_cascade latency-report`.
Date of the numbers in the README: 2026-10-17. Version 0.1.0.

| Metric | Operating target in this lab | Latest simulated result |
| --- | --- | --- |
| Invariant gate, balanced profile | exit 0 | pass (locked by tests) |
| Forced regression | exit non-zero | must fail |
| p95 end-to-end, latency cohort, balanced | ≤ 2500 ms simulated | 950 ms simulated |
| p50 end-to-end, balanced | report only | 860 ms simulated |
| False-cut rate, balanced | 0 | 0.0 |
| Missed eligible interruptions, balanced | 0 | 0.0 |
| Active bookings per slot | ≤ 1 | 1 in the conflict and duplicate scripts |
| Clinical advice in assistant text | 0 calls | 0 when the guard is on |
| Raw phone or scripted name in logs | 0 | redacted |
| Real provider calls | 0 | 0 |

Missed barge-in including sub-threshold bursts is a **reported** tradeoff (0.5 on balanced), not a gate failure. Those 80 ms bursts are below `min_speech_ms`.

## Pilot metrics (not measured)

All **[EST]** until a shadow log exists. Definitions so a later measurement is comparable.

| Metric | Definition |
| --- | --- |
| Containment | Share of scheduling calls that end booked, slots offered, or cancelled without a person. Escalations are not contained. |
| Handle time | Clock time from answer to hangup, person calls and cascade calls reported separately. |
| Cost per resolved call | Formula in [COST.md](COST.md). Unpriced until vendor pages are cited. |
| False escalation | Person judges that the cascade escalated a call it should have finished. Sampled, not exact-matched to tool traces. |
| Double book | Two active rows for one slot in the system of record. Target: zero. |
| Clinical leakage | Any assistant turn a reviewer marks as advice. Target: zero. |

A trajectory diff ("the model called tool X then Y") is not a success metric in this lab. [ADR 0002](adr/0002-invariant-evals.md) says why.
