# M4 close-out: journey library and CLI create (PM-010 / PM-011 gaps)

Branch `feat/journey-library`, stacked on `feat/tui-journey-picker`. Brings `journey create` and saved journeys in
line with `docs/PROGRESSIVE_MUSIC_ROADMAP.md` (PM-010, PM-011); PM-012's TUI picker moves onto the new store.

## Specs

**S1** — PM-010 user value (roadmap, verbatim): "`gentle-stream journey create "20-minute ambient to energetic 118 bpm
synthwave, then keep it going"` asks the model once, prints the journey and starts it; nothing else calls a model."

**S2** — PM-010 scope (verbatim): "a journey prompt in `bridge.py` (genres with tempo ranges, field ranges, curve
names, the schema, the "original music only" rule); [...] validation through `Journey.from_dict`; `--dry-run` prints
without starting; token usage printed." `create` honours the global `--model` and `--gentle-shell` options.

**S3** — PM-010 acceptance (verbatim): "a fake model answer becomes the expected normalised journey; a non-JSON answer
prints `gentle-stream: the model answered with no JSON object` and exits 1; a timeout prints the existing timeout
message."

**S4** — PM-011 user value (verbatim): "keep journeys you like: `journey save NAME [FILE|--last]`, `journey list`,
`journey delete NAME`; saved ones play by name like built-ins."

**S5** — PM-011 scope (verbatim): "`journeys.json` next to `presets.json`, versioned, atomic, corrupt-file-safe; extract
the atomic writer from `presets.py` into a shared helper now that there are two users; the daemon remembers the last
started journey so `--last` works."

**S6** — PM-011 acceptance (verbatim): "same safety guarantees as presets (unreadable file never overwritten, invalid
entries skipped and reported); built-in names cannot be overwritten; existing preset tests pass unchanged."

**S7** — The PM-012 TUI picker and prompt use the same store: saved names as people type them, store errors (built-in
name, unreadable file) shown in the prompt modal with the input kept.

**S8** — PM-011 demo (verbatim): "`journey create "..." && journey save "Morning run" --last && journey play "Morning
run"`."

## Tasks

| Task | Specs | Route | Commit |
| :--- | :--- | :--- | :--- |
| T1 | S5, S6, S7 | worker + inline rewrite: `storage.py`, `presets.py`, `journey.py` store, `app.py`; tests | done (T1 commit) |
| T2 | S4, S5, S8 | worker + inline review: `__init__.py` save/list/delete/play/show by name, daemon `journey_last`, client | done (T2+T3 commit) |
| T3 | S1, S2, S3 | worker + inline tests: `bridge.py` prompt, `__init__.py` create (`--dry-run`, usage, errors, flags) | done (T2+T3 commit) |
| T4 | all | README/help; independent verify (Risk items 1, 3) | pending |

## Log

- L1: User request: "M4" — chosen over PM-013 after the gap report (create only saves, no `--dry-run`/usage, no
  `save`/`delete`, `list` built-ins only, saved journeys not playable by name, unsanitised file names).
- L2: Decision: follow the roadmap's `journeys.json` (human names, case-insensitive like presets) and drop the
  unreleased one-file-per-journey store from PM-010; files under `~/.config/gentle-stream/journeys/` are not migrated.
  CLI `create` stops auto-saving (roadmap PM-010 out of scope: saving); saving is `journey save NAME --last`.
- L3: T1 evidence: worker draft rewritten inline to the `presets.py` style (it packed statements with `;` and
  leaked `PresetError`); name errors now raise `JourneyStoreError`. Mutation check (built-in guard and corrupt-file
  guard disabled) -> 7 store tests RED; restored -> 20 passed. Focused suites 167 passed; `tests/test_presets.py`
  unchanged. Stack check: all 14 chained branches pass (only the known daemon teardown errors).
- L4: T2+T3 evidence: worker passes skipped tests twice; review fixes (shared `_round_trip`, save/delete inside
  `journey_command`, narrow excepts, OLDER_PLAYER for `--last` and `create`, no dict hack in the TUI, explicit
  `source`/`last` instead of overloading `prompt`). CLI create/demo tests written inline. Mutations (dry-run ignored,
  usage not printed, daemon forgets the last journey, saved names not resolved) each turned tests RED; restored ->
  green. Full suite 683 passed, 27 skipped, 2 known daemon teardown errors; no production diagnostics.
