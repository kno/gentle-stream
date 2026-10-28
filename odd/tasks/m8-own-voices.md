# M8: Bring your own voices (PM-027 to PM-030)

One branch per PM, stacked on `feat/vocal-harmonies`. Specs are the roadmap sections in
`docs/PROGRESSIVE_MUSIC_ROADMAP.md` ("### Milestone M8 — Bring your own voices"), read verbatim before each task.
Rule (verbatim): "a repository license never automatically covers its audio. Every pack carries a manifest with its
license and source, and nothing without a verified redistributable license is fetched by gentle-stream."

## Specs

**S1** — PM-027 acceptance (verbatim): "a pack without `license` is refused with a clear message; pitch of shifted
notes within 10 cents; `voices list` prints license and attribution for every pack; FLAC/OGG produce "unsupported
format: convert to WAV"."
**S2** — PM-028 acceptance (verbatim): "renders the requested program; reports "FluidSynth is needed for SF2 voice
packs" without it."
**S3** — PM-029 acceptance (verbatim): "region selection by key and velocity matches a table of cases; sustain loops
hold notes longer than the sample without clicks."
**S4** — PM-030 acceptance (verbatim): "same guarantees as `setup-samples` (checksum mismatch leaves nothing behind;
idempotent)."

## Tasks

| Task | Specs | Route | Branch | Commit |
| :--- | :--- | :--- | :--- | :--- |
| T1 PM-027 WAV voice packs with licensing | S1 | inline | `feat/voice-packs` | done (PM-027 commit; base `d839203`) |
| T2 PM-028 SF2 voice packs | S2 | inline (FluidSynth installed) | `feat/sf2-voice-packs` | done (PM-028 commit; base `3438b79`) |
| T3 PM-029 SFZ subset | S3 | inline | `feat/sfz-voice-packs` | done (PM-029 commit; base `174033c`) |
| T4 PM-030 `setup-voices` for a CC0 pack | S4 | inline; needs network to inspect the archive (A6) | `feat/setup-voices` | done (PM-030 commit; base `d37026f`) |

## Log

- L1: User request (verbatim): "bien, sigue con el siguiente paso" (after accepting the M7 choir pad).
- L2: Context from M7 (odd/tasks/m7-vocal-textures.md L17-L21): the vocal melody (PM-025/026) is gated by
  `Engine.melodic_vocals` until a voice can sing melodies; the roadmap's M8 packs feed the vocal layer. Whether a pack
  is good enough to sing melodies is a listening decision, not something the code can decide.
- L3: PM-027 decisions. (a) Selection: `voices add` registers the folder and makes it active, `voices remove` returns
  to the built-in choir; `voices list` marks the active pack with `*` (the roadmap names a "selected pack" without a
  command). (b) `"melody": true` in `pack.json` sets `Engine.melodic_vocals`, so the listener decides by ear whether a
  pack sings the PM-025 melody. (c) Pitch: the roadmap's "limited to ±4 semitones ... notes outside the range use the
  nearest sample" cannot also keep every note in tune with sparse recordings (one recording leaves pitch classes 5-7
  semitones away). Notes always keep their pitch class: exact shifts up to 4 semitones, octave folding outside the
  recorded range, the smallest in-tune shift (at most 6) otherwise; both cases reported once in the log. (d) The engine
  never reads the registry: `render` and the daemon pass `voicepacks.active_voice()` (`render --procedural` passes
  none), so tests never depend on the user's config; the daemon test fixture now isolates XDG_CONFIG_HOME too.
- L4: T1 evidence: RED ImportError (no voicepacks). GREEN 51 tests: license refusal (message, exit 1, nothing
  registered), empty/non-text licenses, FLAC/OGG refusal with the exact message, 8/16/24-bit/float/stereo WAVs, pitch
  within 10 cents for shifts -4..+4 at 44.1 and 48 kHz files, nearest recording, octave folding and far shifts reported
  once, pitch class always kept, swell and end fade, add/list/remove/replace/missing-folder CLI output, help, engine
  choir sings the pack, melody flag, active pack fallback, render with and without --procedural. Two of my own
  thresholds (attack, end fade) were arbitrary and replaced by the exact ramp rules. Mutations (license check, sample
  rate conversion, FLAC/OGG refusal, attribution listing, octave folding) each fail tests. Ruff/Pyright clean on new
  code; existing files keep their previous ruff findings count.
