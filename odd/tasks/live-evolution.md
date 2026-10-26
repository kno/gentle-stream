# Feature: live-evolution (roadmap milestone M1)

Objective: deliver milestone M1 "Live evolution" of docs/PROGRESSIVE_MUSIC_ROADMAP.md: tempo and energy/colour change in place without restarting the piece, plus offline render to WAV.
Branch: `feat/live-evolution`. Delivery: local work-unit commits; push/PR are the user's decision. Test runner: `uv run pytest` (baseline 385 passed, 27 skipped at f4ffaea).

## Specs

- **S1 — PM-001 Live tempo glide.** Exactly the PM-001 entry of docs/PROGRESSIVE_MUSIC_ROADMAP.md (scope, out of scope, acceptance criteria 1-7) and its Appendix A prompt.
- **S2 — PM-002 Live glide of energy, brightness, space and melody density.** Exactly the PM-002 entry (acceptance criteria 1-4), including golden hashes captured from the base commit in a scratch directory.
- **S3 — PM-003 Offline render to WAV.** Exactly the PM-003 entry (`gentle-stream render --seconds N [--seed] [--genre] [--mood-file] [--procedural] OUT.wav`, 16-bit PCM default).
- **S4 — Nothing regresses.** Section 4 conventions of the roadmap: bars join without clicks, output < 1.0, deterministic, > 4x real time, existing ctl actions byte-identical, docs (README, CONTROLS help, daemon protocol docstring) updated.

## Tasks

| ID | Specs | Route | Status | Commit |
|----|-------|-------|--------|--------|
| T1 PM-001 | S1, S4 | gentle-ai-worker (user asked for a subagent), background; independent verify (Risk 4 concurrency, 3 additive status keys) | done (verify pending) | a89e64a |
| T2 PM-002 | S2, S4 | same worker, continued after T1 commit | done | 51580b0 (+ PM-001 review fixes d74e27e) |
| T3 PM-003 | S3, S4 | same worker, continued after T2 commit | in progress | |

## Log

- L1 (2026-10-26, user): "lanza un subagente con la primera fase" — interpreted as milestone M1 (PM-001..PM-003); one writer, sequential, because PM-001/002/003 share `__init__.py` and `tests/test_main.py`.
- L2: roadmap committed on this branch as the spec source.
- L3 (T1): first worker pass shipped no tests and skipped the differential check; sent back. Second pass: 19 new tests (404 passed), differential check of ctl play/pause/toggle/next/stop/status vs f4ffaea identical except additive bpm/target_bpm. Parent fixed a race in Engine._apply_tempo (a glide queued while the previous one finished was cleared) and pre-existing type errors in engine._master and mastering (behaviour-neutral). A4 (gentle-pi status parser) unavailable on this machine.
- L4: pre-existing flaky teardown `ProcessLookupError` in tests/test_daemon.py:108 (also 2-5 errors per run on f4ffaea); pre-existing Pyright errors in samples.py and genres/*. Out of scope; follow-up.
- L5 (PM-001 verify + native review review-7c48f1552fa85297, state escalated): criteria 1-6 PASS; S4 FAIL. Fix list (follow-up commit after T2): F1 client hard-indexes elapsed_seconds/cycle_remaining_seconds (KeyError vs older player); F2 ctl parser accepts BPM/--over on every action (`ctl play 120` exits 0, base exited 2); F3 `ctl tempo` PlayerError traceback (bad request / older player "unknown command" needs the restart message); F4 tempo queued after queue_style/queue_next silently dropped by _start_piece; F5 queue_tempo reads piece_seconds/style unlocked; F6 docs: cancellation rule, chiptune start-time values, restore ctl status JSON example; F7 init _last_bar_start, replace assert with explicit check, top-level import math.
- L6: T2 done 51580b0 (466 passed; 20 golden hashes bit-identical to f4ffaea). It also fixed F2-F5 and part of F6; parent fixed F1, F7 and the rest of F6 in d74e27e (RED KeyError -> GREEN; 467 passed, 1 known flake).
