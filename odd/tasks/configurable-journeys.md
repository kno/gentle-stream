# Feature: configurable-journeys (roadmap M3 start)

Objective: deliver PM-007 Journey files on `feat/configurable-journeys`, stacked on the accepted M2 branch. Delivery: local reviewable commits; push remains a user decision.

## Specs

- **S1 — PM-007 Journey files.** "write a journey as JSON and run it: `gentle-stream journey play ./sunrise.json`; mistakes produce one clear line, not a crash."
- **S2 — Schema and validation.** "stage 3: \"seconds\" must be a number between 10 and 14400"; version 1; at most 24 stages and 12 hours total; unknown keys ignored; every value is clamped like `Style.from_dict`; warnings report clamping.
- **S3 — Public commands.** `journey validate FILE`; `journey show NAME|FILE`; daemon `journey_start {"journey": {...}}`; the CLI sends the normalized object and the daemon never reads a user path.
- **S4 — Nothing regresses.** Valid files run; invalid files print exact errors and exit 1; `from_dict(to_dict())` round-trips; existing journey/CLI behavior remains unchanged.

## Tasks

| ID | Specs | Route | Status | Commit |
|---|---|---|---|---|
| T1 PM-007 journey file schema and CLI | S1-S4 | explore, implementation, focused verification | pending | |
| T2 PM-007 independent verification | S1-S4 | verifier after T1 commit | pending | |

## Log

- L1 (user): "siguiente punto"
- L2: User selected a new `feat/configurable-journeys` branch, stacked on accepted M2, for PM-007.
