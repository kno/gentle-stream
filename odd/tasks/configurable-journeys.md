# Feature: configurable-journeys (roadmap M3 start)

Objective: deliver PM-007 Journey files and PM-008 Journey controls on `feat/configurable-journeys`, stacked on the accepted M2 branch. Delivery: local reviewable commits; push remains a user decision.

## Specs

- **S1 — PM-007 Journey files.** "write a journey as JSON and run it: `gentle-stream journey play ./sunrise.json`; mistakes produce one clear line, not a crash."
- **S2 — Schema and validation.** "stage 3: \"seconds\" must be a number between 10 and 14400"; version 1; at most 24 stages and 12 hours total; unknown keys ignored; every value is clamped like `Style.from_dict`; warnings report clamping. Approved canonical object: `version: 1`, `name`, optional `title`/`description`/`end`, and `stages`; `version` and `stages` required; `name` defaults from the file name.
- **S3 — Public commands.** `journey validate FILE`; `journey show NAME|FILE`; daemon `journey_start {"journey": {...}}`; the CLI sends the normalized object and the daemon never reads a user path. `validate` prints normalised JSON to stdout and each `warning: ...` to stderr; `show` prints JSON only; invalid input prints `gentle-stream: ...` to stderr and exits 1.
- **S4 — Nothing regresses.** Valid files run; invalid files print exact errors and exit 1; `from_dict(to_dict())` round-trips; existing journey/CLI behavior remains unchanged.
- **S5 — PM-008 Journey controls.** "restart a journey, skip to the next stage, or stop it, from the CLI and from the TUI (`j` opens a small journey menu)."
- **S6 — PM-008 protocol and behavior.** daemon `journey_restart`, `journey_skip`; CLI `journey restart|skip|stop`; TUI modal with Restart / Skip stage / Stop; "skip sets journey time to the next stage start; restart resets journey time and re-applies the first stage's starting values at the next bar." "commands without a running journey answer `no journey is running` (exit 1 in the CLI)." Approved final-stage skip behavior: exit 1 with `already at the final journey stage`; do not change the journey.
- **S7 — PM-008 boundaries and regression.** "each command changes `journey.stage` as specified on the next rendered bar"; skip across a genre boundary follows PM-006's phrase-boundary rule; no arbitrary-time seeking or editing; pause and resume stay documented as already free since PM-004.

## Tasks

| ID | Specs | Route | Status | Commit |
|---|---|---|---|---|
| T1 PM-007 journey file schema and CLI | S1-S4 | explore, implementation, focused verification | done | 8716405, 7fad3b9 |
| T2 PM-007 independent verification | S1-S4 | verifier after T1 commit and correction | done | mvqfalnv-8-5fu2 |
| T3 PM-008 journey controls | S5-S7 | exploration, test-first implementation, focused verification | done | 79a8b02 |
| T4 PM-008 independent verification | S5-S7 | verifier after T3 commit | in progress | mvqixu7b-c-ajds |

## Log

- L1 (user): "siguiente punto"
- L2: User selected a new `feat/configurable-journeys` branch, stacked on accepted M2, for PM-007.
- L3 (user): "Aplicar el contrato propuesto" — canonical v1 journey JSON is `{version: 1, name, title?, description?, end?, stages}` with required version/stages and file-name default name; validate writes normalized JSON to stdout and warnings to stderr, show JSON only, invalid input uses `gentle-stream: ...` and exit 1.
- L4: T1 public PM-007 subset: 31 passed; production LSP clean. Full suite: 609 passed, 27 skipped, 3 teardown-only `ProcessLookupError` errors at `tests/test_daemon.py:108`; no assertion failures.
- L5: Independent verification found schema defects in 8716405: unknown `to` keys were rejected (contrary to unknown-key tolerance), boolean `version` was accepted, and unhashable `end` could raise `TypeError`. Corrected in 7fad3b9 with explicit regression tests; PM-007 subset now 32 passed and LSP is clean.
- L6: Full post-fix suite: 610 passed, 27 skipped, 3 teardown-only `ProcessLookupError` errors at `tests/test_daemon.py:108`, with no assertion failures. Native review was declined for this candidate at consent; repeat independent verification is in progress.
- L7: Repeat verifier mvqfalnv-8-5fu2: S1-S3 PASS; S4 functional checks PASS with the known teardown flake, LSP UNVERIFIED because its scratch session had no LSP tool. The parent production LSP check was clean. PM-007 closed locally; no push requested.
- L8 (user): "sigue con el siguiente punto"
- L9 (user): Selected "Rechazar claramente" for skip at the final stage: exit 1 with `already at the final journey stage`; no journey change.
- L10: T3 complete (commit 79a8b02): engine controls, daemon protocol, CLI restart/skip subcommands, TUI `j` menu, docs updated. 629 PASS, 27 skipped, 0 assertion failures (3 teardown flakes). Independent verification in progress (mvqixu7b-c-ajds).
