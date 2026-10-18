# Cost

Local commands cost **zero**. `eval` does not call a provider. Latency cells marked SIMULATED were produced by `python -m voice_cascade eval` and `python -m voice_cascade latency-report` on 2026-10-17, package 0.1.9, git revision `4fb26ef5a281cc7b325c75c5f6e0f7a96e9a16fa` on main. They are placeholders from a seeded clock, not a service level. Money cells are **[EST]** unless a URL and a retrieval date are in the last column. None are. The live command prices its own estimate from environment variables and a price date; that table in the README stays empty until a live run is pasted there.

| Scenario | Model / provider | Tokens or units | Cost / run | p50 / p95 latency | Quality | Price date / source |
| --- | --- | --- | --- | --- | --- | --- |
| SIMULATED scheduling call, balanced, latency cohort | Fake STT + cassette LLM + fake TTS, in process | Not tokens. Seeded lognormal draws, parameters [EST]. | 0 | p50 896 ms / p95 1004.5 ms end-to-end (SIMULATED) | Invariant gate passes | n/a, local, 2026-10-17, command `python -m voice_cascade eval` |
| Same script, aggressive profile | Same fakes | Same | 0 | p50 676 / p95 780 ms (SIMULATED) | Gate fails: false-cut rate 1.0 by construction (SIMULATED) | same command family, `latency-report` |
| Same script, patient profile | Same fakes | Same | 0 | p50 1295 / p95 1413.75 ms (SIMULATED) | Gate passes | same |
| One minute of a real call **[EST]** | Speech + language + synthesis, unnamed | `stt_minutes + llm_tokens + tts_characters` | **[EST]** | not measured | not measured | no official page retrieved |

## Per-minute formula

Do not fill the blanks with a remembered price.

```
cost_per_minute [EST] =
    stt_price_per_minute
  + (input_tokens + output_tokens) × token_price
  + tts_characters × character_price
```

`stt_price_per_minute`, `token_price`, and `character_price` are placeholders. Add a row only when the number is copied from an official pricing page, with the URL and the date it was opened. Until then the real-call row stays **[EST]** and the README does not quote a currency amount for a vendor.

A live `results.json` separates three money figures. `cost.precall_estimate_usd` is the cap check before any request, from env prices and reserved output tokens. `cost.estimated_usd` is the tokens the response reported, times those env prices. Its `cost_basis` is `tokens_x_price, cached tokens priced separately`: cached tokens use `LIVE_LLM_USD_PER_1K_CACHED_TOKENS` only when the response reports a cached count and that variable is set. Otherwise every input token is priced at the uncached rate, and the estimate note says so. `provider_reported_usd` is optional and is written only when `usage.cost_in_usd_ticks` is an integer tick count (1 tick = 1e-10 USD). The same block then includes the raw `cost_in_usd_ticks` and `provider_cost_source`. A token times price number is `estimated_usd` only. `usage.cost`, a fractional dollar amount in the tick field, and a `provider_reported_usd` already present on a replayed usage object are ignored. The live rollup recomputes the provider figure from the raw tick count.

Webhook retries add attempts, not a provider fee, in this lab. A slow or failed tool still costs caller time. That time is on the simulated clock (timeout 300 ms per attempt, backoff capped at 500 ms, 3 attempts). It is not in the latency cohort, so it does not move the SIMULATED 1004.5 ms p95.
