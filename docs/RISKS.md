# Risks

Owners are roles. "Lab maintainer" is the person who merges this repo. "Clinic operations" and "platform owner" exist only if a later pilot exists. Probability and impact are judgments for this lab, marked as such, not statistics from production.

| Risk | Probability | Impact | Mitigation | Owner |
| --- | --- | --- | --- | --- |
| A retry books the same slot twice | Low in this lab (unique index plus idempotency key) | High if it ever reached a real calendar | Invariant `double_booking`. R01–R05. Do not connect a system that cannot honor a key. | Platform owner for a pilot. Lab maintainer for this repo. |
| The agent states a dose or a diagnosis | Low while the guard and the cassette stay as tested | High | Invariant `clinical_advice`. Forced regression proves the gate sees it. | Clinic operations for the phrase list. Lab maintainer for the code. |
| Aggressive VAD cuts on noise and the caller hears a broken sentence | High if that profile is selected (measured false-cut rate 1.0 simulated, 2026-10-17) | Medium | Gate requires zero false cuts. Balanced is the default. | Platform owner chooses the profile. Lab maintainer keeps the gate. |
| Patient VAD waits through a long pause and the call feels slow | Medium by design (p95 e2e 1350 ms simulated) | Low inside the lab budget, unknown on a real line | Report the three profiles side by side. Do not pick patient without a measured vendor budget. | Platform owner |
| Webhook hangs mid-call and the caller sits in silence | Medium once a real dependency exists. Not observable on the in-process transport. | High | Per-attempt timeout, capped retries, DLQ, escalation copy. Runbook section "webhook stuck". | Platform owner |
| Dead-letter queue grows and nobody replays it | Medium in a pilot, low in the lab (one scripted case) | Medium: missed bookings, no double book | `dlq-replay`, runbook "DLQ growing", alert on queue length (not built here). | Platform owner |
| Logs keep a synthetic or real phone number | Low after redaction tests | High if a real number ever entered the process | Redaction of phone keys and patterns. Invariant `pii`. Do not load a real extract. | Lab maintainer |
| Someone treats simulated p95 as a vendor SLO | High if the README box is skipped | High reputational | Honest-limits box. "Measured with real providers: none yet". | Lab maintainer |
| Demo HMAC constant reused outside the laptop | Low if the docs are followed | High | `SECURITY.md`. Secret scan. Empty `.env.example`. | Whoever deploys |
| Cassette and script drift so the intent no longer matches the tool | Medium as phrases change | Medium | Outcome invariant, not a golden trajectory. Tests lock the balanced cohort. | Lab maintainer |

## Not covered yet

See the same list in the README governance section. The highest gap for a pilot is caller authentication and a real escalation queue. The lab records `escalated` and stops.
