# One real-provider run (2026-10-17/18)

This is one measured run of `python -m voice_cascade live` on repo HEAD `84cfb1a` (`84cfb1a784b44fd01d75d9c0190736c64e4c1a3c` on main). It is not an SLA. n=20 turns, one provider (xAI), one recorded run. A rehearsal with the same code is a different run; the two are not averaged.

Evidence in this directory:

- [2026-10-17-results.json](live/2026-10-17-results.json) is the file the command wrote. Title: `Measured with real providers`. `price_date` is `2026-10-17`.
- [2026-10-17-adapter-log.jsonl](live/2026-10-17-adapter-log.jsonl) is one line per HTTP call. 60 lines, all status 200. No keys.
- [2026-10-17-rehearsal.json](live/2026-10-17-rehearsal.json) is an earlier run of the same code, not the run in the video.

The scratch adapter that rewrote the speech calls lived outside this repo. It is not vendored here. The timing in `results.json` is the repo's own transport clock.

## What was called

`results.json` `stages` records:

| Stage | Endpoint in the file | Source |
| --- | --- | --- |
| STT | `https://api.x.ai/v1/stt` | real |
| LLM | `https://api.x.ai/v1/chat/completions` | real |
| TTS | `https://api.x.ai/v1/text-to-speech/leo` | real |
| VAD | not run | stub |
| Calendar tool | not run | stub |

The results file does not store a model id. The run notes name the language model `grok-4.20-0309-non-reasoning` and the speech model `grok-voice-transcribe-2.0`. TTS voice in the endpoint path is `leo`. List prices were read from docs.x.ai on 2026-10-18 (pricing page last updated October 10, 2026): STT REST US$0.10 per hour, TTS US$15.00 per 1M characters, that language model US$1.25 / US$0.20 cached / US$2.50 per 1M tokens. https://docs.x.ai/developers/pricing

## How the command was configured

Keys stay in the environment. They are not in these files and they are not printed. Names only:

`LIVE_MODE`, `MAX_LIVE_SPEND_USD`, `LIVE_PRICE_DATE`, `LIVE_STT_URL`, `LIVE_STT_API_KEY`, `LIVE_STT_USD_PER_CALL`, `LIVE_LLM_BASE_URL`, `LIVE_LLM_API_KEY`, `LIVE_LLM_MODEL`, `LIVE_LLM_USD_PER_1K_INPUT_TOKENS`, `LIVE_LLM_USD_PER_1K_OUTPUT_TOKENS`, `LIVE_LLM_USD_PER_1K_CACHED_TOKENS`, `LIVE_LLM_RESERVED_OUTPUT_TOKENS`, `LIVE_TTS_BASE_URL`, `LIVE_TTS_API_KEY`, `LIVE_TTS_VOICE_ID`, `LIVE_TTS_MODEL_ID`, `LIVE_TTS_USD_PER_1K_CHARS`.

The repo's live client posts JSON to `LIVE_STT_URL` and an ElevenLabs-style synthesis URL. Those two shapes are not the xAI speech API. A temporary adapter outside the repo rewrote them to `POST /v1/stt` (multipart, pre-synthesized caller audio) and `POST /v1/tts`, and left `POST /v1/chat/completions` unchanged. The repo clock still timed each call. This repo does not include that adapter.

Caller audio was synthesized with TTS in Spanish on 2026-10-17 (original measurement data). It was not a human voice. The latency, `audio_s`, and `chars` figures below are from that run and were not re-measured. Transcript and utterance strings in the adapter log are English translations of those turns. Do not recompute `chars` from the translated text.

## Numbers from the files

Percentiles below are the `latency` object in `2026-10-17-results.json`. The repo rounds each sample to an integer millisecond, then takes the inclusive linear percentile (NumPy type 7). Recomputing that way from `turns[]` matches the stored figures. The table rounds each stored p95 to 0.1 ms. The stored `p95_ms` values are STT 281.45000000000005, LLM 1145.3000000000002, TTS full audio 1253.6000000000004, and end-to-end 2587.7000000000007. TTS first-byte p50/p95 are not keys in `latency`. The same integer-millisecond percentile on `turns[].tts.ttfb_ms` is p50 302 and p95 380.05.

| Stage | n | p50 ms | p95 ms |
| --- | ---: | ---: | ---: |
| STT total | 20 | 245 | 281.5 |
| LLM total | 20 | 798.5 | 1145.3 |
| TTS full audio | 20 | 993.5 | 1253.6 |
| TTS first byte | 20 | 302 | (p95 380.05, not in the README table) |
| End-to-end, STT+LLM+TTS, real stages only | 20 | 2022.5 | 2587.7 |

Every STT, LLM, and TTS `status` in the 20 turns is 200. The adapter log has the same 60 statuses. VAD and the calendar tool are excluded from end-to-end because live mode does not run them.

LLM money is `cost.cost_in_usd_ticks` = 36684000. At 1 tick = 1e-10 USD that is US$0.0036684 (`provider_reported_usd` and `estimated_usd` are the same number in this file). About US$0.003668 is that figure rounded. The speech API does not report a dollar amount. STT+TTS is a list-price estimate: 49.296 audio seconds times US$0.10 per hour, plus 3742 characters times US$15 per 1M characters, which is US$0.05749933, about US$0.0575. Adding the tick total gives about US$0.0612 (exact sum US$0.06116773).

`invariants.passed` is false. The only failure is `unsupported_availability_claim:S15`. The live command returns exit code 1 when that flag is false. The assistant sentence itself is not stored in the results file. The results file does not store the process exit code.

The stored end-to-end p95 (2587.7000000000007 ms, n=20) is above the lab budget of 2500 ms (`StageBudget.e2e_ms`). The TTS first-byte p95 (380.05 ms) is above the lab TTS TTFB budget of 250 ms. Live mode does not read `StageBudget`, so this run did not fail on those budgets. The exit 1 is the heuristic. Live end-to-end is full STT+LLM+TTS audio. The lab end-to-end budget stops at the first TTS byte. The 380.05 ms figure is first-byte time, which is the quantity the 250 ms budget names. The full-audio TTS p95 in the table is a different number.

## Rehearsal

`2026-10-17-rehearsal.json`, same code, earlier: end-to-end p50 2050 ms, p95 3386.3 ms (n=20). STT 253 / 479.15, LLM 823 / 1194.65 (max 2480.44), TTS 974 / 1717.85. Invariant failure `unsupported_availability_claim:S4`. Run-to-run variation is real. The recorded run is not the rehearsal.
