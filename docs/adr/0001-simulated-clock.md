# ADR 0001: Simulated clock and fake providers

## Status

Accepted. 2026-10-17.

## Context

A cascade lab that calls a paid STT, LLM, or TTS on every test cannot run in CI, cannot be repeated bit-for-bit, and invites a false claim that vendor latency was measured.

## Decision

The eval path advances `SimulatedClock` by seeded lognormal draws. Medians and sigmas are [EST] and live in `latency.py`. Turn-taking decisions stay on the profile thresholds. STT, the cassette, and TTS in `eval` are fakes. An optional live command (`python -m voice_cascade live`) can call a speech endpoint, a chat-completions endpoint, and a synthesis endpoint, but only when `LIVE_MODE=1`, and it exits 2 with no request when config or the spend cap fails. CI does not set `LIVE_MODE`. Tests never open a socket.

## Consequences

p50 and p95 are properties of the script, the seed, and the [EST] law. They are comparable across machines. They are placeholders until the owner runs the live command. They are not a service level. The README says so in the first box. A tighter budget fails the gate, so the percentile check is not vacuous.

## Alternatives

- Keep fixed stage times. Rejected: p50 and p95 were the same sum of constants, so the budget gate could not see a spread.
- Call a provider from CI. Rejected: cost, secrets, and a false claim that the lab measured a service.
