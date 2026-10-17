# Discovery

Ask these before choosing a model, a telephony vendor, or a VAD profile. Each answer changes the design. The lab does not contain the answers; it shows which knob moves.

1. **How many scheduling calls arrive, and in which hours?**
   Volume and peaks decide whether the latency budget is a median problem or a p95 problem, and whether the webhook needs a queue separate from the call. A night-only pilot can use the patient VAD. A slammed Monday cannot use a profile whose false-cut rate is 1.0.

2. **What share of calls is truly one intent (book, list, cancel)?**
   If the share is low, containment in [BUSINESS_CASE.md](BUSINESS_CASE.md) collapses and the cascade should stay in shadow. If the share is high, the cassette approach is enough and a general assistant is the wrong build.

3. **Which calls must escalate, and who picks up?**
   The lab escalates clinical questions, unclear speech, slot conflicts, and dead letters. A real desk has to name the queue, the hours, and the maximum time a caller waits after escalation. If nobody picks up, do not automate the front door.

4. **What languages and accents are actually on the line?**
   This repo injects word errors with a seed. That is not an accent study. If more than one language shows up, the single Spanish cassette is out of scope until there is a language branch and a per-language gate. Do not "turn on" a multilingual vendor and skip the eval.

5. **What system owns the slots, and can it take an idempotency key?**
   If the system of record cannot replay a key, the lab's webhook pattern has to live in an adapter in front of it. If it cannot reject a second writer, do not connect the write tool.

6. **Is the call recorded, and what consent is required before any audio is stored?**
   The lab stores text traces of synthetic callers and redacts names and phones. It does not record audio. A yes on recording adds a consent state machine that does not exist here (design only). A no means the trace policy stays text-only and short-lived.

7. **What is allowed to happen when the webhook fails mid-call?**
   Options the lab already distinguishes: retry the same key, dead-letter and escalate, or return the booking that actually committed (slow response). The client has to pick one. "Try again and hope" is the double-book bug.

8. **What end-to-end latency will the operation accept, and who feels it?**
   The SIMULATED balanced p95 is 1004.5 ms (placeholder from the seeded clock, 2026-10-17, `python -m voice_cascade eval`, version 0.1.1). It is not a provider measurement. A human target might be looser or tighter. The VAD profile is the first knob: aggressive is faster and fails the false-cut gate by construction of the synthetic noise; patient is slower and still inside the lab budget of 2500 ms.

9. **How is the caller authenticated before a write?**
   The lab uses an opaque `patient_ref` from the script. If the real answer is "date of birth plus a phone", that is a new step before `book_appointment`, with its own redaction rules. If the answer is "anyone who calls", the write should stay off.

10. **What must the agent never say or do?**
    For this pattern the list is: no dose, no diagnosis, no payment capture, no second booking for one slot. The clinical guard and the invariant are the implementation of the first two. Payment is out of scope until someone adds a tool and a new invariant on purpose.