- L5: PM-027 full non-slow suite job-14 exited 0: 1117 passed, 3 deselected, 0 orphan daemons. T1 verified.
- L6: PM-028: `pack.json` with `"sf2"` (relative to the pack or absolute), `"bank"` 0-16383 and `"program"` 0-127
  (default 0); license rules unchanged. FluidSynth availability is checked when the pack loads (`voices add`, the
  player), without loading the SoundFont: "FluidSynth is needed for SF2 voice packs (install the FluidSynth library and
  the samples extra: uv sync --extra samples)". The renderer loads lazily on the first note through the shared
  `samples.load_renderer` (one per file). Notes render at a fixed `SF2_VELOCITY` 80, the same velocity the reference
  note used by `samples._program_level` is measured at. RED 11 failed / 1 passed (the license rule already held).
  While matching levels I found that PM-027's `note()` peak-limited each note to 1 after RMS matching, which made a
  recorded choir 3.75 dB quieter; removed (the choir's 0.12 gain and the master limiter handle peaks, as for the
  soundfont's own notes). Measured SF2 program 52: middle C 0.0 dB, other notes -3.5..+2.6 dB (the instrument's own
  variation). GREEN 63 voice-pack tests; mutations (FluidSynth check, requested program, relative path, bank/program
  range, level matching) each fail tests. Ruff/Pyright clean.
- L7: PM-028 full non-slow suite job-15 exited 0: 1129 passed, 3 deselected, 0 orphan daemons. T2 verified.
- L8: PM-029: new `sfz.py` (parse and select only; `PackVoice` plays). Decisions: the choir asks regions for velocity 80
  (`NOTE_VELOCITY`, shared with SF2); the first region in file order that plays the note wins (as SFZ players pick one
  layer); a note no region plays is sung by the nearest key zone, reported once; loop points without `loop_mode` loop;
  without `ampeg_release` the choir's 0.4 s release applies (SFZ's own default, 1 ms, would click on a pad); level
  matching uses the region nearest middle C before its `volume`, so `volume` keeps its relative meaning. RED
  ImportError (no sfz). Found and fixed in my own tests: `tune=-50` lowers the playback (the test had it raising), and
  two tests that could not fail: the loop fixture joined at a zero crossing where any join looked smooth (moved to a
  crest with silence after loop_end), and the region table had no overlapping case for "first match wins" (added
  69 @ 90). GREEN 31 SFZ tests (94 with the other voice-pack tests); mutations (loop join, no wrap, tune sign, volume,
  global inheritance, key=, first match, default looping, block comments) each fail tests. Ruff/Pyright clean.
- L10: PM-030 archive inspection (A6), done without extracting to disk: FreePats publishes Synth Pad Choir only as `.7z`
  (SF2, SFZ+FLAC, SFZ+WAV) at github.com/freepats/synth-pad-choir/releases/download/2020-05-16/. SFZ+WAV edition:
  10.1 MB, SHA-256 19f94afc8aed5e120b444da668a51a1737a1e87b772ae93b495d0fc42ff92a16, 17 entries: LICENSE.txt (full CC0
  1.0 legal code), README.txt (CC0; samples by 快乐爱的小精灵 (Elf of Happy and Love) <lovebodhi@yandex.com>, ZynAddSubFX, edited by
  roberto@zenvoid.org), one .sfz and 12 WAV samples (C and F# from C2 to F#7). The .sfz uses only supported opcodes
  (lokey, hikey, pitch_keycenter, loop_start, loop_end, sample; global ampeg_release=2, loop_mode=loop_continuous).
  Python's standard library cannot extract 7z: a decision is needed between a new dependency and a system tool.
- L9: PM-029 full non-slow suite job-16 exited 0: 1160 passed, 3 deselected, 0 orphan daemons. T3 verified.
- L11: User chose "Con una herramienta del sistema (recomendado)" for 7z extraction: `bsdtar` (macOS built-in, Linux
  libarchive-tools) or `7z`, no new Python dependency. User asked to re-check the web ("vuelve a consultar la web"):
  the FreePats page and the GitHub release (2020-05-16, published 2024-07-11; GitHub lists no digest) are unchanged; a
  fresh download has the pinned SHA-256. A local probe confirmed bsdtar 3.5.3 creates and extracts 7z with spaces in
  paths (the test fixture builds a FreePats-shaped archive that way; tests skip without bsdtar).
- L12: PM-030 in new `voicesetup.py`: CATALOG with the pinned URL and SHA-256; reuses `samples._download` (verified
  before extraction); listing checked before extraction (absolute paths, `..`, drive letters, stray top-level entries,
  non SFZ/WAV/text files refused); extracted into a private `.partial-` staging folder; symlinks and special files
  refused; LICENSE.txt and one .sfz required; the pack must load; pack.json and LICENSES.txt (source, checksum,
  credit, the archive's LICENSE.txt and README.txt in full) written; moved into place, then registered and made
  active. RED ImportError. A new test (registry write fails after the move) exposed a bug in my cleanup: it checked
  `installed()`, which is already true after the move, so the half-installed pack stayed; fixed with an explicit
  `moved` flag. GREEN 20 tests; mutations (listing check, top-folder check, LICENSE required, pack validation,
  idempotency, staging cleanup, final cleanup) each fail tests. End-to-end against the real archive in a temporary
  XDG dir: installed with 12 regions, second run "already installed" without downloading, render OK.
- L13: PM-030 full non-slow suite job-17 exited 0: 1180 passed, 3 deselected, 0 orphan daemons. T4 verified; M8 implemented. Not pushed. Not done: listening to the FreePats choir and any voice pack marked `"melody": true`.
