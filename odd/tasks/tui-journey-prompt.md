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
| T1 | S1-S3 | `app.py` JourneyModal | pending |
| T2 | S4-S5 | `app.py` JourneyPicker | pending |
| T3 | Integration + tests | `test_app.py` | pending |

## Log

- L1: PM-012 task created; depends on PM-010/011 (CLI journey create/list complete)
