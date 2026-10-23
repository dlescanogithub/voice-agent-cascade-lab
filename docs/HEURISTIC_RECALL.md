# Availability heuristic and handwritten recall

`unsupported_availability_claim` is a heuristic. It can miss a paraphrase and it can flag the wrong sentence. It does not replace a human read of the transcript. These notes are separate from the unit tests.

## What it flags

It flags a reply that offers a slot when that turn did not call a calendar or availability tool. Signals include:

- A clock time (`H:MM`, `3 pm`, `10am`). `15:00` is still a clock time. "for 15 hours" is not.
- A numeric date (`22/10`, `20/10/2026`) or a month date next to an appointment or a slot ("October 20", "on the 22nd", "for the 5th").
- A confirmation ("I booked you", "you're booked", "you're on the list", "I've reserved", "confirmed").
- A slot phrase ("opening", "book you", "available", "at 3 pm", "10am", "Tuesday"), or a weekday or "today" / "tomorrow" next to an offer.
- "you're booked" next to a day, "we can see you" next to a day, "free slot" next to a day, "put you down", "opening" next to an ordinal or "half past".
- "I've reserved" next to a day or an appointment, "fit you in" next to a day or "noon", "appointment is confirmed" next to a date, "scheduled your", "holding a spot for you".
- "I've blocked" with a day and noon or an appointment, "you're booked" with a day, "have a slot" with a day, and "on the calendar" with a day and a time.

## What it does not flag

- A negation ("I can't", "I don't have", "there is no", "we don't have").
- A general office range ("We are open Monday to Friday at 9:00").
- A cancellation or reschedule policy ("You can cancel up to 24 hours before").
- A medical duration or instruction ("The study requires an 8 hour fast", "fast for 10 hours", "an 8 hour fast", "fast for 12 hours", "the study lasts 8 hours", "rest for 24 hours", "absolute rest for 48 hours", "every 8 hours", "the procedure takes about 3 hours").

False negatives are possible (a paraphrase, "quarter past three", "every N hours" as a dose, a negation earlier in the same sentence). False positives are possible (a date that is not a slot, "in 2 hours" as a duration). A negation, a cancellation policy, or a medical duration can hide a later offer in the same sentence.

## Handwritten samples, 2026-10-17

Four fresh sets, each n=20 affirmative phrases plus a clean list, written by hand and separate from the unit tests. They were scored on the original Spanish phrase lists. Those lists are not reproduced here. The scores were not re-measured after the English rewrite, so they are not a score of the English patterns. Patches were written after seeing the misses in earlier sets, so the scores are not a before/after trial. The lists differ, n is small, and the intervals overlap, so 55%, 75%, 70%, and 80% are not an improvement over one another.

| Set | Scored on | Affirmative | Clean |
| --- | --- | --- | --- |
| Set 1 | Earlier fresh list, original Spanish phrases, 2026-10-17 | 11/20 (55%, about ±22 points at n=20) | 0/20 false positives |
| Set 2 | Heuristic after the 0.1.6 patterns, original Spanish phrases | 15/20 (75%) | 1/20 false positives (a medical fast read as a clock time) |
| Set 3 | Heuristic 0.1.7, original Spanish phrases | 14/20 (70%) | 1/20 false positives (a rest-for-24-hours instruction read as a clock time) |
| Set 4 | Heuristic 0.1.8, original Spanish phrases | 16/20 (80%, about ±18 points at n=20) | 0/20 false positives |

An earlier set, measured before the patterns in pull request 7, caught 14 of 20 claims and 1 of 18 clean sentences. That 14/20 is not set 3. Recall of the English patterns is not measured yet.
