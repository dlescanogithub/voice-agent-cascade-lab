# Runbook

This process is a local lab. "Production" below means the shape of a later pilot, so the same steps still make sense on a laptop.

## Operate

```bash
python3 -m voice_cascade demo
python3 -m voice_cascade eval
python3 -m voice_cascade latency-report
```

Data directory: `VOICE_CASCADE_DATA_DIR` (default `./var`). Each command uses a subdirectory and deletes the SQLite file at the start of a suite so a second eval is not contaminated by the first.

Logs are JSON, one object per line, on the `voice_cascade` logger. Traces are JSONL under the data directory (`trace.jsonl`). Names and phones from the script are redacted.

The webhook listens only if you start it:

```bash
python3 -m voice_cascade webhook-serve --host 127.0.0.1 --port 8765
```

The eval path does not bind a port. It calls the handler in process.

## Monitor

On a laptop, monitoring is the command exit code and `reports/eval.json`.

In a pilot, page on:

- invariant failure (same checks as `evaluate`)
- dead-letter file length above a threshold you set (not coded here)
- p95 end-to-end above the agreed budget, measured on the real provider, not on this clock

## Incident: webhook stuck mid-call

Symptoms: the caller is silent after the transcript, the tool span grows until the timeout, the assistant says the system could not confirm, outcome `escalated`.

1. Check whether the handler committed. If the failure mode is `timeout_before_commit`, there is no booking. If it is `slow_after_commit`, the booking exists and a retry with the same idempotency key must return that same id.
2. Do not invent a new idempotency key and send the booking again. That is how a second row appears.
3. Confirm attempts stopped at `VOICE_CASCADE_MAX_ATTEMPTS` (default 3) and that backoff did not exceed `VOICE_CASCADE_BACKOFF_CAP_MS` (default 500) plus the configured jitter.
4. Read the last JSONL line in the dead-letter file. It has `call_id`, `error`, and `attempts`.
5. If the dependency is healthy, replay. If it is not, leave the letter in the queue and keep the caller with a person. The lab has no person to transfer to; it only records the escalation.

## Incident: DLQ growing

Symptoms: `dlq.jsonl` gains lines and callers leave without a booking.

1. Count lines. A growth rate is a pilot metric; this lab only asserts that script R04 writes one letter and that replay clears it.
2. Group by `error` (`timeout`, `http_500`).
3. Fix the dependency before replay. Replaying into a dead dependency appends nothing new only if you stop the command; a failed replay keeps the letter (`replay_dead_letters` puts failures back).
4. Replay:

```bash
python3 -m voice_cascade dlq-replay --dlq var/eval/dlq.jsonl --db var/eval/clinic.sqlite
```

Use the paths from the incident, not these defaults, if the data directory differs. The command prints `recovered` and `remaining`. Exit 0 means the file is empty of failures.

5. After replay, check `active_counts`: one active booking per slot. If a slot has more than one, stop and repair the store. The SQLite partial unique index is there to make that insert fail.

## Rollback

- Code rollback: revert the commit and redeploy the lab image. There is no live traffic in this repo.
- Data rollback: stop writers, keep the SQLite file, restore the previous file if you took a copy. Idempotency rows are part of the backup; without them a replay can double-book.
- Profile rollback: the gated profile is balanced. If a change flips the gate red on false cuts, set the profile back. Do not weaken `require_zero_false_cuts` to make CI green.
- Guard rollback: if someone disables `VOICE_CASCADE_DISABLE_CLINICAL_GUARD` in a shared environment, turn it back to unset. The regression job exists so that "off" cannot look like success.

## Ownership and handoff

| Piece | Owner in a pilot | In this repo |
| --- | --- | --- |
| Slot inventory and clinical boundary | Clinic operations | Cassette plus guard |
| Webhook, keys, DLQ, timeouts | Platform owner | `webhook.py` |
| VAD profile and latency budget | Platform owner, with operations on the caller experience | `vad.py`, `budget.py` |
| Eval gate | Lab maintainer | `evalkit.py`, CI |

Handoff notes to leave: the HMAC secret in use (out of band, never in git), the data directory, the last `reports/eval.json`, and whether any DLQ lines are still unrepaired.
