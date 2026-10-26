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
| T1 PM-004 | S1, S4 | gentle-ai-worker, background; independent verify (Risk 4: journey commands from daemon threads applied on the render thread) | done (verify pending) | fb03b31 |
| T2 PM-005 | S2, S4 | same worker, continued after T1 commit | in progress | |
| T3 PM-006 | S3, S4 | same worker, continued after T2 commit | pending | |

## Log

- L1 (2026-10-26, user): "siguimos con lo siguiente, pero con su propia rama. haz push" — `feat/live-evolution` pushed to `fork` (kno/gentle-stream) at a44779f; M2 on its own branch stacked on it.
- L2: T1 done fb03b31 (545 passed, known flake only; golden hashes unchanged; ctl/render differential identical vs a44779f). Independent verify mvp97xla-7-ueyr runs on a worktree of fb03b31 while T2 proceeds.
