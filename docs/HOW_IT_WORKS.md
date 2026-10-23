# How this lab works

This is a walkthrough for engineers and buyers. The latency numbers are **simulated**. There is no real telephone behind them.

## The analogy

Picture a restaurant that takes reservations only by phone.

1. The person on the other end talks. The host waits for a silence to be sure the sentence is finished. Cut too early and the order is half-written. Wait too long and the table gets impatient. That is the **VAD** (voice activity detection) and the turn end.
2. Only then does the host write down what they heard. Sometimes a word changes. That is the **STT**.
3. They decide: book a table, say which tables are free, cancel, or hand the call to a person. They do not invent a dish or give health advice. That is the **cassette LLM** plus the clinical guard.
4. They write the reservation in the book. If the pencil sticks and they try again, they must not write the same table twice. That is the **webhook with idempotency**.
5. They start reading the confirmation out loud. If the guest interrupts, the host stops. If they stop because a truck went by, they cut for nothing. That is **barge-in** and the false cut.

The lab measures those five times with a fake clock. Each wait is a seeded lognormal draw (the parameters are marked [EST] in the code). It is not the latency of a paid provider. The gate watches the budget. The numbers are a placeholder.

## The cascade, in one sentence

Synthetic audio goes in (really a list of pieces with a duration and text). A confirmation, a handoff, or a booking comes out. Five stages sit in the middle. See the diagram in the README: frames → VAD → STT → cassette → guard → webhook → TTS, and beside that the cut if the person speaks again.

This is not an end-to-end model that listens and speaks in one jump. It is a cascade on purpose, because that is where you can see **where** the time went.

## Step by step

1. The script builds frames. A frame is speech, silence, or noise, with milliseconds and a text. The logic does not need a WAV. There is a 20 ms silence WAV only to show that the audio interface exists (`fixtures/silence_20ms.wav`).
2. The VAD, with one of three profiles, decides when the turn ended.
   - **aggressive**: short silence (180 ms) and a low threshold. It cuts quickly. It also treats a 100 ms noise burst as speech.
   - **balanced**: 400 ms of silence and a threshold that ignores that noise. This is the profile that has to pass the gate.
   - **patient**: 800 ms. It waits longer. It does not rush a 300 ms pause.
3. The fake STT returns partials (one more word each time) and a final. If the script asks for errors, it changes words with a fixed seed. That stands in for a weak ASR. It is not a corpus of real accents.
4. The classifier folds the text (lowercase, accents stripped) and picks: clinical, cancel, book, find times, or unclear. The cassette says which tool to call and which sentence to speak. The script fills the booking ids, not the "model". Read that before you sell it as language understanding.
5. If the outgoing sentence has a clinical-advice mark (for example a drug name or "mg"), the guard replaces it with a handoff and calls no tools. In the forced regression that guard is turned off on purpose so the gate goes red.
6. Each tool goes through the local webhook: HMAC signature, idempotency key, capped retries with seeded jitter, and a JSONL dead-letter queue if the attempts run out.
7. The TTS splits the sentence into chunks and charges a time-to-first-byte. If speech arrives during that "playback" and the VAD accepts it, playback is cancelled. If noise arrives and the profile takes it as speech, that is a false cut.

The simulated clock only moves on those system waits. The time the person is speaking is not added to the end-to-end. End-to-end starts when the person stopped speaking and ends at the first byte of reply audio.

## Idempotency, with the same analogy

The guest says "write down table 4" and the line drops. The host does not know whether the pencil touched the paper. They say it again with the **same order number**. The book answers "already written, this is the reservation" and does not open another. If another guest asks for the same table with a different order number, the answer is "taken" and the call is handed off. That is R01 and R02 in the script.

If the pencil never touched the paper (timeout before the write) and the retries run out, the order goes to the dead-letter queue and the person is handed off. There is no ghost reservation. That is R04. `python -m voice_cascade dlq-replay` tries that queue again once the book is answering.

## Glossary

| Word | What it means here |
| --- | --- |
| Cascade | STT, then LLM, then TTS. Three hops, not one. |
| VAD | A rule that says "this is speech" and "they have stopped". |
| Barge-in | The person speaks while the system is still "talking", and playback has to stop. |
| False cut | Noise the VAD took for speech, which cut the sentence for nothing. |
| TTFT / TTFB | Time to the first model token, or to the first audio byte. In the eval they are seeded **SIMULATED** draws, not a wall clock. |
| Cassette | A fixed reply for an intent. Not a trained model. |
| Idempotency | Same key, same result, one side effect. |
| DLQ | The queue of what could not be confirmed after the retries. |
| Invariant | A rule about effects ("no two bookings", "no clinical advice"), not the exact list of tool calls. |

## Voice extension (0.2.0), still in the lab

From 0.2.0 there is a second path, beside the 49-call script. It does not replace those numbers (p50 896 ms and p95 1004.5 ms are still the simulated clock from package 0.1.9).

1. A generator builds toy audio: a sum of harmonics, not a person. Each clip has a sidecar with the start and end of the speech, in exact samples.
2. The energy VAD looks at 32 ms windows. A state machine decides whether the person is still talking, whether the turn has closed, or whether they interrupted. On an interrupt, TTS stops and the text left in the history is only what had already "played".
3. Agent echo is a correlation heuristic. It is not real echo cancellation.
4. A report of about 100 synthetic calls writes p50 and p95 per stage. Every row says **SIMULATED**. The p95 carries a bootstrap interval. It is not subtracted from the measured table in the README.
5. The webhook adds a signed timestamp (v2), classifies which errors are retried, and leaves the case that retries cannot fix on the dead-letter queue. The runbook for that is `docs/RUNBOOK.md`.

Silero (a VAD network) is an optional marker, off, with no model download. Decisions D1 to D5 stay open: `docs/voice/OPEN_DECISIONS.md`.

The command that regenerates the report is `python -m voice_cascade eval-voice`. That command costs zero. It does not call a provider.

## Honest limits

- It does not measure providers in CI. The README table "Measured with real providers" has one run pasted by hand (n=20, one provider, one run, not an SLA). The file title has to be exactly that. If STT or TTS is a local stub, the file is titled "Partially measured" and does not go in that table. If config is missing, or the estimate is over `MAX_LIVE_SPEND_USD`, the process exits 2 and sends no request. `unsupported_availability_claim` is a heuristic: it flags a clock time, a date ("October 20", "the 22nd", `20/10`), a confirmation ("I booked you", "confirmed"), or a slot ("Tuesday at 10am"), and only if that turn did not call a calendar tool. It does not flag a negation ("I can't") or office hours ("Monday to Friday"). It can fail in both directions and does not replace a human read. `cost.estimated_usd` is tokens times the env price. `provider_reported_usd` appears only when `usage.cost_in_usd_ticks` is an integer (1 tick = 1e-10 USD). The 2026-10-17/18 latency figures were measured on Spanish synthesized caller audio and were not re-measured after the English rewrite.
- The "LLM" does not choose the booking id by reading the sentence. The script sets it.
- The VAD on the 49-call script is an energy threshold over frames that carry text. The new path (0.2.0) uses the same kind of threshold on synthetic PCM. It is not a neural net. Silero stays off.
- There is no WebRTC, no SIP, no recording consent, and no second language.
- Names and phone numbers are invented and are also redacted in the logs. Redacting fiction is not compliance with a privacy law.
- The regression `make eval-regression` **has to fail**. If it passes, the gate is broken.
