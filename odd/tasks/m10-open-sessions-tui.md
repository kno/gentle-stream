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
| T0 M10 plan in the roadmap | S0 | inline | `docs/m10-plan` | pending |
| T1 PM-036 record the session | S1 | inline | `feat/session-record` | pending |
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
