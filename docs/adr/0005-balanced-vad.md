# ADR 0005: Balanced VAD is the gated profile

## Status

Accepted. 2026-10-17.

## Context

Three profiles are the point of the lab: a fast one that false-cuts, a slow one that waits, and a middle one. The gate needs a single operating point or CI becomes a choice.

## Decision

`python -m voice_cascade eval` defaults to **balanced** (`min_speech_ms` 120, `end_silence_ms` 400, energy threshold 0.50). The false-cut invariant is on for that command. Aggressive is expected to fail it (noise RMS 0.35 is above its 0.30 threshold). Patient is stricter on short speech and still passes the false-cut rule. `latency-report` prints all three and does not fail the process.

Cancel bound is 300 ms simulated, which is above every profile's `min_speech_ms` (the largest is 220).

## Consequences

Shipping aggressive means the gate goes red until the product owner either changes the audio front end or explicitly accepts false cuts and edits the invariant. That edit should be a new ADR, not a silent flag.

## Alternatives

- Gate all three profiles. Rejected. Aggressive is a demonstration of the bad tradeoff, not a candidate.
- Gate none and only print rates. Rejected. The lab would not stop a regression to aggressive.
