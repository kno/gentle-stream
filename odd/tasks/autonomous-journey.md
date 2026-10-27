# Feature: autonomous-journey (roadmap milestone M2, the MVP)

Objective: deliver milestone M2 "Autonomous journey (MVP)" of docs/PROGRESSIVE_MUSIC_ROADMAP.md: a built-in multi-stage journey runs on its own, shows its progress, steps between genres and sustains its final atmosphere.
Branch: `feat/autonomous-journey`, stacked on `feat/live-evolution` (M1, pushed to the `fork` remote, not merged). Delivery: local work-unit commits, pushed to `fork` when the user asks. Test runner: `uv run pytest` (baseline at a44779f: 494 passed, 27 skipped, plus the known `ProcessLookupError` teardown flake in tests/test_daemon.py:108).

## Specs

- **S1 — PM-004 Journey runner with sustain.** Exactly the PM-004 entry of docs/PROGRESSIVE_MUSIC_ROADMAP.md (scope, out of scope, technical approach, acceptance criteria 1-6), including `render --journey NAME` on top of PM-003.
- **S2 — PM-005 Journey progress in the TUI and `ctl status`.** Exactly the PM-005 entry.
- **S3 — PM-006 Genre steps between stages.** Exactly the PM-006 entry (acceptance criteria 1-5), including the built-in `ambient-to-synthwave` journey.
- **S4 — Nothing regresses.** Section 4 conventions of the roadmap: bars join without clicks, output < 1.0, deterministic, > 4x real time, constant-style golden hashes of tests/test_live_glide.py unchanged, existing ctl actions byte-identical, older background players handled, docs (README, CONTROLS help, daemon protocol docstring) updated.

## Tasks

| ID | Specs | Route | Status | Commit |
|----|-------|-------|--------|--------|
| T1 PM-004 | S1, S4 | gentle-ai-worker, background; independent verify (Risk 4: journey commands from daemon threads applied on the render thread) | done (verified; J1-J5 corrected) | fb03b31, bcbd588 |
| T2 PM-005 | S2, S4 | same worker, continued after T1 commit | done | 9923a93 |
| T3 PM-006 | S3, S4 | gentle-ai-worker, background | done (independent verification pending) | 1c9536b |

## Log

- L1 (2026-10-26, user): "siguimos con lo siguiente, pero con su propia rama. haz push" — `feat/live-evolution` pushed to `fork` (kno/gentle-stream) at a44779f; M2 on its own branch stacked on it.
- L2: T1 done fb03b31 (545 passed, known flake only; golden hashes unchanged; ctl/render differential identical vs a44779f). Independent verify mvp97xla-7-ueyr runs on a worktree of fb03b31 while T2 proceeds.
- L3 (PM-004 verify mvp97xla-7-ueyr): S1 criteria 1-6 PASS, S4 PASS. Fix list for after T2 (separate commit): J1 MEDIUM a glide on a journey-owned field is overwritten every bar yet still reported as target, and takes over abruptly when the journey stops or releases (66.5 -> 112.4 bpm in one bar), contradicting "journey stop leaves the music as it is"; J2 LOW a journey queued then stopped in the same bar drops the glides it cancelled; J3 LOW `journey`/`journey_seconds` show a just-started journey before any of its bars rendered (relevant for PM-005 snapshots); J4 LOW `next` advances journey time by the dropped prebuffer (consistent with D2, document it); J5 INFO built-in Stage.to dicts are mutable module globals.
- L4: T2 done 9923a93 (565 passed, known flake only; ctl/render differential identical except additive `journey` key). J1-J5 fixes in progress with the same worker. Decision (parent): a field driven by a running or queued journey cannot be glided (one-line error, exit 1); glides on a journey's fields are cancelled when the journey starts, not when queued.
- L5: J1-J5 corrected in bcbd588: journey-owned fields reject direct glides atomically; glides are cancelled only when the journey starts; rendered-bar state avoids premature journey visibility; stage targets are immutable and hashable; README documents `next` advancing rendered journey time by the dropped buffer. Focused tests: 135 passed plus six known teardown-only daemon-race errors; LSP clean.
- L6: T3 PM-006 started with worker mvqadnbe-h-45ir after type-diagnostics cleanup; scope is strictly the stage-genre switch, `skip_intro`, tests and documentation in S3-S4.
- L7: User chose "Cerrar M2 con producción limpia" when a full scan exposed 142 pre-existing test-only Pyright diagnostics; they are deferred as a separate cleanup. Production source is LSP-clean and M2 functional verification continues.
- L8: T3 implementation in 1c9536b and focused acceptance suite: 209 passed, 11 skipped. Full suite: 578 passed, 27 skipped; four teardown-only `ProcessLookupError` errors at `tests/test_daemon.py:108`, no assertion failures. `render --journey ambient-to-synthwave --seconds 30 --seed 1` was byte-identical twice (sha256 b94d7ce1…). Manual listening remains unverified; independent verification is pending.
