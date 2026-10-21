# Value realization plan: adopting `voice-agent-cascade-lab`

> **Important notice**
>
> - **Fictional customer.** "Fictional diagnostic-imaging network" is an **invented** company for this exercise. It does not represent any real customer or employer. The clinic in the repo, "Clínica Aurora", is fictional too.
> - **Inspired by the AWS Business Value Realization (BVR) framework:** a value-realization plan, KPIs with a threshold per stage ("pit stops"), and confirmation by the customer. **It is not an official AWS template** (the official VRP template is not public) and **I do not hold the AWS BVR Competency**, which is awarded to AWS partner companies, not to individuals.
> - Labels:
>   - **[REPO]**: measured or configured in the repo, with the commit, version, and date the repo records.
>   - **[REPO-EST]**: a figure the repo itself marks as [EST].
>   - **[SYN]**: a synthetic business assumption invented for this case.
>   - **SIMULATED**: the repo labels it this way. It comes from a seeded clock, not from a provider.
> - Repo: https://github.com/dlescanogithub/voice-agent-cascade-lab (tree `bdd841a`, 2026-10-21, package 0.2.0). This document was checked against that tree. It does not move the measured commits below.

---

## 0. What the lab actually does (technical base, [REPO])

**Offline cascade** STT → LLM → TTS with fake providers and a simulated clock, for one intent family: book, list, or cancel a slot. It does not give clinical advice. It does not place phone calls, it does not use a microphone, and it does not call providers in `eval`, `demo`, or CI.

**SIMULATED figures for the 49-call script** (latency cohort n=36, VAD profile *balanced*, seed 42). The repo publishes them as package **0.1.9**, revision `4fb26ef5a281cc7b325c75c5f6e0f7a96e9a16fa`, 2026-10-17, command `python -m voice_cascade eval`. They are placeholders with lognormal parameters **[REPO-EST]**. They were **not re-measured as a published 0.2.0 result**. The 0.1.9 publication does not record a Python version. On this tree the same command prints `version=0.2.0` because that is the package version. A local run of that command on `bdd841a` with Python 3.12.3 printed the same percentiles. That run confirms the clock still emits the 0.1.9 figures. It is not a new measurement, and it does not move the attribution off `4fb26ef`.

| Stage | p50 SIMULATED ms | p95 SIMULATED ms | Budget p95 ms |
| --- | ---: | ---: | ---: |
| VAD endpoint | 400.5 | 412.5 | 900 |
| STT final | 155 | 213.75 | 400 |
| LLM TTFT | 137 | 195.5 | 350 |
| Tool webhook | 104 | 206.75 | 800 |
| TTS TTFB | 69.5 | 99.5 | 250 |
| End to end (end of caller speech → first TTS byte) | 896 | 1004.5 | 2500 |

**SIMULATED VAD profiles** (the same 49 scripts):

| Profile | p50/p95 e2e (ms) | False-cut rate | Missed barge-in (all attempts) | Premature endpoint | Gate |
| --- | --- | ---: | ---: | ---: | --- |
| aggressive | 676 / 780 | 1.0 | 0.0 | 1.0 | **fail** |
| balanced | 896 / 1004.5 | 0.0 | 0.5 | 0.0 | pass |
| patient | 1295 / 1413.75 | 0.0 | 0.5 | 0.0 | pass |

- The aggressive 1.0 is "by construction": the synthetic noise has RMS 0.35 and the threshold is 0.30 (`NOISE_RMS` in `budget.py`, `speech_threshold` on the aggressive profile in `vad.py`).
- The missed-barge-in 0.5 is 80 ms bursts that *balanced* and *patient* are configured to ignore (4 of 8 barge-in calls). Balanced `min_speech_ms` is 120. It is a **reported** tradeoff, not a gate failure. Missed eligible interruptions on balanced are 0.0.

**What fails the gate, as `evaluate()` implements it** (`src/voice_cascade/evalkit.py`):

1. A call outcome is not in the outcomes allowed by its script.
2. `contains_clinical_advice` (a phrase check) finds clinical advice in the assistant text.
3. An eligible barge-in was not cancelled (`missed_interrupt`).
4. A cancellation takes longer than `CANCEL_BOUND_MS` = 300 ms.
5. An unexpected dead letter appears, or an expected one is missing.
6. A false cut, because `require_zero_false_cuts` defaults to True.
7. More than 1 active booking per slot. There is also a partial unique index in SQLite, `one_active_per_slot`.
8. Scripted names or phones appear raw in the logs or traces (`contains_raw_pii`).
9. The p95 of any stage exceeds its budget on the latency cohort.

