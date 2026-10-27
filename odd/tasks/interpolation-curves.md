# PM-009: Interpolation curves

## Specs

**S1** — Each `Stage` has a `curve` field (default `"linear"`). Valid curve names: `linear`, `ease-in`, `ease-out`, `ease-in-out`, `exp`, `step`. Unknown names fall back to `linear` with a `validate` warning.

**S2** — A pure function `shape(curve: str, progress: float) -> float` where `progress ∈ [0, 1)` maps to the interpolated value:
- `linear`: `progress` (identity)
- `ease-in`: `progress^2`
- `ease-out`: `1 - (1-progress)^2`
- `ease-in-out`: piecewise: `0.5 * (2*progress)^2` if `progress < 0.5`, else `1 - 0.5 * (2*(1-progress))^2`
- `exp`: interpolate in log space: `10^(progress * (log10(target) - log10(source))) / source` (or equivalent)
- `step`: `0` for `progress < 1`, else `1` (jump at the start)

**S3** — At bar boundaries, when evaluating journey progress, use the curve to compute `value = source + (target - source) * shape(curve, progress)` instead of the linear interpolation.

**S4** — `validate` warnings for unknown curve names, like: `warning: unknown curve "wobble" in stage 1; using linear`.

**S5** — Property tests: each curve monotonic, hits 0 at 0 and 1 at 1, `ease-in` < linear at 0.5.

**S6** — Demo: `render --journey demo-curves.json --verbose` with `ease-in-out` vs `linear` stages, compare bpm log.

## Tasks

| Task | Spec | Route | Status | Commit |
| :--- | :--- | :--- | :--- | :--- |
| T1 | S1-S2, S4 | `journey.py`, `test_journey.py` | done | 60253e8 |
| T2 | S3 | `journey.py` (at method) | done | 60253e8 |
| T3 | S5, S6 | `test_journey.py` | done (6 tests) | 60253e8 |

## Log

- L1: User request "siguiente" → PM-009 start
- L2: Implemented `shape()` function, `Stage.curve` field (default "linear"), validation for 6 curve types
- L3: Updated `Journey.from_dict()` to read `curve` with fallback to "linear" + warning for unknown
- L4: Updated `Journey.to_dict()` to serialize `curve` (omit if default)
- L5: Modified `Journey.at()` to use `shape(stage.curve, progress)` for interpolation
- L6: Added 6 curve tests: boundary conditions (0→1), monotonicity, ease-in < linear, from_dict/to_dict, fallback, interpolation effect
- L7: Commit 60253e8; 76 total journey tests pass (99 with engine tests)
- L8: PM-009 complete; ready for next feature (PM-010: natural-language journeys)
