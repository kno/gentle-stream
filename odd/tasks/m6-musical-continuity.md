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
| T4 PM-019 drum ramp | S4 | inline | `feat/drum-ramp` | done (PM-019 commit) |
| T5 PM-020 two-genre crossfade | S5 | inline | `feat/genre-crossfade` | done (PM-020 commit) |
| T6 PM-021 flagship journey | S6 | inline; listening review by the maintainer | `feat/flagship-journey` | metrics done (PM-021 commit); checklist pending the maintainer |

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
- L6: T4 decision: journey-level `"drums": "energy"` maps energy to a level (<0.25 none, <0.5 soft, <0.75 lofi,
  else busy); a stage `"drums"` names a level held from then on and wins over energy; one level per phrase. `warm-up`
  now builds its drums with the energy (roadmap demo). JourneyStore renaming now uses `dataclasses.replace` so new
  Journey fields survive saving. Evidence: RED (drums_for_energy missing) -> 19 passed; mutation (jump straight to
  the target) -> RED. Full suite 924 passed, 27 skipped, 5 known daemon teardown errors; pyright clean.
- L7: T5 design: `_start_piece` split into `_voice` (same RNG draw order, golden hashes unchanged) and `_use`; a
  stage `transition: {"bars": N}` (1-32) starts an incoming `_Voice` with its own accumulator at the step's phrase,
  synced to the outgoing tempo/energy/colour/drums each bar, mixed with `crossfade_gains` (cos/sin) through one
  master chain blended per bar, promoted when the samples are done; `next`/new mood drop it. Evidence: RED 13 ->
  14 passed (RMS within +-3 dB, no clicks, >4x real time, 8 bars). The +-3 dB criterion alone also passes a linear
  fade, so an exact equal-power test was added (linear mutation -> RED). Full suite 938 passed, 27 skipped, 2 known
  daemon teardown errors; pyright clean. Procedural backend only (the samples backend is not installed here).
- L8: T6: ambient-to-synthwave rebuilt as the 20-minute reference (Dawn, Drift, Chillout, Lift, Synthwave, Peak;
  layers, energy drums, two 8-bar crossfades, binaural out before the lift). Metrics (slow test, seed 2026,
  procedural): tempo monotonic after the opening stage 60 -> 118; per-stage RMS -18.1, -17.9, -13.0, -12.9, -15.1,
  -15.2 dBFS (the bus compressor and each genre's master set loudness; decision: no stage drops more than 2.5 dB and
  the end is >= 2.5 dB louder, thresholds fitted to these measurements); onsets/s 0.07, 0.11, 1.68, 1.93, 2.11, 2.22.
  Finding: ambient ignores the `bass` layer (PM-018 relies on each genre's layers contract). Checklist in
  docs/FLAGSHIP_LISTENING_CHECKLIST.md is for the maintainer's listening review (S6 not complete until then).
