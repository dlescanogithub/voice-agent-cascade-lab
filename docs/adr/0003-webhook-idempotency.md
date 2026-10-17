# ADR 0003: Webhook idempotency and dead letters

## Status

Accepted. 2026-10-17.

## Context

A voice tool call is often retried because the phone path timed out, not because the booking failed. The dangerous case is a commit that succeeded and a response that never arrived.

## Decision

- HMAC-SHA256 over the raw body, header `X-Voice-Signature`.
- Client sends an idempotency key. The store returns the stored JSON for that key, including a failure such as `slot_unavailable`.
- SQLite partial unique index: one active booking per slot.
- Retries: at most `max_attempts` (default 3), exponential backoff capped by `backoff_cap_ms`, jitter from a seeded RNG.
- Timeout is per attempt. The simulated clock advances by the timeout, not by a wall sleep.
- Exhausted attempts append a JSONL dead letter. `dlq-replay` sends the same envelope again.
- Fault modes cover HTTP 500, timeout before commit, slow response after commit, duplicate delivery, and out-of-order observation.

## Consequences

Replay is safe only if the key is stable. The pipeline builds the key from scenario id, tool, and slot. A caller that changes the key on purpose is a second request and can hit `slot_unavailable`.

## Alternatives

- At-most-once with no retry. Fewer double bookings, more dropped bookings, worse for a flaky tool.
- At-least-once with no key. Simple client, unsafe store. Rejected.
