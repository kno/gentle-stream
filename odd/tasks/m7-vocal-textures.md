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
| T2 PM-023 sampled choir | S2 | inline | `feat/sampled-choir` | done (`226de88`; separate cleanup `ca1601f`) |
| T3 PM-024 vocals in journeys and status | S3 | inline | `feat/vocal-status` | done (PM-024 work-unit commit; base `226de88`) |
| T4 PM-025 wordless vocal melody | S4 | inline | `feat/vocal-melody` | pending |
| T5 PM-026 vocal harmonies | S5 | inline | `feat/vocal-harmonies` | pending |

## Log

- L10: PM-024 full non-slow suite job-6 exited 0: 1024 passed, 3 deselected. Eight-path LSP clean and three focused tests passed. Native assessment remains unavailable (package-local-binary-missing), not approved. Work-unit review boundary is 226de88..HEAD, not the accumulated stack. T3 verified; PM-025 next.

- L9: PM-024 adds audible vocal level/backend to daemon state, local/remote player backend access, a TUI line hidden at zero, and a wordless-choir explanation in the journey prompt. Journey voice interpolation already uses GLIDE_FIELDS. Initial RED: two failed, one passed. After implementation and deterministic TUI setup: three passed; fresh LSP checks on eight paths found no errors. README updated. Full non-slow suite job-6 running; no completion or commit yet.

- L8: Full non-slow suite job-4 exited 0: 1021 passed, 3 deselected. Separate teardown fix committed as ca1601f. PM-023 work-unit boundary is fffd942..HEAD on feat/sampled-choir, excluding the isolated teardown commit; earlier M6/M7 work belongs to preceding stack branches, not this review slice. Native assessment unavailable (package-local-binary-missing); no review approval claimed. PM-023 focused tests and Pyright passed; slow tests excluded. T2 verified; T3 is next.

- L7: User authorized fixing the teardown separately: "do it". Added a deterministic fixture regression for a daemon exiting between the liveness probe and SIGKILL, alongside normal cleanup coverage. RED: 1 failed, 1 passed; GREEN: 2 passed. Cleanup now suppresses only ProcessLookupError from SIGKILL, leaving production daemon code unchanged. Full non-slow suite job-4 running; separate cleanup commit pending successful verification.

- L5: User confirmed installation: "ya está instalado y ejecutado el setup-samples". FluidR3_GM renderer loaded successfully. PM-023 focused checks: 53 passed; sampled/procedural level differences measured from -0.2 to -1.6 dB across five genres. A +12 dB mutation caused all three level tests to fail and was removed. Pyright exited 0 with no errors or warnings.
- L6: Full non-slow suite (job-2) exited 1: 1019 passed, 3 deselected, six teardown errors from ProcessLookupError at tests/test_daemon.py:108. No clean full-suite result; PM-023 remains open pending the user's decision on addressing this previously observed teardown problem. README describes sampled selection and procedural fallback. Slow tests were excluded. No PM-023 commit or push yet.

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
- L4: FluidSynth library and soundfont are missing here; user chose "Lo instalo yo y me avisas" (they run `brew install fluid-synth` and `uv run gentle-stream setup-samples`, then PM-023 is implemented and verified).
