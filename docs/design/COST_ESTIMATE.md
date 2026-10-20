# Cost estimate: one live run of ~100 synthetic calls

**Status:** Draft v1, private. All money figures are **[EST]**. No API was called and nothing was spent to produce this file.
**Prices checked:** 2026-10-19, from the official pages listed in §5. Prices change; re-check on the day of the run and update `LIVE_PRICE_DATE`.

## 1. Assumptions

Reference point (**MEASURED**, from the repo's 2026-10-17/18 run, n=20 turns, `docs/live/2026-10-17-results.json`): about 2.46 s of caller audio per turn (49.296 s / 20), about 187 TTS characters per turn (3742 / 20), about 273 input and 42 output LLM tokens per turn (5464 / 832 total), 91% of input tokens reported as cached (4992 / 5464). The extension adds multi-turn history and tool turns, so the planning values below are larger.

| Input per turn | low [EST] | base [EST] | high [EST] |
| --- | ---: | ---: | ---: |
| Caller audio sent to STT | 2.5 s | 3.0 s | 4.5 s |
| LLM input tokens | 400 | 700 | 1,200 |
| LLM output tokens | 45 | 60 | 120 |
| Share of input tokens cached | 85% | 70% | 0% |
| Agent TTS characters | 160 | 190 | 300 |
| Caller-voice characters (only if caller audio is made with a paid TTS) | 40 | 50 | 70 |

Two run sizes:

- **L1:** 100 calls × 1 measured turn = 100 turns. Enough for per-stage p50/p95 on n=100.
- **L4:** 100 calls × 3 / 4 / 6 turns (low / base / high) = 300 / 400 / 600 turns. Adds history growth and barge-in turns.

Other rules:

- Caller audio is synthesized **offline** (zero cost) unless decision D2 picks a paid TTS. The paid option is a separate line.
- Barge-in turns are priced as if the full TTS reply was billed. Whether a cancelled streaming request is billed in full is **UNVERIFIED** for every provider, so this is the conservative case.
- VAD (Silero or energy) and the webhook run locally: zero provider cost.
- A 20% contingency covers retries and a short rehearsal. Totals are shown with and without it.
- Free credits, subscriptions and volume tiers are ignored. Pay-as-you-go list prices only.

## 2. Unit prices (list, pay-as-you-go, USD)

### STT

| Option | Price | Unit | Notes |
| --- | ---: | --- | --- |
| xAI Speech to Text, streaming | 0.20 | per hour | REST is 0.10 per hour |
| Deepgram Nova-3 Multilingual, streaming | 0.0092 | per minute | Struck-through list price. Page shows a limited-time promo of 0.0058. Estimate uses list. Spanish on the monolingual model: **UNVERIFIED**, so multilingual is priced. |
| ElevenLabs Scribe v2 Realtime | 0.39 | per hour | Batch Scribe v2 is 0.22 per hour |
| OpenAI gpt-4o-mini-transcribe | ~0.003 | per minute | OpenAI's own "estimated cost"; billed by tokens (1.25 in / 5.00 out per 1M). Treat as approximate. |

### LLM (per 1M tokens: input / cached input / output)

| Option | Input | Cached | Output |
| --- | ---: | ---: | ---: |
| xAI grok-4.20-0309-non-reasoning (< 200k prompt) | 1.25 | 0.20 | 2.50 |
| OpenAI gpt-4.1-mini | 0.40 | 0.10 | 1.60 |
| OpenAI gpt-5.4-mini | 0.75 | 0.075 | 4.50 |

### TTS (per 1M characters)

| Option | Price | Notes |
| --- | ---: | --- |
| xAI Text to Speech | 15.00 | |
| OpenAI tts-1 | 15.00 | |
| Deepgram Aura-2 | 30.00 | Listed as 0.030 per 1K characters |
| ElevenLabs Flash/Turbo or v4 Turbo | 40.00 | Listed as 0.04 per 1K characters. v4 and multilingual are 0.08 per 1K. |

## 3. Per-stage cost per run [EST], without contingency

### L4 (base: 400 turns, 20 audio minutes, 280k in / 24k out tokens, 76k TTS characters)

| Stage | Option | low | base | high |
| --- | --- | ---: | ---: | ---: |
| STT | xAI streaming | 0.04 | 0.07 | 0.15 |
| STT | Deepgram Nova-3 Multi (list) | 0.12 | 0.18 | 0.41 |
| STT | ElevenLabs Scribe v2 Realtime | 0.08 | 0.13 | 0.29 |
| STT | OpenAI gpt-4o-mini-transcribe | 0.04 | 0.06 | 0.14 |
| LLM | xAI grok-4.20 non-reasoning | 0.08 | 0.20 | 1.08 |
| LLM | OpenAI gpt-4.1-mini | 0.04 | 0.09 | 0.40 |
| LLM | OpenAI gpt-5.4-mini | 0.08 | 0.19 | 0.86 |
| TTS | xAI / OpenAI tts-1 | 0.72 | 1.14 | 2.70 |
| TTS | Deepgram Aura-2 | 1.44 | 2.28 | 5.40 |
| TTS | ElevenLabs Flash/Turbo | 1.92 | 3.04 | 7.20 |
| Caller voice, if paid TTS (xAI price) | one-time, cacheable | 0.18 | 0.30 | 0.63 |

TTS is the largest line in every bundle.

## 4. Per-run totals by bundle [EST]

| Bundle | STT | LLM | TTS | L1 (100 turns) | L1 + 20% | L4 | L4 + 20% | xAI spend in L4 + 20% |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| A. All xAI | xAI streaming | grok-4.20 non-reasoning | xAI | 0.28–0.66 (base 0.35) | 0.34–0.79 (base 0.42) | 0.84–3.93 (base 1.41) | 1.01–4.72 (base 1.69) | same as total |
| B. Deepgram speech + xAI LLM | Deepgram Nova-3 Multi | grok-4.20 non-reasoning | Aura-2 | 0.54–1.15 (base 0.67) | 0.65–1.38 (base 0.80) | 1.63–6.89 (base 2.67) | 1.96–8.27 (base 3.20) | 0.09–1.30 (base 0.25) |
| C. ElevenLabs speech + OpenAI LLM | Scribe v2 Realtime | gpt-4.1-mini | Flash/Turbo | 0.68–1.32 (base 0.82) | 0.82–1.58 (base 0.98) | 2.04–7.90 (base 3.26) | 2.45–9.48 (base 3.91) | 0 |
| D. Lowest list | gpt-4o-mini-transcribe | gpt-4.1-mini | tts-1 | 0.27–0.54 (base 0.32) | 0.32–0.65 (base 0.39) | 0.80–3.24 (base 1.29) | 0.96–3.89 (base 1.55) | 0 |

Ranges are low–high from §1. Add the caller-voice line only if D2 picks a paid TTS.

Formula used (script kept next to this file, `calc/cost_calc.py`):

```
cost [EST] = audio_minutes × stt_price_per_minute
           + (input_tokens × ((1 − cached_share) × input_price + cached_share × cached_price)
              + output_tokens × output_price) / 1e6
           + tts_characters × tts_price_per_million / 1e6
```

## 5. Sources (opened 2026-10-19)

| Provider | URL | What was read |
| --- | --- | --- |
| xAI | https://docs.x.ai/developers/pricing | Text API table (grok-4.20-0309-non-reasoning), Voice Pricing (STT 0.10/h REST, 0.20/h streaming; TTS 15.00 per 1M chars) |
| Deepgram | https://deepgram.com/pricing | STT streaming and pre-recorded tables (Nova-3, promo and list), TTS (Aura-2, Aura-1, Flux TTS) |
| ElevenLabs | https://elevenlabs.io/pricing/api | API pay-as-you-go: TTS per 1K chars by model, Scribe v2 and Scribe v2 Realtime per hour |
| OpenAI | https://platform.openai.com/docs/pricing | Standard text tokens (gpt-4.1-mini, gpt-5.4-mini), transcription (gpt-4o-mini-transcribe), tts-1 |

**UNVERIFIED** items (not used as facts): billing for cancelled streaming TTS requests on any provider; Spanish support on Deepgram Nova-3 monolingual; minimum top-up amounts per provider; any rate limit that would force a slower run.
