# M10: Open sessions, and everything from the TUI (PM-036 to PM-044)

One branch per PM, stacked on `feat/journey-moods`. Specs are the roadmap sections in
`docs/PROGRESSIVE_MUSIC_ROADMAP.md` ("### Milestone M10"), read verbatim before each task.

## Specs

**S0** — User requirement (verbatim): "hasta ahora hay muchas cosas que se pueden hacer desde la línea de comandos,
pero hay que hacer que todo se pueda hacer desde la TUI".
**S1-S9** — the acceptance criteria of PM-036 to PM-044 in the roadmap, quoted verbatim there.

## Tasks

| Task | Specs | Route | Branch | Commit |
| :--- | :--- | :--- | :--- | :--- |
| T0 M10 plan in the roadmap | S0 | inline | `docs/m10-plan` | done (`a35fe49`) |
| T1 PM-036 record the session | S1 | inline | `feat/session-record` | done (PM-036 commit; base `docs/m10-plan`) |
| T2 PM-037 open-ended stages | S2 | inline | `feat/open-stages` | done (PM-037 commit; base `4347a90`) |
| T3 PM-038 point-list curves | S3 | inline | `feat/point-curves` | done (PM-038 commit; base `10c82c5`) |
| T4 PM-039 journeys from the TUI | S4, S0 | inline | `feat/tui-journeys` | done (PM-039 commit; base `a886ff7`) |
| T5 PM-040 live controls from the TUI | S5, S0 | inline | `feat/tui-controls` | done (PM-040 commit; base `a5b5c64`) |
| T6 PM-041 binaural from the TUI | S6, S0 | inline | `feat/tui-binaural` | done (PM-041 commit; base `ef9030e`) |
| T7 PM-042 spoken phrases from the TUI | S7, S0 | inline | `feat/tui-say` | done (PM-042 commit; base `fdbd512`) |
| T8 PM-043 voices and samples from the TUI | S8, S0 | inline | `feat/tui-voices` | done (PM-043 commit; base `418280a`) |
| T9 PM-044 render and the parity guard | S9, S0 | inline (worker attempt discarded) | `feat/tui-render` | done (PM-044 commit; base `7706d20`) |

## Log

- L1: User (verbatim): "sigue con el roadmap, dime lo que propones". Proposal: M10 from section 8 (session recording,
  open-ended stages, point-list curves, TUI journey edit); singing synthesis deferred to a license study.
- L2: User (verbatim): "si, hasta ahora hay muchas cosas que se pueden hacer desde la línea de comandos, pero hay que
  hacer que todo se pueda hacer desde la TUI". M10 widened: TUI parity for journeys, live controls, binaural, speech,
  voices/samples and render, with a parity guard test. Inventory (2026-10-28): the TUI covers play/pause/next/stop,
  volume, moods, model, presets, journey create/pick/restart/skip/stop; it lacks tempo/glide, binaural, say, journey
  edit/save/delete/show/validate, voices, setup-voices, setup-samples, render (and the new record). UX: frequent
  actions keep a key, every action goes into Textual's command palette (Textual 8.2.8 has it built in).
- L3: User chose "Teclas para lo frecuente + paleta (recomendado)": frequent actions keep a key, every action is in the command palette (ctrl+p).
- L4: PM-036. `recorder.py`: the audio callback queues a copy of each block (never touches the disk); a writer thread
  saves them in order and rewrites the WAV header sizes after every block, so the file is valid at any moment (a
  crash loses at most the queued blocks). What is recorded is what the device was given: volume and pause silence
  included (the acceptance criterion as written). Player.record_start/stop/recording; close() saves the recording.
  Daemon record_start (absolute paths only: the daemon runs from /; the CLI resolves) / record_stop, state
  "recording". `ctl record start FILE [--force]` / `ctl record stop`. TUI: `r` opens RecordDialog (dated file in the
  home folder proposed; errors shown in the dialog), `r` again stops; the state line shows `● REC m:ss`. The command
  palette (ctrl+p, GentleCommands over StreamApp.palette_actions) starts here with every current action; a test keeps
  every visible key action in it. The `--help` key list was missing j and J (fixed with r and ctrl+p). My own mistake:
  the first `drain()` waited for an empty queue, which does not mean written; it now waits for a marker the writer
  reaches. RED ImportError (both test files); GREEN 24; 7 mutations each fail tests. The new RecordDialog BINDINGS
  list repeats the file's existing RUF012 pattern.
