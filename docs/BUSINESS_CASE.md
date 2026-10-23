# Business case

Fictional desk: Aurora Clinic, one intent family, appointments only. No clinical advice. Figures in money and volume are **[EST]**. Latency figures cited from the harness are **SIMULATED** placeholders (see the README for the command and the date). They are not a provider measurement. One measured run lives in the README section "Measured with real providers"; it is not used in this ROI sketch and it is not a comparison with these placeholders.

## Pilot

A contact-center pilot for **one call intent**: book a slot, list free slots, or cancel. Everything else, including any health question, goes to a person. The pilot does not start with a dialer. It starts in shadow: the cascade proposes, a person commits.

## What would have to be true

These are assumptions, not measurements from a live queue.

| Assumption | Value | Label |
| --- | --- | --- |
| Scheduling calls per month | 8,000 | [EST] |
| Share that is only book / list / cancel | 40% | [EST] |
| Share of that slice the cascade contains after shadow | 50% of the slice, so 20% of all scheduling calls | [EST] |
| Handle time avoided per contained call | 4 minutes | [EST] |
| Loaded staffing cost | 0.45 currency units per minute | [EST], not a wage quote |
| Voice-stack cost per contained call | unknown until a vendor page is cited | [EST] |

Contained calls per month = 8000 × 0.40 × 0.50 = **1,600 [EST]**.

Minutes avoided = 1,600 × 4 = **6,400 [EST]**.

Gross staffing relief = 6,400 × 0.45 = **2,880 currency units / month [EST]**.

Net is that number minus the voice stack. This repo's local run costs **0**. A real stack is not priced here. Do not subtract a made-up vendor tariff.

## Cost per resolved call

```
cost_per_resolved_call [EST] =
    (staff_minutes_still_spent × loaded_rate)
  + stt_minutes × stt_price
  + llm_tokens × token_price
  + tts_characters × tts_price
  + webhook_ops
```

Until `stt_price`, `token_price`, and `tts_price` come from an official page with a URL and a retrieval date, each term stays **[EST]** and the total stays unpublished. See [COST.md](COST.md).

## What the lab already constrains

- One intent. Extra intents are a new cassette and a new gate, not a prompt tweak in production.
- p95 end-to-end on the balanced cohort is 1004.5 ms (SIMULATED placeholder), from 2026-10-17 with `python -m voice_cascade eval`, version 0.1.9. The harness gates a budget of 2500 ms. That ceiling is a lab limit, not a service target, and not a provider measurement.
- A retry must not create a second active booking. That is an invariant, not a hope.
- Containment counts only calls that finish as booked, slots offered, or cancelled. Escalations are not contained.

## Extension terms [EST]

The 0.2.0 lab makes two extra terms explicit. They are still placeholders. The SIMULATED false-barge-in rate in `docs/voice/SIMULATED_LATENCY.md` is not a measured rate on real callers, and it is not an improvement over the 49-script false-cut rate.

```
monthly_value [EST] =
    contained_calls × minutes_saved_per_call × loaded_rate_per_minute
  − calls × (voice_stack_cost_per_call)
  − false_barge_in_rate × calls × recovery_minutes × loaded_rate_per_minute
  − dead_letter_rate × calls × manual_fix_minutes × loaded_rate_per_minute
```

`voice_stack_cost_per_call` stays empty until a list price has a source URL and a date. A planning range for one future paid run, not spent here, is in `docs/design/COST_ESTIMATE.md`. The dry-run command prints bundle D at size L1 and sends no request. Which bundle to buy (D3) and how many turns to measure (D1) stay open.

## What this does not claim

No baseline handle time was collected. No currency is a quote. No clinic signed this pilot. The paragraph in the README under "Deployment Strategist conversation" is the order of work: discovery, shadow, then a gated write.
