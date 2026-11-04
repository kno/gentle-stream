# Ballad musical endings

Branch `feat/ballad-finales`, stacked on `feat/ballad-bridge` (`1fa8a85`). A bounded cadence at explicit finite endings, without changing live Stop.

## Specs

**S1** — User: "siguiente punto" after the agreed sequence of bridge, finales and bass riffs. Add a musical ending to the ballad, not a generic abrupt cut.

**S2** — User chose: "Solo render y journey". Do not delay or change live Stop.

**S3** — User chose: "La música continúa". At the end of a finite journey, play the cadence and continue the stream; sustaining/open-ended journeys have no automatic end.

## Tasks

| Task | Specs | Route | Commit |
| :--- | :--- | :--- | :--- |
| T1 Write RED tests for an offline ballad cadence and unchanged default render/Stop | S1, S2 | inline | finale work-unit commit |
| T2 Add a ballad cadence and schedule it at finite render and release-journey boundaries | S1-S3 | inline | finale work-unit commit |
| T3 Run focused/full verification, differential checks, and deliver reviewable branch | S1-S3 | inline | finale work-unit commit |

## Log

- L1: "siguiente punto"
- L2: The answer "si" was clarified with a single choice: "Solo render y journey". A journey-choice follow-up selected "La música continúa".
- L3: Existing `render_style` truncates exactly at requested seconds; `Journey.end` has `sustain` (forever) and `release` (returns control without stopping playback). Design: cadence only for the currently playing ballad at finite render or release boundaries; preserve duration and existing Stop behavior.
- L4: RED observed for an unchanged ballad WAV; GREEN: 127 focused render/journey/ballad tests for V–I cadence, exact WAV length and unchanged prelude, release continuing, sustain and explicit Stop not triggering, and existing behavior. An existing test caught an accidental positional argument to the ordinary scheduler; the default no-argument call was restored.
- L5: Differential check against HEAD for all 12 non-ballad `render` commands: exit, stdout, stderr and one-second procedural WAV hashes matched exactly with the same input. Temporary archive removed. Listening comparison (untracked): `listen/ballad-finale-before.wav` is the preceding branch's 108-second `ballad-bridge-after.wav` with procedural instruments, style JSON `listen/ballad-bridge-style.json` (6/8, effective 140 BPM), seed 20261107. `listen/ballad-finale-after.wav` uses identical inputs. Both match sample-for-sample through 102.857143 s; the first change is at 102.859683 s. The last sample of the new render is zero (350 ms fade). Baseline SHA-256 `d6be58592ad3d5a8c7a6969fc86b4a53bd2280873651d35559c7313b01bf5945`; after `eb2d3e221a3b7ffda79ceef82e7496546f404cea7cde274220c3c0a14209ee95`.
- L6: Independent read-only verifier reviewed S1-S3 but could not run pytest in its environment and flagged missing tempo/mask/short-render/continuity evidence. RED tests reproduced repeat cues with a tempo ramp and leaked masked instruments; GREEN after recording at most one V–I cue per journey and honoring masked layers. Added 6/8 and one-second render checks, a waveform continuity bound at release, and killed 3/3 targeted mutants. The parent rerendered the after WAV with the final code; its SHA-256 remains unchanged. Full suite: 1919 passed. Native ASSESS was unavailable because untracked `listen/` requires explicit declaration, so no native review verdict is claimed.
