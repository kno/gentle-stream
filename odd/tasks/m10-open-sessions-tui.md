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
| T2 PM-037 open-ended stages | S2 | inline | `feat/open-stages` | pending |
| T3 PM-038 point-list curves | S3 | inline | `feat/point-curves` | pending |
| T4 PM-039 journeys from the TUI | S4, S0 | inline | `feat/tui-journeys` | pending |
| T5 PM-040 live controls from the TUI | S5, S0 | inline | `feat/tui-controls` | pending |
| T6 PM-041 binaural from the TUI | S6, S0 | inline | `feat/tui-binaural` | pending |
| T7 PM-042 spoken phrases from the TUI | S7, S0 | inline | `feat/tui-say` | pending |
| T8 PM-043 voices and samples from the TUI | S8, S0 | inline | `feat/tui-voices` | pending |
| T9 PM-044 render and the parity guard | S9, S0 | inline | `feat/tui-render` | pending |

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
