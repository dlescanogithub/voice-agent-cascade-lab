# Silero VAD (optional marker)

The energy backend is what `eval` and CI run. It has no extra dependency.

`voice-agent-cascade-lab[vad]` is declared and **empty** in 0.2.1. Installing the base package does not install torch and does not download weights. `load_silero` raises before any import of a model:

- Flag unset or not `1`: "off by default".
- Flag `VOICE_CASCADE_ENABLE_SILERO=1`: still refuses, and still does not download weights.

That flag is off in tests. A test checks both refusals. There is no CI job for a neural VAD, because this repo does not change `.github/` for it. Decision D4 (a PR job versus manual only) stays open. The default is manual only.

The state machine calls `speech_prob` only. A future Silero backend would plug in there. This page does not claim that backend has been measured.
