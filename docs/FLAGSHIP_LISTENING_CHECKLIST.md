# Flagship journey listening checklist (PM-021)

`ambient-to-synthwave` is the 20-minute reference journey. Its regression metrics run in
`tests/test_flagship_journey.py` (marked `slow`); this checklist is the human half of the acceptance and belongs in
the PR, completed by the maintainer.

## Listen

```bash
uv run gentle-stream render --journey ambient-to-synthwave --seconds 1200 --seed 2026 flagship.wav
# or live, from the start of any music:
uv run gentle-stream journey play ambient-to-synthwave
```

Use headphones for the binaural texture (stages 1 to 4).

| Time | Stage | What should happen |
| :--- | :--- | :--- |
| 0:00–3:00 | Dawn (ambient) | A still opening: pads and glass only, no drums or melody; the 6 Hz binaural texture fades in. |
| 3:00–6:00 | Drift (ambient) | The melody enters on the first phrase of the stage; tempo eases up to 68 bpm. |
| 6:00–10:00 | Chillout (lo-fi) | An eight-bar crossfade from ambient into lo-fi, prepared by a dominant; drums arrive soft. |
| 10:00–13:00 | Lift (lo-fi) | Energy and tempo rise to 98 bpm; drums step up; the binaural texture fades out. |
| 13:00–17:00 | Synthwave | An eight-bar crossfade into synthwave in a related key; the ambient motif still opens the melody; the counter-melody joins. |
| 17:00–20:00 | Peak (synthwave) | 118 bpm and full energy, busy drums, then it holds. |

## Checklist

- [ ] No clicks, dropouts or level jumps at any stage boundary or crossfade.
- [ ] Each genre step sounds prepared (the key change resolves, nothing lurches).
- [ ] The opening motif is recognisable in the lo-fi and synthwave stages.
- [ ] Parts enter where the table says (drums in Chillout, melody in Drift, counter-melody in Synthwave).
- [ ] The drums build one step at a time; no sudden busy pattern.
- [ ] The loudness feels like a rise, not a dip, into synthwave (the metrics allow a dip of up to 2.5 dB there:
      synthwave's master sits about 2 dB under lo-fi's).
- [ ] The binaural texture is quiet and gone before the lift (no claims about effects anywhere).
- [ ] The whole 20 minutes would work as a reference demo.

Listener: maintainer  Date: 2026-10-28  Notes: listened to the full journey; "suena bien" (sounds good).

## Known limits

- Layer switches only reach parts a genre plays through the shared `layers` contract: ambient ignores `bass`, so
  the bass of the opening cannot be switched off there.
- Metrics run on the procedural backend; with the soundfont installed, levels differ slightly.