- L5: PM-036 suite job-24 failed one test I had left stale (the state key order test lists the last keys; `recording` is appended last as its rule says); fixed. A daemon left after that run was not a test daemon (no private XDG_RUNTIME_DIR, started near the end): the user's real player, left alone. Rerun job-25: 1316 passed, 3 deselected, 0 test daemons left. T1 verified.
- L6: PM-037. An open stage is `Stage(seconds=inf, ramp=R)` ("seconds": "open", "ramp" 10-14400, default 120):
  progress is measured over the ramp (`Stage.span`), so values reach their targets and hold; cumulative ends after it
  are infinite, so later stages wait. Skip on an open stage closes it where it is (`Journey.closed(index, seconds)`)
  and the next stage starts from the bar after. Snapshot gains `open` (this stage) and `open_ahead` (a later one), the
  TUI shows "open"/"open-ended", `journey list` "open-ended", `stage_diff` "open (ramp N s)", the edit CLI's clock
  "open". The NL rules offer it. Open stages are excluded from the 43200 s total. Regression I introduced and fixed:
  I had extended the PM-007 error message for invalid seconds with `or "open"`, which broke four PM-007 tests pinning
  the exact text; the original message is kept. Mutation work: updating the engine's driving journey on close had no
  observable effect (same fields, identity never compared) and was removed; the open-stage target tempo was untested
  (my first test had one stage, where "at infinity" lands in the same stage) and is now tested with a later stage.
  RED 15 failed; GREEN 16; the snapshot key-order test gains "open", "open_ahead".
- L7: User asked whether sound and the whole screen could go to a streaming service such as YouTube; after three
  options were described, user (verbatim): "añadelo al roadmap, pero solo la opción 3, dependerá de librerías nuevas
  y de configuración de api keys, seguramente". Added as M11 / PM-045 in commit f86d809 (on feat/open-stages, before
  the PM-037 commit): the player renders its own broadcast view and feeds an RTMP(S) encoder. Clarified: YouTube Live
  ingest needs a stream key, not an API key; OAuth/Data API out of scope. Encoder, frame drawing dependency and public
  content rules recorded as open decisions; nothing implemented.
- L7: User: "pues adelante". PM-037 suite job-26: 1332 passed, 3 deselected, 0 test daemons. T2 verified.
- L8: PM-038. `curve_points` validates a point list (2-16 [progress, fraction] pairs, both 0-1, progress strictly
  increasing, from [0, 0] to [1, 1]) and names the offending point; `Stage.curve` is a name or a tuple of points;
  `shape` interpolates linearly between points (bisect, no numpy in journey.py); to_dict writes lists; stage_diff
  says "N points"; the journey rules offer it. Named curves and the unknown-name warning are unchanged (the two tests
  pinning them passed in RED). The README had never documented the named curves (PM-009); now both forms are. My
  slips: numpy is not imported in journey.py (first GREEN attempt failed); my own error-message regex did not match
  my message. RED 19 failed / 2 passed; GREEN 21; 6 mutations each fail tests. One new TRY004 (ValueError for a
  bad type) follows the parser's convention: its callers catch ValueError.
- L9: PM-038 suite job-27: 1353 passed, 3 deselected, 0 test daemons. T3 verified.
- L10: PM-039. `journey.edit_preview` computes what `journey edit` shows (position for the model, header, stage
  diff, landing) and both the CLI and the TUI use it; it measures the position over the stage's span, which also fixes
  a latent PM-037 bug in the CLI (seconds into an open stage were computed from an infinite length). TUI: journey menu
  gains Edit with words (JourneyEditModal: the model runs in a worker, the diff is shown, Apply enabled only with a
  valid answer, Esc cancels) and Save as (the running journey via journey_current, with its edits; SaveDialog gains a
  heading). Picker: `v` shows (JourneyShowModal, the `journey show` JSON), `d` deletes a saved journey (built-ins
  refused), and "Open a journey file" (JourneyFileModal: files only, validated with `_journey_source`, errors stay in
  the dialog; then JourneyShowModal with warnings, Play and Save as). Palette gains the three actions. The open option
  goes last: the PM-012 test pins create, built-ins, saved in that order (I first put it second and broke two tests);
  the pinned list now ends with "open". My test-side slips: the fake stream is never pulled in make_app, so journeys
  never started until a helper pulled audio; identity comparisons failed because journey_start rebuilds the journey
  from JSON. A surviving mutation showed the file check mattered (a built-in name would have opened as a "file"); a
  test was added. 12 tests; 6 real mutations fail tests (one control was unreachable by design). Three new RUF012
  (dialog BINDINGS) follow the file's convention.
- L11: PM-039 suite job-28: 1365 passed, 3 deselected, 0 test daemons. T4 verified.
- L12: PM-040. `c` opens ControlsModal: one compact row per GLIDE_FIELDS field with its audible value, "over"
  seconds (default 60, 0-3600 like `--over`), fields the running journey owns locked and marked "(journey)". Apply
  sends only the changed fields in one `player.glide(fields, over)`, i.e. the engine's `queue_glide` as `ctl glide`
  does (and `ctl tempo` for bpm); invalid numbers and out-of-range "over" stay in the dialog; the engine's
  JourneyDriven refusal is shown with the CLI's message. The in-process Player gains `glide` and `tempo` (only the
  daemon client had them). First layout used 3-line inputs and did not fit an 80x24 terminal (Apply off screen);
  compact rows fix it. RED ImportError; GREEN 9; 5 mutations each fail tests.