**Robustness R01–R05** [REPO]:

- R01: a duplicate `book` leaves one active booking.
- R02: two callers and one slot: the second call is escalated and one booking remains.
- R03: two HTTP 500s, then success: one booking in 3 attempts.
- R04: timeout before commit: escalated, one dead letter, no booking.
- R05: slow response after commit: the retry returns the same booking.

**Voice extension 0.2.0, SIMULATED** ([docs/voice/SIMULATED_LATENCY.md](voice/SIMULATED_LATENCY.md): package `0.2.0`, seed 42, 100 calls, 400 turns, p95 bootstrap with 2,000 resamples). Regenerated with `python -m voice_cascade eval-voice` on commit `bdd841a88dd516407913493efa9b07fc4eaa0ea6` and Python 3.12.3. That command reproduced the tables already in the file. The commit and the Python version are recorded in the file by this docs change. `eval-voice` itself does not write them.

The current SIMULATED cohort is this 100-call script, not the 49-call table above:

- End-to-end p50 **807** / p95 **927.150** ms. Bootstrap interval on that p95: [**911**, **953**].
- Cold start (first turn of each call) end-to-end p50 **879.500** / p95 **979.050**.
- Per-stage p95 on that report (3 decimal places, as printed): VAD 416, STT 218.150, LLM 191.050, tool 116.100 (n=100), TTS 102.050, end-to-end 927.150. Tool n is 100 because not every turn calls the tool.
- False barge-in 0 (0 / 230); missed barge-in 0 (0 / 112); reaction p50/p95 192 / 192 ms; endpoint p95 416; premature 0 (0 / 400); history violations 0.
- Webhook W01–W12: 12 of 12 pass.
  - W01: timeout before commit: no booking, one dead letter.
  - W02: slow after commit: same booking.
  - W03: two 503s then one booking, 3 attempts.
  - W04: Retry-After 2s, wait capped at `backoff_cap_ms`.
  - W05: persistent 500, dead letter `http_5xx` inside the tool bound.
  - W06–W08: poison, bad args, or a missing idempotency key: HTTP 400, no retries. The report's class column is `poison_payload`, `bad_args`, and `missing_idempotency_key`. A 400 is classified as `poison_payload` inside the client even when the payload error is `bad_args`.
  - W09: JSON reordered after signing: HTTP 401, payload error `bad_signature` (the client class is `auth_failed`; the report's class column says `bad_signature`).
  - W10: one denied attempt (`auth_failed`, attempts 1 in the report) and a separate call that succeeds once `previous` is set.
  - W11: the case sends a timestamp 600 s (10 minutes) old. The tolerance is 300 s. The report detail is "capture older than 300s is stale_timestamp" (HTTP 401).
  - W12: duplicate delivery: `idempotent_replay`.

**Measurement with real providers** ([docs/LIVE_RUN.md](LIVE_RUN.md) and [docs/live/2026-10-17-results.json](live/2026-10-17-results.json), HEAD `84cfb1a`, 2026-10-17/18, n=20, one provider, one run, **not an SLA**; VAD and the tool do not run in live) [REPO]. Values from the file at full precision. The README table rounds each stored p95 to 0.1 ms (281.5, 1145.3, 1253.6, 2587.7).

| Stage | p50 ms | p95 ms |
| --- | ---: | ---: |
| STT total | 245.0 | 281.45000000000005 |
| LLM total | 798.5 | 1145.3000000000002 |
| TTS full audio | 993.5 | 1253.6000000000004 |
| End-to-end STT+LLM+TTS, real stages only | 2022.5 | 2587.7000000000007 |

- TTS first byte is not a key in the `latency` object. Recomputing from `turns[].tts.ttfb_ms` the way the file builds percentiles (round each sample to an integer millisecond, then the inclusive linear percentile) gives p50 302 / p95 380.05. [LIVE_RUN.md](LIVE_RUN.md) states the same pair.
- 60 HTTP calls, all status 200 (adapter log: 20 STT, 20 LLM, 20 TTS).
- `invariants.passed` is **false** because of `unsupported_availability_claim:S15` (turn id `S15`). `cmd_live` returns exit 1 when that flag is false. The results file does not store the process exit code. [LIVE_RUN.md](LIVE_RUN.md) states that the command exits 1. The repo publishes the failure.
- Compared with `StageBudget` (`e2e_ms` 2500, `tts_ttfb_ms` 250), the stored live end-to-end p95 is above 2500 ms, and the live TTS first-byte p95 (380.05 ms) is above 250 ms. **Live mode does not apply those budgets** (`live.py` does not read `StageBudget`). The exit 1 is the heuristic failure, not a budget failure. Definitions differ: live end-to-end is the sum of full STT, LLM, and TTS audio; the lab end-to-end budget stops at the first TTS byte. The 380.05 ms figure is first-byte time. The live TTS row above is full audio.
- Cost:
  - LLM: `cost_in_usd_ticks` 36684000 = US$0.0036684 (`provider_reported_usd` and `estimated_usd` in this file).
  - STT+TTS from list prices, as published in [LIVE_RUN.md](LIVE_RUN.md): 49.296 audio seconds at US$0.10 per hour, plus 3742 characters at US$15 per 1M characters, published as US$0.05749933. Those two inputs are in the adapter log (sum of `audio_s` and sum of `chars`). The unrounded product is US$0.0574993333….
  - Published total US$0.06116773 (the LIVE_RUN sum). Dividing that published total by 20 is about US$0.0030583865 per turn. **That quotient is not a field in `results.json`.** The speech API does not report the STT+TTS dollars.
- An earlier rehearsal of the same code: end-to-end p50/p95 2050.0 / 3386.3 ms (`docs/live/2026-10-17-rehearsal.json`). Run-to-run variation is real. Invariant failure on that file: `unsupported_availability_claim:S4`.

**Heuristic `unsupported_availability_claim`** [REPO]: four handwritten sets of n=20 scored 11/20, 15/20, 14/20, and 16/20. The intervals overlap, so no improvement is shown. Recall after the latest patterns is not measured yet. The pattern list and the labeled samples are in [HEURISTIC_RECALL.md](HEURISTIC_RECALL.md).

---

## 1. Business challenge [SYN]

The fictional diagnostic-imaging network receives **20,000 calls per month** on its scheduling line, in Rioplatense Spanish [SYN]. **45%** are only book, list, or cancel [SYN]. Call-center staff spend time on that intent, and Monday peaks create a wait. When the scheduling system is slow, manual retries produce **about 30 duplicate appointments per month** [SYN], at about USD 20 each in empty-room time and rescheduling [SYN]. They want to automate that intent **without giving medical instructions** (for example, how to prepare for a study), without cutting the caller off during a pause, and without duplicating appointments.

The repo's own [EST] sketch in [BUSINESS_CASE.md](BUSINESS_CASE.md) is a different volume: 8,000 scheduling calls per month and a 40% slice. Do not mix the two.

## 2. Objectives and sponsor [SYN]

- **Executive sponsor:** Director of Operations of the fictional network.
- **Owner of the slot inventory and the clinical boundary:** clinic operations.
- **Owner of the webhook, the DLQ, the VAD profile, and the latency budget:** platform.

That split is the ownership table in [RUNBOOK.md](RUNBOOK.md) [REPO]. The sponsor's job title is [SYN]. The runbook also gives the platform owner a share of the caller-experience decision with operations, and it names a lab maintainer for the eval gate.

- O1. Contain part of the scheduling intent with latency inside a budget, **measured on a real line**, not simulated.
- O2. **Zero duplicate appointments**: one active booking per slot, with idempotency on every retry.
- O3. Turn-taking that does not cut on noise and that cancels TTS when the caller interrupts.
- O4. Zero clinical advice. Anything that is not scheduling goes to a person.

## 3. Plan KPIs

| KPI | Category (BVR / Cloud Value Framework) | Baseline | Target | How it is measured | Stage |
| --- | --- | --- | --- | --- | --- |
| p95 end-to-end (end of speech → first TTS byte) | Agility / experience | SIMULATED 1004.5 ms (0.1.9, `4fb26ef`, not re-measured on 0.2.0) [REPO]; current 0.2.0 SIMULATED cohort (different script) p95 927.150 ms (`bdd841a`, Python 3.12.3) [REPO]; live STT+LLM+TTS **full audio** p95 2587.7000000000007 ms (n=20, `84cfb1a`) [REPO]. **The definitions are not the same** | ≤2500 ms **MEASURED** on the real line, n≥100 per stage [SYN; 2500 is the lab budget, REPO] | `python -m voice_cascade live` plus traces by `call_id`/`turn_id` [REPO]; later, production telemetry [SYN] | 1. Activation (shadow) |
| p95 by stage: STT final / LLM TTFT / tool / TTS TTFB | Agility | SIMULATED 213.75 / 195.5 / 206.75 / 99.5 ms on the 49-call cohort (0.1.9) [REPO]; 0.2.0 100-call p95 218.150 / 191.050 / 116.100 / 102.050 ms [REPO]; live TTS first byte p95 380.05 ms [REPO] | ≤400 / ≤350 / ≤800 / ≤250 ms [REPO: `StageBudget`], measured on a real line [SYN] | Per-stage table with MEASURED provenance, not mixed with SIMULATED [REPO: the test rejects mixed tables] | 1. Activation → 2. Scale |
| False-cut rate (noise during TTS that cancels playback) | Experience / resilience | 0.0 SIMULATED on balanced; 1.0 SIMULATED on aggressive, by construction [REPO] | 0 on a consented real-audio sample [SYN] | Gate with `require_zero_false_cuts` [REPO] plus listening to a sample [SYN] | 1. Activation |
| Eligible barge-in not cancelled / cancel ≤300 ms | Experience | 0.0 SIMULATED missed eligible; 300 ms bound (`CANCEL_BOUND_MS`) [REPO] | 0 and ≤300 ms on real audio [SYN] | Invariants `missed_interrupt` and `cancel_bound` [REPO]; short bursts (under `min_speech_ms`) are reported separately [REPO] | 2. Scale |
| Containment (the call ends booked, slots offered, or cancelled, without a person) | Productivity | 0% [SYN] | 50% of the scheduling slice (9,000 calls/month → 4,500) [SYN; the repo uses 50% of its own slice as [REPO-EST], on 8,000 calls and a 40% slice, not on these 9,000] | Outcome per call; escalations **do not** count as contained (definition in [METRICS.md](METRICS.md)) [REPO] | 2. Scale |
| Duplicate appointments (more than 1 active booking per slot) | Resilience / cost | ~30/month [SYN] | 0 [REPO: invariant `double_booking` plus the partial unique index] | Count in the scheduling system; `active_counts` [REPO] | 2. Scale |
| Tool dead letters and retries of non-retryable errors | Operational resilience | Not measured [SYN] | DLQ ≤1% of handled calls [SYN]; 0 retries on poison, bad args, a missing key, a bad signature, or a stale timestamp [REPO: W06–W11] | `dlq.jsonl` grouped by `error_class`; `dlq-replay` with **the same** key [REPO] | 2. Scale |
| Webhook signatures rejected after a deploy | Resilience | No control [SYN] | 0 sustained `bad_signature`; rotation with `previous` [SYN; the mechanism is REPO, W09/W10] | Logs with secret ids, never values [REPO] | 3. Value retention |
| Clinical advice in the assistant text | Risk | 0 with the guard on; the forced regression detects it [REPO] | 0, plus human review of 5% of transcripts [SYN], because the guard and `unsupported_availability_claim` are heuristics [REPO] | Invariant `clinical_advice` plus a human sample | 3. Value retention |
| Voice-stack cost per minute | Cost savings | Live: US$0.06116773 for 20 turns, the published sum in LIVE_RUN [REPO]; bundle D L1 [REPO-EST]: dry-run `estimated_usd=0.3229` for 100 turns (`cost_estimate.bundle_d_l1_usd`, rounded to 4 decimals). With the 20% contingency the same function is 0.3875 | ≤USD 0.06/min including telephony [SYN] | Provider invoice plus cost ticks per call [REPO]; telephony is outside the repo [SYN] | 3. Value retention |

> Note: the repo measures SIMULATED latencies, turn-taking on synthetic PCM, webhooks, idempotency, a DLQ, and one live run of n=20. It does **not** measure containment, handle time, duplicates in a real system, telephony, or human audio. The customer would have to measure those business KPIs.

## 4. Stages ("pit stops") with exit criteria [SYN, structure inspired by BVR]

1. **Activation / shadow** (weeks 1–8)
   - Work: connect telephony and the scheduling system through an adapter that accepts the idempotency key (question 5 in [DISCOVERY.md](DISCOVERY.md) [REPO]).
   - Shadow (the cascade suggests and a person confirms), telephony, consent, and multi-language still have to be **built**. In the repo they are design only or a next step [REPO].
   - Measure real per-stage latency at n≥100 and record a consented sample of real audio.
   - *Exit:* MEASURED end-to-end p95 ≤2500 ms; false-cut rate 0 on the sample; gate green and regression red in CI.
2. **Scale: a gated write** (months 3–5)
   - Work: `book_appointment` and `cancel_appointment` write behind idempotency, a latency budget, and an explicit approver for the tool.
   - *Exit:* containment ≥50% of the slice; 0 duplicates; DLQ ≤1%; 0 missed eligible barge-ins.
3. **Value retention** (months 6–12)
   - Work: monthly transcript review (5%), a secret-rotation drill, VAD-profile recalibration by time of day, and a cost-per-minute check against the invoice.
   - *Exit:* 0 clinical advice in the sample; cost ≤USD 0.06/min.

**Customer confirmation:** at the end of each stage, the Director of Operations and clinic operations sign a note that confirms the KPIs with the evidence attached (MEASURED latency reports, scheduling-system counts, a transcript sample). That follows the BVR idea that **the customer attests the results**.

## 5. ROI (year 1) [ALL SYNTHETIC, except where marked]

**Formulas:**

- Benefit = staffing relief + duplicates avoided.
- Cost = initial investment + recurring cost. Recurring cost is maintenance, the voice stack, recovery from false barge-ins, and manual repair of dead letters. That is the same term structure as [BUSINESS_CASE.md](BUSINESS_CASE.md) [REPO-EST]. The dollars below are not that file's dollars.
- ROI = (benefit − cost) / cost.
- Payback (months) = initial investment / ((benefit − recurring) / 12).

**Shared assumptions** [SYN]:

- 20,000 calls/month; scheduling slice 45%, so 9,000 calls handled by the cascade.
- 4 minutes avoided per contained call (the repo also uses 4 minutes as [REPO-EST], on a different volume).
- USD 0.40/min loaded staffing cost.
- Voice stack + telephony: USD 0.06/min × 3 minutes per handled call.
- False barge-ins: 2% × 1 minute of recovery. Dead letters: 1% × 5 minutes of manual repair.
- Duplicates avoided: 30/month × USD 20.

**Costs** [SYN]:

| Item | USD/year |
| --- | ---: |
| Integration: telephony, scheduling-system adapter, shadow (initial investment) | 30,000 |
| Spanish golden set with consented real audio (initial investment) | 4,000 |
| Maintenance (10 h/month × USD 50) | 6,000 |
| Voice stack + telephony (9,000 × 3 min × 0.06 × 12) | 19,440 |
| False barge-in recovery (0.02 × 9,000 × 1 min × 0.40 × 12) | 864 |
| Manual dead-letter repair (0.01 × 9,000 × 5 min × 0.40 × 12) | 2,160 |
| **Total cost** (investment 34,000 + recurring 28,464) | **62,464** |

**Results:**

| Scenario | Containment of the slice | Benefit | ROI | Payback |
| --- | ---: | ---: | ---: | ---: |
| **Base** | 50% → 4,500/month; staffing 86,400 + duplicates 7,200 | 93,600 | (93,600 − 62,464) / 62,464 ≈ **49.8%** | 34,000 / ((93,600 − 28,464) / 12 = 5,428/month) ≈ **6.3 months** |
| **Conservative** | 30% → 2,700/month; 51,840 + 7,200 | 59,040 | ≈ **−5.5%** | ≈ **13.3 months** (does not pay back inside the year) |
| **Minimum** | 10% → 900/month; 17,280 + 7,200 | 24,480 | ≈ **−60.8%** | **never**: monthly net benefit is negative (−332) |

**An honest reading:**

- In voice, ROI depends almost entirely on **containment**. The voice stack is paid for every handled call, including calls that escalate. Below about 33% containment of the slice, year 1 does not break even.
- What still holds when containment is low: **duplicates avoided** and **webhook discipline** (idempotency, DLQ, signatures).
- The live p95 of 2587.7000000000007 ms (STT+LLM+TTS full audio, n=20) shows that real latency can land near or above the 2500 ms budget. That is why stage 1 measures before anyone promises a latency. The comparison is not a result the live command computes. See section 0 for the definition caveat.

## 6. Risks

| Risk | Source | Mitigation |
| --- | --- | --- |
| Lab latencies are SIMULATED (seeded clock, [EST] parameters) and do not predict a real line | [REPO] | Measure in shadow at n≥100 per stage; do not compare SIMULATED tables with MEASURED tables |
| The live run is n=20, one provider, one run, and the rehearsal p95 was 3386.3 ms: runs differ | [REPO] | Several runs and times of day; report intervals |
| Live TTS first byte (p95 380.05 ms) is above the lab's 250 ms budget. The live command does not make that comparison. Live end-to-end is full audio; the lab TTS budget is first byte | [REPO] numbers; the comparison is a reading of those numbers | TTS streaming, filler phrases while the tool runs, try another provider |
| `unsupported_availability_claim` and the clinical guard are heuristics: recall between 11/20 and 16/20, with no demonstrated improvement; the live run failed on S15 and the command path exits 1 | [REPO] | Human review of transcripts; slots only from the calendar tool |
| The fake LLM does not interpret dates in free text: the script supplies the slot | [REPO] | Add the invariant "arguments stay inside the allowed slot set" (a next step in the repo) |
| No telephony, consent, caller authentication, or multi-language | [REPO] | Outside the lab's scope: integration budget [SYN] |
| v1 signatures are still accepted by default (D5 open, deprecated) | [REPO] | Cut v1 in stage 2 with a notice window |
| Callers with accents or noise that the balanced profile does not cover | [SYN] | A profile by time of day, a real-audio sample, fallback to a person |
| Volume, rates, containment, and duplicate assumptions are invented | [SYN] | Replace them with the discovery answers |

## 7. Checks against `bdd841a` (package 0.2.0)

These were open questions about the README at that commit. This docs change records the result of each check.

1. **Next steps item 1** asked to paste wall-clock rows into an empty table. The "Measured with real providers" table already holds the `84cfb1a` run. The item now says so.
2. **49-call figures stay attributed to 0.1.9 / `4fb26ef`.** They were not re-published as a 0.2.0 measurement. `eval` on this tree prints `version=0.2.0` and, on Python 3.12.3, the same percentiles. That local print is a confirmation, not a new published campaign. The current SIMULATED cohort is the 100-call report (end-to-end p95 927.150 ms).
3. **Python version for the 0.2.0 SIMULATED report.** [voice/SIMULATED_LATENCY.md](voice/SIMULATED_LATENCY.md) now records commit `bdd841a88dd516407913493efa9b07fc4eaa0ea6` and Python 3.12.3. Regeneration matched the existing tables. The 0.1.9 publication still has no Python version.
4. **README live p95 rounding is real.** Stored `p95_ms` values are 281.45000000000005, 1145.3000000000002, 1253.6000000000004, and 2587.7000000000007. The README shows 281.5, 1145.3, 1253.6, and 2587.7, and now says those cells are rounded to 0.1 ms.
5. **`docs/design/COST_ESTIMATE.md`** no longer says "private". The status line is "Draft v1".
6. **Tests.** Local `python3 -m pytest` with the repo addopts, Python 3.12.3, package 0.2.0: 105 passed, total coverage 92.97%. The suite is unchanged from `bdd841a`. The same command is recorded in the README.
7. **Budget comparison, confirmed from the artifacts.** Live end-to-end p95 2587.7000000000007 ms (`84cfb1a`, n=20) is above the lab 2500 ms budget. Live TTS first-byte p95 380.05 ms is above the 250 ms TTS TTFB budget. Live end-to-end is full audio; the lab end-to-end budget is first byte. The live run's published failure is `unsupported_availability_claim:S15`, and the live command returns 1 when `invariants.passed` is false. Live mode does not gate on `StageBudget`.
