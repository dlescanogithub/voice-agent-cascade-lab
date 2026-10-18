# Adapt this to a real client

Throw these away or replace them before any real caller hits the process. Keep the gate.

1. **Replace the argument binding.** Today the script inserts the slot id. A real model must emit arguments, and the webhook must reject ids that were not in the last `find_slots` result.
2. **Replace the cassette** with a model call behind the same `plan` shape. Keep the clinical guard in your code, not only in the prompt.
3. **Measure one speech service, one language endpoint, and one synthesis service** with `python -m voice_cascade live` outside CI. Paste the wall-clock rows into the README table. Until that table has rows, do not quote the 1004.5 ms figure as a provider result. It is a SIMULATED placeholder.
4. **Put idempotency in front of the real calendar** if that calendar has no key of its own. Keep the unique "one active booking per slot" constraint.
5. **Pick a VAD on real audio.** The energy thresholds here are for synthetic frames. Aggressive is already a known fail on the false-cut invariant.
6. **Add consent and telephony only after discovery question 6 and a named escalation queue.** They are design-only in this repo.
7. **Delete the demo HMAC** and set `VOICE_CASCADE_HMAC_SECRET` out of band. Do not commit the value.
8. **Re-run the invariant suite** against recorded calls with fake provider playback (cassettes of the real model, not a live call inside CI). Add cases for the client's phrases. Do not switch the gate to exact tool-call equality.

If the client wants a second intent, clone the pattern: one cassette, one allowed-effect list, one new invariant. Do not fold a pharmacy or a telecom desk into the Aurora gate without that work.
