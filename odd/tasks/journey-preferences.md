# Journey preferences

Branch `feat/journey-preferences`, stacked on `feat/ballad-finales`.

## Specs

**S1** — "vamos con ello" after the proposal: "adaptación a tus preferencias: aprender de los journeys que conservas o saltas".

**S2** — "yo prefiero que todo sea desde la tui".

**S3** — "ambas" in response to "solo sugiera journeys ... o ... también use esas preferencias al generar journeys nuevos".

**S4** — "Señal débil": "Reduce ligeramente su prioridad, sin tratar un salto aislado como rechazo."

## Tasks

| Task | Specs | Route | Commit |
| :--- | :--- | :--- | :--- |
| T1 Local, safe preference signals and weak skip scoring | S1, S4 | inline | storage work unit |
| T2 TUI recommendations, inspect and clear preferences | S1-S4 | inline | pending |
| T3 TUI natural-language generation uses bounded preference summary | S2-S3 | inline | pending |
| T4 Functional checks, independent verification and delivery | S1-S4 | inline | pending |

## Log

- L1: "vamos con ello"
- L2: "yo prefiero que todo sea desde la tui"
- L3: "ambas"
- L4: "Señal débil"
- L5: Exploration identified the TUI picker and prompt in `app.py`, `JourneyStore` in `journey.py`, and explicit skip in the journey menu. Save is positive; a skip is a weak negative, not a definitive dislike. Preferences are local; only a bounded summary goes to the model for generation, with the user's request taking priority. The TUI must allow inspection and clearing. No player or daemon changes inferred.
- L6: T1: versioned aggregate genre scores (+4 for a saved genre, −1 for an explicit skip), capped at ±100. No prompts or raw activity history stored. JSON writes are atomic, malformed files are preserved, and an advisory lock serializes concurrent updates. Nine focused tests pass, including four concurrent processes; `ruff` I/E9/F passes. `fcntl` is already used by the daemon and the project declares macOS and Linux. Independent verification reviewed the initial implementation and passed its then-four tests; expanded tests were run by the parent. Integration with actual UI actions remains T2.
