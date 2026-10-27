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

| Task | Spec | Route | Notes |
| :--- | :--- | :--- | :--- |
| T1 | S1-S2, S4 | `journey.py`, `test_journey.py` | Implement `shape()`, add `curve` field to `Stage`, update `to_dict/from_dict`, validation |
| T2 | S3 | `engine.py` | Apply `shape()` in journey evaluation at next bar; update progress snapshot |
| T3 | S5, S6 | `test_journey.py` | Property tests, demo/manual listening (render output) |

## Log

- L1: User request "siguiente" → PM-009 start
