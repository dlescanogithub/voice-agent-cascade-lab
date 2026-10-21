# ADR 0006: Signed webhook timestamp (v2)

## Status

Accepted for the lab default in 0.2.0. Open decision D5 (whether v1 stays on by default) is **not** closed by this ADR. The default below is the cheapest offline choice that keeps current callers working.

## Context

HMAC over the body stops a forged payload. It does not stop a captured payload from being replayed later. The voice path also needs a stable error class for "this signature is old" so the runbook can tell clock skew apart from a wrong secret.

## Decision

- Header `X-Voice-Signature: t=<unix_s>,v1=<hex>`. The MAC is HMAC-SHA256 over `"{t}."` concatenated with the raw body bytes.
- Tolerance is 300 seconds **[EST]**. A timestamp inside the window passes. A timestamp 301 seconds off fails with `stale_timestamp`.
- Retries resend the original `t`. A retry inside the window still passes. A capture older than the tolerance fails.
- Two secrets may be active: `current` and `previous`. Logs record secret ids (a short hash), never the secret value.
- v1 (`sha256=<hex>` over the raw body) is still accepted when `VOICE_CASCADE_ACCEPT_V1_SIGNATURE` is on. The 0.2.0 default is **on**, and it is documented as deprecated. Turning it off is a config change, not a silent ADR rewrite.
- Non-retryable 4xx responses (bad JSON, bad args, missing idempotency key, bad signature, stale timestamp) do not retry. 401 writes an alert on the dead letter. Poison letters are not replayed as-is.

## Consequences

Clients that only sign v1 keep working while the flag stays on. A proxy that reorders JSON keys breaks the MAC on purpose (case W09). Widening the 300 second tolerance is an ADR change, not a config tweak made to clear an alert.

## Alternatives

- v1 only. No replay window. Rejected for the extension because the runbook needs `stale_timestamp`.
- v2 only, v1 off in 0.2.0. Safer against replay of old v1 captures, and it would break the current in-repo v1 tests and any caller still on v1. Left open as D5. The default keeps v1 on so the lab stays runnable offline without a flag day.
