# PM-012: TUI journey prompt and picker

## Specs

**S1** — Press `J` in TUI → opens a modal `JourneyModal` with:
  - Text input field for natural-language journey description
  - "Create" button sends to `shell.journey_from_prompt()`, saves with user-suggested name
  - "Cancel" button dismisses modal

**S2** — After creation, or from main TUI, `J` opens `JourneyPicker` showing:
  - Built-in journeys (read-only)
  - Saved journeys (from `JourneyStore.list()`)
  - Selected journey plays immediately via `player.journey_start()`

**S3** — On error (Gentle Shell timeout, invalid JSON, schema mismatch), show error in modal and keep input

**S4** — Modal is modal: blocks main TUI input; Escape dismisses without saving

**S5** — Journey picker sorts built-ins first, then saved alphabetically

## Tasks

| Task | Spec | Route | Status |
| :--- | :--- | :--- | :--- |
| T1 | S1-S3 | `app.py` JourneyPromptModal | done (this commit) |
| T2 | S4-S5 | `app.py` JourneyPickerModal | done (this commit) |
| T3 | Integration + tests | `test_app.py` | done (this commit) |

## Log

- L1: PM-012 task created; depends on PM-010/011 (CLI journey create/list complete)
- L2: User request: "si, adelante" — approved `J` (uppercase) for prompt/picker, `j` keeps the PM-008 controls menu.
- L3: f67b96a only added unwired modal classes. Wired `J` -> picker ("Create from a description…" first, built-ins, saved
  sorted); create -> prompt modal (description + optional name; Gentle Shell in a thread worker; errors stay in the modal
  with input kept) -> saved under a safe slug -> picker reopens on it. Added in-process `Player.journey_start`.
  Fixed `escape` bindings (`"action_cancel"` -> `"cancel"`) in all three journey modals, including the PM-008 menu.
- L4: Evidence: `pytest -k "pm012 or pm008"` 14 passed; full suite 645 passed, 27 skipped, 5 errors — the errors are
  pre-existing flaky `test_daemon.py` teardown `ProcessLookupError` (3 errors on the base commit as well).
