"""[EST] per-run cost for ~100 synthetic calls. Prices copied from official pages on 2026-10-19."""

from __future__ import annotations

from typing import TypedDict


class Scenario(TypedDict):
    calls: int
    turns: int
    audio_s: float
    in_tok: int
    out_tok: int
    cache: float
    tts_chars: int
    caller_chars: int


class Units(TypedDict):
    turns: int
    stt_min: float
    in_tok: int
    out_tok: int
    cache: float
    tts: int
    caller: int


SCEN: dict[str, Scenario] = {  # per run
    "low": {
        "calls": 100,
        "turns": 3,
        "audio_s": 2.5,
        "in_tok": 400,
        "out_tok": 45,
        "cache": 0.85,
        "tts_chars": 160,
        "caller_chars": 40,
    },
    "base": {
        "calls": 100,
        "turns": 4,
        "audio_s": 3.0,
        "in_tok": 700,
        "out_tok": 60,
        "cache": 0.70,
        "tts_chars": 190,
        "caller_chars": 50,
    },
    "high": {
        "calls": 100,
        "turns": 6,
        "audio_s": 4.5,
        "in_tok": 1200,
        "out_tok": 120,
        "cache": 0.0,
        "tts_chars": 300,
        "caller_chars": 70,
    },
}
CONT = 1.20  # 20% contingency for retries / rehearsal turns
STT: dict[str, float] = {  # USD per audio minute
    "xAI STT REST ($0.10/h)": 0.10 / 60,
    "xAI STT streaming ($0.20/h)": 0.20 / 60,
    "Deepgram Nova-3 Multilingual streaming PAYG ($0.0058/min promo)": 0.0058,
    "Deepgram Nova-3 Multilingual streaming PAYG list ($0.0092/min)": 0.0092,
    "ElevenLabs Scribe v2 Realtime ($0.39/h)": 0.39 / 60,
    "ElevenLabs Scribe v2 batch ($0.22/h)": 0.22 / 60,
    "OpenAI gpt-4o-mini-transcribe (~$0.003/min est. by OpenAI)": 0.003,
}
LLM: dict[str, tuple[float, float, float]] = {  # (input, cached, output) per 1M tokens
    "xAI grok-4.20-0309-non-reasoning": (1.25, 0.20, 2.50),
    "OpenAI gpt-4.1-mini": (0.40, 0.10, 1.60),
    "OpenAI gpt-5.4-mini": (0.75, 0.075, 4.50),
}
TTS: dict[str, float] = {  # USD per 1M chars
    "xAI TTS ($15/1M)": 15.0,
    "Deepgram Aura-2 ($0.030/1K)": 30.0,
    "ElevenLabs Flash/Turbo or v4 Turbo ($0.04/1K)": 40.0,
    "OpenAI tts-1 ($15/1M)": 15.0,
}


def units(scenario: Scenario) -> Units:
    turns = scenario["calls"] * scenario["turns"]
    return {
        "turns": turns,
        "stt_min": turns * scenario["audio_s"] / 60,
        "in_tok": turns * scenario["in_tok"],
        "out_tok": turns * scenario["out_tok"],
        "cache": scenario["cache"],
        "tts": turns * scenario["tts_chars"],
        "caller": turns * scenario["caller_chars"],
    }


out: list[str] = []
for name, scenario in SCEN.items():
    usage = units(scenario)
    out.append(f"\n## {name}: {usage}")
    for label, price in STT.items():
        out.append(f"STT | {label} | {usage['stt_min'] * price:.4f}")
    for label, (input_price, cached_price, output_price) in LLM.items():
        cost = (
            usage["in_tok"] * ((1 - usage["cache"]) * input_price + usage["cache"] * cached_price)
            + usage["out_tok"] * output_price
        ) / 1e6
        out.append(f"LLM | {label} | {cost:.4f}")
    for label, price in TTS.items():
        out.append(
            f"TTS | {label} | agent {usage['tts'] * price / 1e6:.4f} | "
            f"+caller synth {usage['caller'] * price / 1e6:.4f}"
        )
print("\n".join(out))
# bundles
B: dict[str, tuple[str, str, str]] = {
    "A all-xAI": (
        "xAI STT streaming ($0.20/h)",
        "xAI grok-4.20-0309-non-reasoning",
        "xAI TTS ($15/1M)",
    ),
    "B Deepgram STT+TTS, xAI LLM": (
        "Deepgram Nova-3 Multilingual streaming PAYG list ($0.0092/min)",
        "xAI grok-4.20-0309-non-reasoning",
        "Deepgram Aura-2 ($0.030/1K)",
    ),
    "C ElevenLabs STT+TTS, OpenAI LLM": (
        "ElevenLabs Scribe v2 Realtime ($0.39/h)",
        "OpenAI gpt-4.1-mini",
        "ElevenLabs Flash/Turbo or v4 Turbo ($0.04/1K)",
    ),
    "D lowest list (OpenAI STT+LLM+tts-1)": (
        "OpenAI gpt-4o-mini-transcribe (~$0.003/min est. by OpenAI)",
        "OpenAI gpt-4.1-mini",
        "OpenAI tts-1 ($15/1M)",
    ),
}
print("\n## bundles (caller audio synthesized offline = $0; then x1.2 contingency)")
for bundle_name, (stt_name, llm_name, tts_name) in B.items():
    row: list[str] = []
    for name, scenario in SCEN.items():
        usage = units(scenario)
        input_price, cached_price, output_price = LLM[llm_name]
        total = (
            usage["stt_min"] * STT[stt_name]
            + (
                usage["in_tok"]
                * ((1 - usage["cache"]) * input_price + usage["cache"] * cached_price)
                + usage["out_tok"] * output_price
            )
            / 1e6
            + usage["tts"] * TTS[tts_name] / 1e6
        )
        row.append(f"{name} {total:.3f} -> {total * CONT:.3f}")
    xai_part: list[str] = []
    for _name, scenario in SCEN.items():
        usage = units(scenario)
        xai_share = 0.0
        if stt_name.startswith("xAI"):
            xai_share += usage["stt_min"] * STT[stt_name]
        if llm_name.startswith("xAI"):
            input_price, cached_price, output_price = LLM[llm_name]
            xai_share += (
                usage["in_tok"]
                * ((1 - usage["cache"]) * input_price + usage["cache"] * cached_price)
                + usage["out_tok"] * output_price
            ) / 1e6
        if tts_name.startswith("xAI"):
            xai_share += usage["tts"] * TTS[tts_name] / 1e6
        xai_part.append(f"{xai_share * CONT:.3f}")
    print(bundle_name, "|", " | ".join(row), "| xAI share w/ cont:", xai_part)
