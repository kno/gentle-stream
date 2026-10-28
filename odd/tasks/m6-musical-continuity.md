# M6: Musical continuity (PM-016 to PM-021)

One branch per PM, stacked on `feat/binaural-journeys`. Specs are the roadmap sections in
`docs/PROGRESSIVE_MUSIC_ROADMAP.md` ("### Milestone M6 — Musical continuity"), read verbatim before each task.

## Specs

**S1** — PM-016 acceptance (verbatim): "for every genre pair, the target key differs by ≤ 1 step on the circle of
fifths (or is the relative key); the last bar before the switch carries the pivot passing chord."
**S2** — PM-017 acceptance (verbatim): "the first bar of the new piece's motif equals the previous motif's head
transposed to the new key; default construction is bit-identical."
**S3** — PM-018 acceptance (verbatim): "a masked layer is absent from every planned bar of its stage; a mask change
applies on the first bar where `bar % 4 == 0`."
**S4** — PM-019 acceptance (verbatim): "drum style changes only on phrase boundaries and never skips more than one
level per phrase."
**S5** — PM-020 acceptance (verbatim): "RMS stays within ±3 dB across the transition; render speed stays > 4x real
time during it; no clicks at either end."
**S6** — PM-021 acceptance (verbatim): "metrics pass; checklist completed in the PR."

## Tasks

| Task | Specs | Route | Branch | Commit |
| :--- | :--- | :--- | :--- | :--- |
| T1 PM-016 harmonic handoff | S1 | inline | `feat/harmonic-handoff` | done (PM-016 commit) |
| T2 PM-017 motif across stages | S2 | inline | `feat/motif-continuity` | done (PM-017 commit) |
| T3 PM-018 layer entrances | S3 | inline | `feat/stage-layers` | done (PM-018 commit) |
| T4 PM-019 drum ramp | S4 | inline | `feat/drum-ramp` | pending |
| T5 PM-020 two-genre crossfade | S5 | inline | `feat/genre-crossfade` | pending |
| T6 PM-021 flagship journey | S6 | inline; listening review by the maintainer | `feat/flagship-journey` | pending |

## Log

- L1: User request: "sube y sigue m6".
- L2: PM-016 decision: a mode the target genre supports keeps key and mode; otherwise the target is the genre's most
  typical mode sharing the current pitch collection (distance 0 on the circle of fifths; all six modes are diatonic,
  so one always exists). The progression's degrees are kept, as genre steps already do.
- L3: T1 evidence: RED (harmonic_handoff missing) -> 105 passed (every genre pair x source mode x key lands on the
  relative collection, pivot B7 before C lydian -> E minor, supported mode keeps D minor with its pivot, no-journey plans
  unchanged). Mutation (pivot disabled) -> 2 RED. Full suite 885 passed, 27 skipped, 6 known daemon teardown errors;
  pyright clean. Not done: the roadmap's before/after WAV listening note (needs the maintainer's ears).
- L4: T2 evidence: RED 6 failed (next-keeps-fresh pinned green) -> green; default Composer plans unchanged and golden
  hashes pass; head carried in scale steps (realised in E minor), augmented x2 above a 1.5 tempo ratio, kept through
  later cycles, carried by a journey genre step. Full suite 892 passed, 27 skipped, 5 known daemon teardown errors;
  pyright clean. Native review assess unavailable (package-local binary missing).
- L5: T3 decision: `layers` switches hold across stages (like fields), every part starts on, unknown part names
  and non-boolean switches reject the journey; masking only removes parts the composer planned. Evidence: RED
  (LAYERS missing) -> 13 passed; mutations (apply off-boundary, no filtering) -> 4 RED each. The full suite caught a
  broken f-string brace in the new prompt line (fixed, pinned by a prompt test). Full suite 905 passed, 27 skipped,
  8 known daemon teardown errors; pyright clean.
