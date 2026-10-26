# Type diagnostics cleanup

Authorized scope: resolve pre-existing Pyright/LSP errors in audio samples and genre modules before resuming M2.

## Specs

S1. "Corregirlos ahora"

## Tasks

| ID | Specs | Route | Status | Commit |
|---|---|---|---|---|
| T1 samples diagnostics | S1 | inline | done | f09c79d |
| T2 full source diagnostics | S1 | bounded workers by independent subsystem | done | pending commit |
| T3 verification | S1 | focused diagnostics and full suite | done | pending commit |

## Log

- L1: "sigue"
- L2: User chose "Corregirlos ahora" after being shown 38 pre-existing Pyright/LSP errors in `samples.py` and eight genre modules, which did not change since M1.
- L3: Full source scan found 72 diagnostics: the original sample/genre errors plus pre-existing Pyright errors in `app.py` and `composer.py`, genre errors in chiptune/cumbia/dubstep/electro, and one AST rule in `client.py`. T1 resolves `samples.py` and its focused tests: handling unreadable tar members now raises `SetupError`; Pyright and AST diagnostics are clean there.
- L4: T2 clears the workspace scan (27 source files, zero diagnostics). It preserves the live-glide golden hashes; an accidental `int()` conversion in ambient changed audio and was corrected to a typing-only `cast()` before verification.
- L5: T3 full suite: 576 passed, 27 skipped, 5 teardown-only `ProcessLookupError` errors at `tests/test_daemon.py:108`, the pre-existing daemon race. There were no test assertion failures; focused samples and genre tests passed, and LSP workspace scan is clean.
