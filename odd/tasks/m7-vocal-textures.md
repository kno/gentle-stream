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
| T4 PM-025 wordless vocal melody | S4 | inline | `feat/vocal-melody` | done (PM-025 work-unit commit; base `d61af53`) |
| T5 PM-026 vocal harmonies | S5 | inline | `feat/vocal-harmonies` | done (PM-026 work-unit commit; base `0a50b86`) |

## Log

- L24: Rerun job-13 exited 0: 1066 passed, 3 deselected, 0 orphan daemons after the run. M7 closed; branches pushed to fork.

- L23: Full suite job-12 (after the M8 gate) exited 1 after 19m43s: 1058 passed, 8 failed, all `PlayerError: the player did not start in time` in tests/test_main.py. Load average was 64: an Apple Virtualization VM plus 37 orphaned `gentle_stream daemon` processes, all with XDG_RUNTIME_DIR=/tmp/gs-* (test daemons, 4-25 h old, from earlier interrupted runs: daemons start in their own session and survive a killed pytest). Orphans killed (load fell to 8.7). The 8 tests pass alone (27 selected passed); test_daemon, test_main, test_app and test_daemon_cleanup each leave no orphan. Rerun job-13.

- L22: Maintainer on the choir pad (listen/pad.wav): "bien, sigue con el siguiente paso". M7 accepted: choir pad (PM-022/023) and status/journeys (PM-024) active; vocal melody and harmonies (PM-025/026) implemented and gated until an M8 melodic voice.

- L21: PM-025 gate (on feat/vocal-melody): `Engine.melodic_vocals` (False until an M8 voice pack provides a melodic voice) is passed to `vocals.instrumental_plan` and `vocals.schedule`; without it the genre keeps its lead and the choir pads at any `voice`. RED 5 failed -> GREEN 82 passed across the vocal test files; the PM-023 level test's melody case now enables the melodic voice explicitly (its melody-level mutation still fails a test). Removing the gate fails 3 tests. README states that melody mode waits for a voice pack.

- L20: User chose "Dejarlas a la espera de M8 (recomendado)": keep the PM-025/026 code and tests, but melody mode only runs when the engine has a melodic voice (a future M8 voice pack). Until then the choir is always a pad, whatever `voice`, and the genre lead is never replaced. The gate lands on `feat/vocal-melody` and is merged (no rewrite) into `feat/vocal-harmonies`.

- L19: Maintainer: 3b and 3c "demasiado metálicos ambos"; raw FluidSynth Choir Aahs an octave lower (stem 5, no processing) "si, aunque menos". Conclusion: the FluidR3_GM choir is itself metallic (looped GM samples; roadmap risk A5); skipping the attack (loop region only) and vibrato on a chorused sample make it worse. Samples exist every three semitones across the range, so it is not sample stretching. A real vocal melody needs better voice sources (M8). Decision on PM-025/026 pending.

- L18: Maintainer (verbatim): "4 tiene como un ruido de fondo. 3 es la que más parece una voz, pero muy chillona en las notas altas". Direction: Choir Aahs read past its attack (stem 3); procedural aah with breath rejected. Measured cause of shrillness: register, not timbre: the composer's melody spans MIDI 65-89 (p10/p50/p90 71/79/85); the Choir Aahs spectral centroid stays 1.6-2.2 kHz across pitches. Two variants rendered: 3b an octave lower, 3c an octave lower plus 3.5 kHz low-pass. Awaiting the maintainer's pick.

- L17: Maintainer listening (verbatim): "la melodía de melody.wav no parecen voces". Diagnosis: the sampled melody sings GM 53 Voice Oohs for the "o"/"u" vowels (flute-like in FluidR3_GM); GM 52 Choir Aahs has a 0.37 s attack to half level, longer than many melody notes (0.42-0.83 s); vibrato 18 cents from 300 ms is inaudible on short notes; no breath on melodic notes. Four melody-only comparison stems rendered by the untracked script `listen/compare_melody.py` (current sampled, current procedural, Choir Aahs read past its attack, procedural open "a" with 40-cent vibrato from 150 ms and onset breath). PM-025 acceptance reopened pending the maintainer's choice.

- L16: Full non-slow suite job-11 exited 0: 1063 passed, 3 deselected. T5 verified. M7 implemented; pending: the maintainer's listening pass (choir pad, vocal melody, harmonies) and pushing the five M7 branches.

- L15: PM-026 decisions: "high energy" = plan energy >= 0.7 for one part (the composer's COUNTER_ENERGY) and >= 0.9 for
  two (measured: style energy 0.5 gives B 0.80 and B' 0.95; 0.2 never reaches it). Each harmony note keeps the melody
  rhythm and takes the chord tone below the voice above at the first interval in (3, 4, 8, 9, 5, 7, 6, ...), never the
  melody's pitch class. This follows the melody in parallel thirds/sixths instead of reusing `Composer._nearest` (the
  roadmap's hint), because nearest-pitch search can pick a second or a tone above the melody. Parts panned -0.45/+0.45,
  0.55x the melody gain, high-passed at 180 Hz (roadmap risk: muddiness). RED: ImportError (no harmony_parts). GREEN:
  16 harmony tests + 91 across the vocal files. Mutations (non-chord tones, melody pitch class, part cap, high-pass)
  each fail tests; the high-pass mutation first survived, so a filter test was added. Ruff and Pyright clean.

- L14: Full non-slow suite job-10 exited 0: 1047 passed, 3 deselected (slow flagship tests; the flagship journey sets no voice). T4 verified; PM-026 next. Not done: manual listening of the vocal melody (roadmap demo `ctl glide voice=0.8` on lo-fi).

- L13: Full non-slow suite job-9 exited 1: 1042 passed, 2 failed. The PM-023 level test ran at voice 0.6, which PM-025 turns into melody mode; sampled melody was up to 4.7 dB quieter (procedural notes were peak-normalised, sampled ones scaled by the pad reference RMS). Test split into pad (0.4) and melody (0.6) cases; RED 2 failed (lofi, ambient melody). Fix: both melodic backends scaled to one `melody_rms` reference after the glide. GREEN 79 passed across the vocal test files; measured melody differences -2.6..+1.7 dB, pad unchanged (-0.2..-1.6 dB). Removed an unused `noqa` I added in PM-023. Ruff and Pyright clean on touched files. Remaining pi-lens reports (bridge.py I001, client.py SIM105, engine.py I001) exist on lines this work did not change and the project ruff config does not flag them; left alone. Full suite job-10 running.

- L12: PM-025 RED: 20 failed before implementation. GREEN: 20 passed on both sampled and procedural paths (autocorrelation at note centres <30 cents, close-note pitch slides, threshold and engine routing); Pyright clean, fresh seven-path LSP probe clean. Added 90 ms variable-rate sampled portamento, procedural equivalent, delayed vibrato, connected-note state, four-bar vowel choice, and lead masking on outgoing/incoming engine paths. README documents the requested behavior change. Full non-slow suite job-9 running; no completion or commit yet.

- L11: User selected "1" for PM-025 backend: sampled when available, procedural fallback, with pitch processing. Preserve the sampled choir timbre for melody; do not silently switch sampled melody to procedural. PM-025 replaces the genre lead at voice >= 0.5 when that layer plays, with 60–120 ms portamento for close connected notes, delayed vibrato and phrase vowels. Work-unit base: d61af53.

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
