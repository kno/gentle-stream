# Ballad bridge listening comparison

Branch `feat/ballad-bridge`, stacked on `feat/meter` (`3de9f6f`). Two matched offline renders, no live player changes.

## Specs

**S1** — User: "el vals está bien". Preserve the validated 6/8 feel while trying a distinct four-bar bridge before the ballad's last chorus.

**S2** — User: "adelante, genera una antes del cambio y otra después para comparar". Generate one before and one after the change with identical style, seed, backend, duration, and output format; leave the two audio files in `listen/` untracked.

## Tasks

| Task | Specs | Route | Commit |
| :--- | :--- | :--- | :--- |
| T1 Render and inspect the baseline WAV | S2 | inline | untracked `listen/ballad-bridge-before.wav` |
| T2 Compose and schedule the bridge with focused RED/GREEN tests | S1 | inline | `55b1235` |
| T3 Render the matching after WAV, verify comparison and full suite, commit | S1, S2 | inline | `55b1235` |

## Log

- L1: "adelante, genera una antes del cambio y otra después para comparar"
- L2: Earlier context: "el vals está bien"; the accepted proposal was to give the ballad its own bridge before the chorus. The existing `breakdown` is four bars without a lead melody, followed by `B'`.
- L3: The comparison uses 6/8, effective 140 BPM (`render --mood-file` clamps a supplied 180 to 140), seed 20261107, procedural instruments, 108 s, 16-bit stereo. The 4-bar bridge begins at 72 s; the returning chorus runs about 82.29–102.86 s. Baseline SHA-256 `044b2d5d9105581763bfe9eaf1fa94839c03ca74a0d34c104d6515842a929570`; after SHA-256 `d6be58592ad3d5a8c7a6969fc86b4a53bd2280873651d35559c7313b01bf5945`. Prelude samples 0–72 s are identical; first differing sample is at 72.00249 s. WAVs and the style JSON remain untracked under `listen/`.
- L4: RED observed for missing compound bridge melody; focused 64 tests passed after the fix, and 3/3 targeted mutants died. Existing 4/4 breakdown remains without lead.
- L5: Differential check against the base commit: all 13 genres had identical one-second procedural WAV hashes, CLI exit codes, stdout and stderr with the same seed. The temporary baseline archive was removed.
- L6: Independent read-only verifier covered S1 and checked both WAVs' format and hashes; it did not rerun the sample comparison, which the parent verified (prelude identical, first changed sample at 72.00249 s). Compound bridge also checked at 12/8; 4/4 remained without lead. Full suite: 1911 passed. Native ASSESS could not evaluate the untracked `listen/` artifacts, so there is no native review verdict.
