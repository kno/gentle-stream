# M7: Vocal textures (PM-022 to PM-026)

One branch per PM, stacked on `feat/flagship-journey`. Specs are the roadmap sections in
`docs/PROGRESSIVE_MUSIC_ROADMAP.md` ("### Milestone M7 — Vocal textures"), read verbatim before each task. M7 delivers
only sample-based or synthesized vocal instruments: no words, no singing synthesis, no text-to-song.

## Specs

**S1** — PM-022 acceptance (verbatim): "1. `voice=0` is bit-identical to the base commit for every genre. 2. With
`voice>0` the spectrum shows formant peaks near the vowel targets (e.g. "a": ~800 Hz and ~1200 Hz). 3. Old presets
without `voice` load with `voice=0`. 4. Render speed stays > 4x real time."
**S2** — PM-023 acceptance (verbatim): "the sampled path renders, is level-matched within ±3 dB of the procedural choir
at the same `voice`, and falls back to procedural without the soundfont."
**S3** — PM-024 acceptance (verbatim): "status shows backend and level; journey stages drive `voice`."
**S4** — PM-025 acceptance (verbatim): "pitch track (by autocorrelation) follows the planned melody within 30 cents at
note centres; portamento appears between notes ≤ 4 semitones apart."
**S5** — PM-026 acceptance (verbatim): "every harmony note on a strong beat is a chord tone; no parallel octaves with the
melody."

## Tasks

| Task | Specs | Route | Branch | Commit |
| :--- | :--- | :--- | :--- | :--- |
| T1 PM-022 procedural wordless choir | S1 | inline | `feat/wordless-choir` | done (PM-022 commit) |
| T2 PM-023 sampled choir | S2 | inline (FluidSynth tests skip without the soundfont) | `feat/sampled-choir` | pending |
| T3 PM-024 vocals in journeys and status | S3 | inline | `feat/vocal-status` | pending |
| T4 PM-025 wordless vocal melody | S4 | inline | `feat/vocal-melody` | pending |
| T5 PM-026 vocal harmonies | S5 | inline | `feat/vocal-harmonies` | pending |

## Log

- L1: User request: "lo he escuchado y suena bien, sube las ramas, sigue con el roadmap" (M6 closed, M7 next).
- L2: PM-022 decision: the choir keeps its own voice-leading centre (`piece.state`), so the genre's voicing and every
  random draw of the music stay as they are; the vowel follows the section ("a" in main sections, "o" in intro,
  breakdown and release).
- L3: T1 evidence: RED (no vocals module) -> 29 passed: formant peaks within 150 Hz of each vowel's F1/F2 on a G2 note,
  "a" at 800/1200 Hz, swell without click, cached notes, choir on upper chord tones in G3-G5 with voice leading,
  voice=0 never schedules the choir in any genre (golden hashes unchanged), every genre > 4x real time and below
  full scale with voice=1, old presets load with voice 0, prompt offers the field. The GLIDE_FIELDS set test was
  extended with `voice` (requested continuous field). Full non-slow suite 967 passed + that test; pyright clean.
  Not done: manual listening on ambient and lo-fi (roadmap manual check).
