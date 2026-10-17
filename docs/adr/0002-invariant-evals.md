# ADR 0002: Invariant evals, not trajectories

## Status

Accepted. 2026-10-17.

## Context

A golden list of tool calls breaks when the same booking is reached with a different order, or when a retry adds an attempt. It also passes a run that booked twice if the trace happened to match the happy path shape.

## Decision

The gate checks effects:

- outcome is in the scenario's allowed set (finished task or a graceful escalation)
- at most one active booking per slot
- assistant text has no clinical-advice markers
- logs and traces do not contain the scripted names or phones
- p95 of each stage on the latency cohort is within budget
- eligible barge-in cancels within 300 ms simulated, and the gated profile has no false cuts
- dead letters appear only for scenarios that expect them

A forced regression disables the clinical guard, injects an advice sentence, and must fail.

## Consequences

Word-error scenarios may escalate or complete. Both are allowed when the scenario says so. We do not assert the exact substituted string in the gate.

## Alternatives

- Snapshot the whole JSON trace. Rejected. It freezes the cassette wording and hides effect bugs that still match the snapshot.
