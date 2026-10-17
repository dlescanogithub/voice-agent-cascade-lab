# ADR 0001: Simulated clock and fake providers

## Status

Accepted. 2026-10-17.

## Context

A cascade lab that calls a paid STT, LLM, or TTS on every test cannot run in CI, cannot be repeated bit-for-bit, and invites a false claim that vendor latency was measured.

## Decision

All stage times are constants on `SimulatedClock`. STT, LLM, and TTS are fakes. Real adapters exist only as functions that raise `RealProviderError` and contain no HTTP client. CI does not set the enable flags.

## Consequences

p50 and p95 are properties of the script and the constants, not of a network. They are comparable across machines. They are not a service level. The README says so in the first box.

## Alternatives

- Record vendor cassettes once and replay bytes. Useful later, still not a live measurement, and it needs a key the lab does not have.
- Call a vendor in a manual workflow only. Allowed later, outside CI, and only with a filled "real providers" row.