- L13: PM-040 suite job-29 failed one test that predates M10: tests/test_main.py journey list counted the user's real saved journey "Desayuno" (created in the app at 16:11, not by any test: the string is in no file of the repo). Many tests did not isolate XDG_CONFIG_HOME. New tests/conftest.py gives every test a private empty config dir by default (tests that set their own still override); the failing test passes with the user's file present. Separate commit. The user's file was only read, never written. Rerun job-30 (test_tui_binaural.py, the PM-041 RED, excluded).
- L14: Rerun job-30: 1374 passed, 3 deselected, 0 test daemons (PM-041 RED file excluded). Isolation committed separately. T5 verified.
- L15: PM-041. `B` (b is Back) opens BinauralModal: carrier, beat, level (the playing values, or the defaults
  when off) and a glide time. Off: Apply = `set_binaural(Binaural, over)`, the CLI's `binaural on` request; on: Apply
  = `glide_binaural(changed values, over)`, the CLI's `binaural set` with only what changed; Off button =
  `set_binaural(None)`. Ranges checked with Binaural's own messages before sending; a journey that owns the layer is
  refused with the CLI's message; the copy makes no claim about effects (tested). The in-process Player gains
  set_binaural and glide_binaural (refusing a set while off with the daemon's message). Two mutations first survived
  because the local engine receives the same call for on and set; a test now checks the requests themselves, as the
  acceptance criterion says. RED ImportError; GREEN 13.
- L16: PM-041 suite job-31: 1387 passed, 3 deselected, 0 test daemons. T6 verified.
- L17: PM-042. `t` opens SayModal: text, a voice Select filled in a worker from speech.voices() (Default first),
  rate (blank = the voice's own, else 80-400) and effect. Say renders in a worker through the new Player.say (the
  background player's `say`: resolve_voice warning, render, queue_speech), so the CLI and TUI send the same
  options to the TTS program (tested on its argv). Errors (no backend, empty text, bad rate) stay in the dialog.
  A worker that dismisses the dialog itself was cancelled with the screen; the dialog now closes from
  on_worker_state_changed. Mutations: 4 of 5 caught; "skip the empty-text check" is equivalent (speech.render
  refuses with the same message before calling the program). RED ImportError; GREEN 8.
- L18: PM-042 suite job-32: 1395 passed, 3 deselected, 0 test daemons. T7 verified.
- L19: PM-043. `v` opens VoicesModal. The CLI's texts moved to shared functions (voicepacks.list_lines,
  added_message; voicesetup.installed_message; samples.installed_message) so the dialog and the CLI cannot drift;
  the CLI output is unchanged (138 voice/sample tests pass untouched). Tests compare against the CLI itself: the
  list equals `voices list`; add/remove leave voices.json byte-identical to `voices add/remove`; installing the
  choir or the soundfont leaves config and cache trees identical to `setup-voices`/`setup-samples` (local fake
  .7z/.deb); a failed install (checksum) says why and leaves nothing; a slow fake download moves the bar, disables
  the install buttons and the UI keeps answering. The dialog cannot close mid-download (a thread cannot be stopped).
  80x24 first clipped two buttons: two button rows now (tested). Mutations: 5 of 6 caught; the survivor
  ("always call setup_samples") is equivalent, it does nothing when installed. Finding for the user: the engine
  reads the active pack only at start, so "the choir now sings it" (CLI and dialog) takes effect on the next start.
- L20: PM-043 suite job-33: 1406 passed, 3 deselected, 0 test daemons. T8 verified.
- L21: PM-044. A gentle-ai-worker was delegated (context backstop) and returned partial: its build_parser() was a
  hand-written copy of the command list, so the guard could never see a new command, and one test was always true.
  Discarded and done inline. `build_parser()` now holds the real parser main() uses (test: `--help` output equals
  build_parser().format_help()). `render` keeps its CLI and calls the new `render_style(out, seconds, seed, style,
  procedural, journey)`, which the TUI's RenderModal (`w`) also calls in a worker, with the style playing now. Tests:
  the dialog's WAV equals `gentle-stream render --mood-file <that style>` byte for byte (style, and journey +
  procedural), the printed line is the TUI's status, invalid options and an unwritable path stay in the dialog with
  the CLI's messages, 80x24 fits. app.PARITY maps every command and ctl action to its TUI action (which must exist
  and be in the palette); NOT_IN_TUI holds only `ctl status` (always on screen). The guard walks the real parser;
  removing an entry or adding a CLI command fails it (tested both ways). No CLI gaps found. Mutations: 8 of 8 caught
  after strengthening two tests (procedural only changes bytes with a soundfont, so a spy checks the options; the
  playing style is now a non-default one). README: parity table and the `w` row; --help lists `w`.
- L22: PM-044 suite job-34: 1424 passed, 3 deselected, 0 test daemons; test_tui_render.py re-run after a lint-only edit. T9 verified; M10 implementation complete (slow tests next).
