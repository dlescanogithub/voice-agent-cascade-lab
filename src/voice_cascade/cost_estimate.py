"""Offline [EST] cost for one live run. No network. Prices are list prices.

Copied from the planning note dated 2026-10-19. They are not a quote and not
a measurement. Decision D3 (which bundle to buy) stays open. The dry-run
default is the lowest list bundle, size L1 (100 calls x 1 turn), because that
is the cheapest planning point that still has n=100.
"""

from __future__ import annotations

PRICE_DATE = "2026-10-19"
CONTINGENCY = 1.20

# L1 base [EST]: 100 turns, 3.0 s audio, 700 in / 60 out tokens, 70% cached, 190 TTS chars.
L1_TURNS = 100
L1_AUDIO_S = 3.0
L1_IN_TOKENS = 700
L1_OUT_TOKENS = 60
L1_CACHE = 0.70
L1_TTS_CHARS = 190

# Bundle D, lowest list in the planning note. USD.
STT_USD_PER_MIN = 0.003
LLM_INPUT_PER_1M = 0.40
LLM_CACHED_PER_1M = 0.10
LLM_OUTPUT_PER_1M = 1.60
TTS_PER_1M_CHARS = 15.0


def bundle_d_l1_usd() -> tuple[float, float]:
    """Return ``(base, base_plus_contingency)`` for bundle D at L1. Both are [EST]."""

    turns = L1_TURNS
    stt = turns * L1_AUDIO_S / 60.0 * STT_USD_PER_MIN
    in_tokens = turns * L1_IN_TOKENS
    out_tokens = turns * L1_OUT_TOKENS
    llm = (
        in_tokens * ((1.0 - L1_CACHE) * LLM_INPUT_PER_1M + L1_CACHE * LLM_CACHED_PER_1M)
        + out_tokens * LLM_OUTPUT_PER_1M
    ) / 1e6
    tts = turns * L1_TTS_CHARS * TTS_PER_1M_CHARS / 1e6
    base = stt + llm + tts
    return base, base * CONTINGENCY


def dry_run_plan(max_spend_usd: float | None) -> dict[str, object]:
    """Cap check only. Does not read an API key and does not open a socket."""

    base, with_contingency = bundle_d_l1_usd()
    over = max_spend_usd is None or with_contingency > max_spend_usd
    return {
        "title": "SIMULATED dry-run cost estimate",
        "provenance": "[EST]",
        "bundle": "D lowest list (planning default, decision D3 open)",
        "size": "L1 100 calls x 1 turn (planning default, decision D1 open)",
        "caller_audio": "offline synthetic, 0 USD (planning default, decision D2 open)",
        "price_date": PRICE_DATE,
        "estimated_usd": round(base, 4),
        "estimated_usd_with_contingency": round(with_contingency, 4),
        "max_spend_usd": max_spend_usd,
        "over_cap": over,
        "request_sent": False,
    }
