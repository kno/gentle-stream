# Meter: 6/8 and 12/8 beside 4/4

Branch `feat/meter`, stacked on `feat/composition-variety`.

## Specs

**S1** — Maintainer: "lo que sea mejor" after choosing "Compás de 6/8 y 12/8": the pending part of the original
request ("si queremos hacer algo más pop, rock, heavy, baladas"), so that a ballad or a waltz can be in compound
meter instead of forcing every bar into four beats.

**S2** — A style names its meter: `"4/4"` (default), `"6/8"` or `"12/8"`, and the bar's length follows it
(`beats × 60 / bpm`, `bpm` counting the meter's own pulse: quarter in 4/4, eighth in 6/8 and 12/8). The field
round-trips, survives `variation`, and a style without it is exactly today's 4/4.

**S3** — The core composes in the meter's beats: melodies, bass, counter-melody, motif development, rhythm patterns
and the choir all count in that bar's beats, and phrase boundaries stay in bars (a 4-bar phrase is still 4 bars).
The engine's bar clock, the journey's phrase boundaries and the sung-phrase lookahead follow the same bar length.

**S4** — 4/4 renders sample-identical to the base for every genre: the meter is additive.

**S5** — Later phases (out of this branch unless the maintainer asks): each genre's own drum, bass and comping
patterns in compound time (a 6/8 ballad's lilting broken chords, a 12/8 shuffle), and the tempo ranges and mood
prompt hints that go with them. Until then, a genre's patterns keep their shape scaled into the bar (documented).

## Tasks

| Task | Specs | Route | Commit |
| :--- | :--- | :--- | :--- |
| T1 `Style.meter`, `beats`, `bar_seconds`; tests | S2, S4 | inline | done |
| T2 Composer and choir in the meter's beats; phrase boundaries in bars; tests | S3, S4 | inline | done |
| T3 Engine clock, journeys and the sung lookahead; a 6/8 render of every genre; README | S3, S4 | inline | pending |

## Log

- L1: "lo que sea mejor" → chose "Compás de 6/8 y 12/8" (the last pending item of the original request).

- L2: Measured the 4-beat assumptions before designing: 9 files (`composer.py`, `engine.py`, `vocals.py` and six
genre modules) hold the literal 4s (`4 * B`, `bar * 4`, `60 / bpm`, `% 4`).

- L3: Implemented: `Style.meter` + `Style.beats`; `Engine.bar_seconds = beats * 60 / bpm`; the composer counts the
bar's beats (`self.beats`, `self.k = beats/4` stretching a pattern written for four beats), the phrase-end note holds
the whole bar; the choir places its notes in the bar's beats; the genres that computed a bar (`BAR = 4 * B`) and the
bar-length effects (ballad's strings, dubstep's riser, electrohouse's build riser) now use `style.beats`. Left for the
next phase (S5): electrohouse's build and LFO progressions, which normalise by a literal 4, and every genre's own
rhythmic patterns (still four-beat shaped inside a longer bar).
- L4: the note that holds a phrase now lasts the whole bar (`self.beats`, not a literal 4).

- L5: Phase 2a (this branch): the ballad composes in the meter's groups of three — a broken chord over the bar's
  eighths in the verse, the chord on each half in the chorus, a side-stick and one hat per group in the drums, and
  4/4 keeps its exact pattern (golden hashes unchanged). Three mutants killed. Other genres still stretch a four-beat
  pattern: lofi, jazz's 12/8 shuffle and electrohouse's two literal 4s are the next slice.
