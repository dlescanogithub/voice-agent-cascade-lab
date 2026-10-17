# Cost

Local commands cost **zero**. They do not call a vendor. Latency cells marked simulated were produced by `python -m voice_cascade eval` and `python -m voice_cascade latency-report` on 2026-10-17, package 0.1.0. Money cells are **[EST]** unless a URL and a retrieval date are in the last column. None are.

| Scenario | Model / provider | Tokens or units | Cost / run | p50 / p95 latency | Quality | Price date / source |
| --- | --- | --- | --- | --- | --- | --- |
| Simulated scheduling call, balanced, latency cohort | Fake STT + cassette LLM + fake TTS, in process | Not tokens. Fixed stage units on a simulated clock. | 0 | p50 860 ms / p95 950 ms end-to-end (simulated) | Invariant gate passes | n/a, local, 2026-10-17, command `python -m voice_cascade eval` |
| Same script, aggressive profile | Same fakes | Same | 0 | p50 640 / p95 730 ms (simulated) | Gate fails: false-cut rate 1.0 | same command family, `latency-report` |
| Same script, patient profile | Same fakes | Same | 0 | p50 1260 / p95 1350 ms (simulated) | Gate passes | same |
| One minute of a real call **[EST]** | STT vendor + LLM vendor + TTS vendor, unnamed | `stt_minutes + llm_tokens + tts_characters` | **[EST]** | not measured | not measured | no official page retrieved |

## Per-minute formula

Do not fill the blanks with a remembered price.

```
cost_per_minute [EST] =
    stt_price_per_minute
  + (input_tokens + output_tokens) × token_price
  + tts_characters × character_price
```

`stt_price_per_minute`, `token_price`, and `character_price` are placeholders. Add a row only when the number is copied from an official pricing page, with the URL and the date it was opened. Until then the real-call row stays **[EST]** and the README does not quote a currency amount for a vendor.

Webhook retries add attempts, not a vendor fee, in this lab. A slow or failed tool still costs caller time. That time is on the simulated clock (timeout 300 ms per attempt, backoff capped at 500 ms, 3 attempts). It is not in the latency cohort, so it does not move the 950 ms p95.
