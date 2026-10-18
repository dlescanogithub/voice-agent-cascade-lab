# Availability heuristic and handwritten recall

`unsupported_availability_claim` is a heuristic. It can miss a paraphrase and it can flag the wrong sentence. It does not replace a human read of the transcript. These notes are separate from the unit tests.

## What it flags

It flags a reply that offers a slot when that turn did not call a calendar or availability tool. Signals include:

- A clock time, "N hs", "N horas", "a las N", or a Spanish hour ("diez", "tres de la tarde"). "las 15 horas" is still a clock time.
- A date ("el 20 de octubre", "el 22", `20/10`).
- A confirmation ("agendé", "agendada", "te reservé", "confirmado").
- An English slot ("opening", "book you", "available", "at 3 pm", "10am", "Tuesday"), or a weekday / "hoy" / "mañana" next to an offer.
- "quedaste con" next to a day, "we can see you" next to a day, "free slot" next to a day, "put you down", "opening" next to an ordinal or "half past".
- "reservé" next to a day or "cita", "fit you in" next to a day or "noon", "appointment is confirmed" next to a date, "scheduled your", "holding a spot for you", "I've reserved".
- "I've blocked" with a day and noon or an appointment, "you're booked" with a day, "have a slot" with a day, and "on the calendar" with a day and a time.

## What it does not flag

- A negation ("no puedo", "no tengo", "no hay", "I can't", "we don't have").
- A general office range ("Atendemos de lunes a viernes a las 9").
- A cancellation or reschedule policy ("Podés cancelar hasta 24 horas antes", "You can cancel up to 24 hours before").
- A medical duration or instruction ("El estudio requiere ayuno de 8 horas", "ayunar por 10 horas", "an 8 hour fast", "fast for 12 hours", "el estudio dura 8 horas", "guardá reposo por 24 horas", "reposo absoluto por 48 horas", "cada 8 horas", "rest for 24 hours", "the procedure takes about 3 hours").

False negatives are possible (a paraphrase, "quince y media", "cada N horas" as a dose, a negation earlier in the same sentence). False positives are possible (a date that is not a slot, "en 2 horas" as a duration). A negation, a cancellation policy, or a medical duration can hide a later offer in the same sentence.

## Handwritten samples, 2026-10-17

Four fresh sets, each n=20 affirmative phrases plus a clean list, written by hand and separate from the unit tests. Patches were written after seeing the misses in earlier sets, so the scores are not a before/after trial. The lists differ, n is small, and the intervals overlap, so 55%, 75%, 70%, and 80% are not an improvement over one another.

| Set | Scored on | Affirmative | Clean |
| --- | --- | --- | --- |
| Set 1 | Earlier fresh list | 11/20 (55%, about ±22 points at n=20) | 0/20 false positives |
| Set 2 | Heuristic after the 0.1.6 patterns | 15/20 (75%) | 1/20 false positives (a medical fast read as a clock time) |
| Set 3 | Heuristic 0.1.7 | 14/20 (70%) | 1/20 false positives ("guardá reposo por 24 horas" read as a clock time) |
| Set 4 | Heuristic 0.1.8 | 16/20 (80%, about ±18 points at n=20) | 0/20 false positives |

An earlier set, measured before the patterns in pull request 7, caught 14 of 20 claims and 1 of 18 clean sentences. That 14/20 is not set 3. Recall after the patterns in the current release is not measured yet.
