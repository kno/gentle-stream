# M9: Spoken phrases and full natural-language orchestration (PM-031 to PM-035)

One branch per PM, stacked on `feat/setup-voices`. Specs are the roadmap sections in
`docs/PROGRESSIVE_MUSIC_ROADMAP.md` ("### Milestone M9 — Spoken phrases and full natural-language orchestration"),
read verbatim before each task.

## Specs

**S1** — PM-031 acceptance (verbatim): "the clip starts exactly on a phrase-boundary sample; ducking ramps in and out
without clicks; a failing backend leaves the music untouched and the error is reported."
**S2** — PM-032 acceptance (verbatim): "phrases occur only in their stage, at most once per interval, on phrase
boundaries."
**S3** — PM-033 acceptance (verbatim): "options reach the backend command line exactly; unknown voices fall back with a
warning."
**S4** — PM-034 acceptance (verbatim): "position preserved per the rule; the diff of stages is printed in the CLI."
**S5** — PM-035 acceptance (verbatim): "overrides end at the stage boundary; the status line names them."

## Tasks

| Task | Specs | Route | Branch | Commit |
| :--- | :--- | :--- | :--- | :--- |
| T1 PM-031 TTS phrase layer | S1 | inline | `feat/tts-phrases` | done (PM-031 commit; base `f821ace`) |
| T2 PM-032 phrases in journeys | S2 | inline | `feat/journey-phrases` | done (PM-032 commit; base `2141704`) |
| T3 PM-033 voice characteristics | S3 | inline | `feat/speech-voices` | done (PM-033 commit; base `f496ba4`) |
| T4 PM-034 natural-language journey edit | S4 | inline | `feat/journey-edit` | done (PM-034 commit; base `d08f102`) |
| T5 PM-035 moods inside a journey | S5 | inline | `feat/journey-moods` | done (PM-035 commit; base `3b98de8`) |

## Log

- L1: User request (verbatim): "sigue" (after M8 was implemented; pushing the M8 branches is still unanswered, so they
  stay local).
- L2: PM-031 decisions: the clip is rendered synchronously in the daemon's per-connection thread (a worker, never the
  render thread), so `ctl say` reports a backend failure directly and nothing reaches the engine; the text goes to the
  backend on stdin, never as an argument (no option injection); `say -o FILE --data-format=LEI16@22050` on macOS,
  `espeak-ng -w FILE --stdin` on Linux; the clip is mixed after the master chain (like the binaural layer) so the bus
  compressor never pumps on it, centred, RMS-normalised and peak-limited; the music is ducked 3 dB with 50 ms linear
  ramps; text is limited to 200 characters.
- L3: T1 evidence: RED ImportError (no speech). GREEN 24 tests with fake `say`/`espeak-ng` executables on a private
  PATH (never the real program): say preferred, exact command lines, text only on stdin (an option-looking text stays
  text), no-backend and failing-backend messages, cache by text, length limits checked before the program runs,
  normalisation and peak limit, temporary WAV removed; in the engine the clip's first sample lands exactly on the
  boundary sample (queued after bars 1, 4 and 5 -> bars 4, 4, 8) with no change before it, the music held at -3 dB
  under a silent clip and back to full level after, linear ramps, two clips on consecutive boundaries, render_bar
  never runs TTS; daemon `say` queues on success and leaves the queue empty on failure; `ctl say` joins its words,
  reports the player's error, needs TEXT, and handles no player. All tests passed at the first run, so I mutated
  nine rules (boundary, duck, ramps, stdin, say format, backend order, daemon queueing, peak limit): each fails tests.
- L4: PM-031 full non-slow suite job-18 exited 0: 1204 passed, 3 deselected, 0 orphan daemons. T1 verified. Not done: hearing a real `say` phrase over the music.
- L5: PM-032: `Stage.phrases` (<= 12, 1-80 characters, whitespace collapsed) and `phrase_every` (10-3600 s, default 120;
  `phrase_every` without `phrases` is refused); round-trips through to_dict. Decisions: phrases are rendered ahead by
  `speech.prerender` in a background thread when the daemon (or the in-process player) starts the journey, delivered
  with `Engine.provide_phrase`; the engine checks on each phrase boundary: the playing stage's interval has passed since
  its last phrase (each stage counts from its own start), nothing is speaking or queued, and a clip is ready (else it
  skips; the music plays on). Choice: a dedicated generator seeded from the engine seed, so phrases never change the
  music's random draws and the order repeats for a seed; never the phrase just spoken unless the stage has one. The
  first prerender failure is logged once and stops the thread. The NL journey prompt offers phrases with the rule
  "never claim health, therapeutic or medical effects". RED 22 failed. One test expectation was my arithmetic error
  (10 s interval on 8 s boundaries gives 4 phrases in 64 s, not 5). Mutations: two survived (no-repeat rule, stage
  reset), so two tests were added (25 picks of two phrases must alternate; consecutive phrase stages); then every
  mutation (interval, repeats, stage reset, never speaks, shared rng, daemon prerender, phrases saved, stage index)
  fails tests. 24 tests pass; ruff/pyright clean (journey.py keeps its 9 pre-existing TRY004).
