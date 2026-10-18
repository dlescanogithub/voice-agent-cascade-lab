# Scope

Fictional pilot: Clínica Aurora scheduling. No fees, no statement of work, no vendor contract.

## Phases

| Phase | What happens | Exit criteria |
| --- | --- | --- |
| 0. This lab | Simulated cascade, three VAD profiles, webhook, invariant gate. | `python -m voice_cascade eval` exits 0. `python -m voice_cascade eval-regression` exits non-zero. No vendor calls. |
| 1. Shadow | A person hears the caller and sees the proposed tool call. Nothing is written to a real calendar. | Four weeks of traces (the duration is a planning assumption **[EST]**, not a promise) with zero writes and a reviewed false-escalation sample. |
| 2. Gated write | One system of record, idempotency required, balanced-or-stricter false-cut policy, clinical path still human. | No double booking in the audit log. p95 latency measured on a real provider and written into the README table. Escalation queue staffed. |
| 3. Widen | A second intent only after phase 2 holds. | New cassette, new invariants, same gate. Not a prompt edit on Friday. |

## Assumptions

- One language in the cassette (Spanish, scheduling phrases).
- One service id: `consulta_general`. It is an administrative label, not a clinical protocol.
- The system of record can store an idempotency key or sit behind an adapter that does.
- Synthetic data only inside this repository.

## Out of scope

- Telephony, SIP, WebRTC, and phone numbers that ring.
- Neural VAD and real audio corpora.
- Speech-to-speech models and a bake-off against the cascade.
- Recording consent, retention schedules, and a legal review.
- Multi-language, payments, refills, and clinical content.
- A second fictional business in the same gate.
- Real vendor prices. Those stay **[EST]** until an official page is cited with a date.

## Exit criteria for the lab itself

The lab is done for this version when CI runs lint, types, tests with coverage at least 80%, the eval gate, the secret scan, and the forced regression, and when the README numbers match the harness. It is not a production voice service. The Measured with real providers table stays empty until `python -m voice_cascade live` is run outside CI.
