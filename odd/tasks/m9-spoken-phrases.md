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
| T2 PM-032 phrases in journeys | S2 | inline | `feat/journey-phrases` | pending |
| T3 PM-033 voice characteristics | S3 | inline | `feat/speech-voices` | pending |
| T4 PM-034 natural-language journey edit | S4 | inline | `feat/journey-edit` | pending |
| T5 PM-035 moods inside a journey | S5 | inline | `feat/journey-moods` | pending |

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