- L6: User: "sube y sigue": M8 branches and feat/tts-phrases pushed to fork (no PRs). PM-032 full non-slow suite job-19 exited 0: 1228 passed, 3 deselected, 0 orphan daemons. T2 verified.
- L7: PM-033: `ctl say --voice/--rate/--effect`, `ctl say --list-voices` (no player). say: `-v NAME -r WPM`; espeak-ng:
  `-v CODE -s WPM`, each a separate argument after the fixed ones, text still on stdin. Voices: `say -v ?` parsed
  as name (spaces allowed) and locale; `espeak-ng --voices` as language code and name; matched without case; an
  unknown voice is dropped before the program runs and a warning travels back in the player's answer and is printed
  to stderr (exit 0). Rate 80-400 wpm (usage error in the CLI, SpeechError in render). Effects dry, radio (band
  300-3400 Hz twice, tanh saturation), space (`mastering.procedural_ir` at 0.7, one channel, 0.6 send: the master
  reverb's impulse used as a send on the voice; the voice is mixed after the master chain so it cannot ride the
  music's own send). Caching split: `_speak` keeps the program's output per (text, voice, rate), `render` the
  processed clip per effect, so changing only the effect never reruns the program; `speech.clear_cache()` clears
  both. RED ImportError. My own test errors fixed: the fake signal had no in-band content (radio test meaningless),
  and the effect cache count. Real `say` check: Samantha resolves from "samantha", all three effects render (space
  adds ~2.2 s), and a WavFileWarning appeared on every say WAV (an extra chunk); `read_clip` now silences only that
  warning (RED/GREEN with a crafted WAV). 33 tests; 9 mutations (flags per program, case, unknown voice passed,
  rate check, space, radio, daemon resolution, names with spaces) each fail tests. Ruff/Pyright clean.
- L8: PM-033 full non-slow suite job-20 exited 0: 1261 passed, 3 deselected, 0 orphan daemons. T3 verified.
- L9: PM-034 `journey edit "CHANGE" [--yes]`. Decisions: the CLI asks the player for the journey it is running
  (`journey_current`, the engine's journey) rather than `journey_last`, which misses built-ins started by name; the
  model gets the journey JSON, the position ("stage 2 of 3 "Build", 0:40 into its 2:00 (1:40 into the journey)") and
  the same rules as `journey create` (moved to `bridge.journey_rules()`, shared). Position rule (`map_position`): same
  stage name, any case, keeps the seconds into it, held inside a shorter stage (99.9% of it); otherwise the same time,
  at most the new end. The engine applies it at the next bar (`queue_journey_edit`, refused without a running
  journey) keeping the start values; fields the edit newly owns stop gliding. The diff (`stage_diff`) is printed with
  a header and the position mapping before applying; a terminal is asked, no terminal needs `--yes` (exit 1
  otherwise), declining exits 0. The TUI is not changed (the roadmap lists app.py): `journey edit` works on the
  background player the TUI attaches to. Mistakes of mine found on the way: `journey_rules()` was inserted between
  `@dataclass` and the class it decorates (import error, fixed); the PM-032 prompt test read journey_from_prompt's
  code constants and broke with the refactor, now it checks the prompt actually sent; the M7/M8 import lines in
  engine.py were unsorted (fixed); a weak test of the start values (only the first stage ramps from them) let a
  mutation survive and was rewritten. RED ImportError; GREEN 21 tests; 10 mutations each fail tests. Ruff/Pyright
  clean on new code.
- L10: PM-034 full non-slow suite job-21 exited 0: 1282 passed, 3 deselected, 0 orphan daemons. T4 verified.
- L11: PM-035. Before it, a mood during a journey lost every change to a field the journey owns (the next bar took
  the journey's values: the "fighting" the roadmap names). Now, when a style is queued while a journey runs, each owned
  field the mood changes (compared with the playing style) becomes an offset from the journey's value, applied to the
  journey's values (clamped) for the rest of the stage; the rest of the mood applies directly as before and stays.
  Offsets are keyed by the running journey and stage, so they end at the stage boundary and on restart, skip or edit;
  a later mood in the same stage replaces only the offsets it changes; the name is the mood text, else the style name.
  The snapshot gains an optional `override` (name, offsets), additive in to_dict and tolerated missing from older
  players; the TUI journey line appends `mood "NAME": field +x.xx ... until "STAGE" ends`. Contract change pinned in
  tests/test_journey.py: the "style during a journey" case now expects the mood's bpm and energy (as offsets, named
  in the snapshot); the "next" case is unchanged; the snapshot key order gains "override". A bpm tolerance I first
  added was dead code (the engine and the model both round bpm to 0.1), shown by a surviving mutation, and removed.
  RED 7 failed / 3 passed (those three pin behaviour that already held); GREEN 10; 6 mutations each fail tests.
- L12: PM-035 full non-slow suite job-22 exited 0: 1292 passed, 3 deselected, 0 orphan daemons. T5 verified. M9 implemented; slow flagship tests run next.
