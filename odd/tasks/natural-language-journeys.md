# PM-010: Natural-language journeys (CLI)

## Specs

**S1** — `journey create "prose prompt"` sends the prompt to Gentle Shell, receives a journey JSON, validates it through `Journey.from_dict`, and saves it with a user-chosen name to `~/.config/gentle-stream/journeys/` as versioned JSON (same pattern as presets).

**S2** — Journey name is derived from the first word of the prompt or user-supplied. File stem is the name, e.g. `energetic-buildup.json`. Filename collision asks the user (overwrite Y/N).

**S3** — `journey list` shows both built-in and saved journeys (built-in first, then saved alphabetically). Saved journeys are marked with a dot or asterisk prefix.

**S4** — A journey created via NL can be played immediately (`journey play energetic-buildup`) or saved for later. Journey schema is standard (version 1, stages, curves, etc.).

**S5** — Errors from Gentle Shell (network, timeout, invalid JSON, schema mismatch) are caught and reported clearly; partially saved files are never left behind.

**S6** — When started, the TUI picks a saved journey on the first run, or accepts it as an arg like `gentle-stream --journey my-journey`.

## Tasks

| Task | Spec | Route | Status |
| :--- | :--- | :--- | :--- |
| T1 | S1-S2, S5 | `journey.py` + `__init__.py` | pending |
| T2 | S3-S4 | `journey.py` + CLI | pending |
| T3 | S6 | `app.py` + main | pending |
| T4 | Integration + tests | `test_journey.py`, e2e check | pending |

## Log

- L1: User chose "dejar sin revisar" (PM-009 RDD candidate); PM-010 start
