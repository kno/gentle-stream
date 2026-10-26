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
| T1 PM-001 | S1, S4 | gentle-ai-worker (user asked for a subagent), background | in progress | |
| T2 PM-002 | S2, S4 | same worker, continued after T1 commit | pending | |
| T3 PM-003 | S3, S4 | same worker, continued after T2 commit | pending | |

## Log

- L1 (2026-10-26, user): "lanza un subagente con la primera fase" — interpreted as milestone M1 (PM-001..PM-003); one writer, sequential, because PM-001/002/003 share `__init__.py` and `tests/test_main.py`.
- L2: roadmap committed on this branch as the spec source.
