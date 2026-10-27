# Feature: configurable-journeys (roadmap M3 start)

Objective: deliver PM-007 Journey files on `feat/configurable-journeys`, stacked on the accepted M2 branch. Delivery: local reviewable commits; push remains a user decision.

## Specs

- **S1 — PM-007 Journey files.** "write a journey as JSON and run it: `gentle-stream journey play ./sunrise.json`; mistakes produce one clear line, not a crash."
- **S2 — Schema and validation.** "stage 3: \"seconds\" must be a number between 10 and 14400"; version 1; at most 24 stages and 12 hours total; unknown keys ignored; every value is clamped like `Style.from_dict`; warnings report clamping. Approved canonical object: `version: 1`, `name`, optional `title`/`description`/`end`, and `stages`; `version` and `stages` required; `name` defaults from the file name.
- **S3 — Public commands.** `journey validate FILE`; `journey show NAME|FILE`; daemon `journey_start {"journey": {...}}`; the CLI sends the normalized object and the daemon never reads a user path. `validate` prints normalised JSON to stdout and each `warning: ...` to stderr; `show` prints JSON only; invalid input prints `gentle-stream: ...` to stderr and exits 1.
- **S4 — Nothing regresses.** Valid files run; invalid files print exact errors and exit 1; `from_dict(to_dict())` round-trips; existing journey/CLI behavior remains unchanged.

## Tasks

| ID | Specs | Route | Status | Commit |
|---|---|---|---|---|
| T1 PM-007 journey file schema and CLI | S1-S4 | explore, implementation, focused verification | done (independent verification pending) | pending commit |
| T2 PM-007 independent verification | S1-S4 | verifier after T1 commit | pending | |

## Log

- L1 (user): "siguiente punto"
- L2: User selected a new `feat/configurable-journeys` branch, stacked on accepted M2, for PM-007.
- L3 (user): "Aplicar el contrato propuesto" — canonical v1 journey JSON is `{version: 1, name, title?, description?, end?, stages}` with required version/stages and file-name default name; validate writes normalized JSON to stdout and warnings to stderr, show JSON only, invalid input uses `gentle-stream: ...` and exit 1.
- L4: T1 public PM-007 subset: 31 passed; production LSP clean. Full suite: 609 passed, 27 skipped, 3 teardown-only `ProcessLookupError` errors at `tests/test_daemon.py:108`; no assertion failures.
- L5: Independent verification found schema defects in 8716405: unknown `to` keys were rejected (contrary to unknown-key tolerance), boolean `version` was accepted, and unhashable `end` could raise `TypeError`. Corrected pending commit with explicit regression tests; PM-007 subset now 32 passed and LSP is clean.
