"""A wordless choir: a soft "aah" pad that sings the upper tones of each chord, in every genre (`Style.voice`).

Each voice is procedural, no download: a band-limited saw source shaped by three vowel formant band-passes
(`FORMANTS`), a slow vibrato that enters after the onset, a little breath noise, and a swell envelope. Notes are
cached by (midi, duration, vowel, rate) like the genres' own voices. The engine schedules the choir after the genre
through `Piece.add`, before the master chain, so the genre's room and reverb carry it; with `voice` 0 it never runs.

The choir keeps its own voice-leading centre in the piece's state, so the genre's chord voicing and the random draws
of the music stay exactly as they are. The vowel follows the section: "a" where the melody plays, "o" in the intro,
the breakdown and the release.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from .composer import BarPlan, Chord
from .genres.base import Piece
from .synth import SR, adsr, bp, mtof, osc

# vowel -> (F1, F2, F3) in Hz; each formant's band-pass width and gain below
FORMANTS = {"a": (800, 1200, 2500), "o": (500, 850, 2400), "u": (350, 650, 2300)}
WIDTHS = (110, 130, 180)
GAINS = (1.0, 0.65, 0.25)
RANGE = (55, 79)            # G3 to G5: where the choir sings
CENTRE = 67                 # where its voicing starts, G4
GAIN = 0.12                 # each choir voice's level at voice=1
RELEASE = 0.4               # seconds a note rings past its length
PANS = (-0.35, 0.0, 0.35)


@lru_cache(maxsize=512)
def sung(midi: int, seconds: float, vowel: str, sr: int = SR) -> np.ndarray:
    """One sung note of `seconds` (plus RELEASE) on `vowel`: peak at most 1, swelling in without a click."""
    n = int(seconds * sr) + int(RELEASE * sr)
    t = np.arange(n) / sr
    depth = 0.012 * np.clip((t - 0.4) / 0.6, 0.0, 1.0)            # vibrato enters after the onset
    freq = mtof(midi) * (1 + depth * np.sin(2 * np.pi * 5.2 * t))
    source = osc("saw", freq, n, sr)
    voice = np.zeros(n)
    for f, w, g in zip(FORMANTS[vowel], WIDTHS, GAINS, strict=True):
        voice += g * np.asarray(bp(source, f - w / 2, f + w / 2, sr))
    breath = np.asarray(bp(np.random.default_rng(midi).standard_normal(n), 1500, 4000, sr)) * 0.02
    env = adsr(n, sr, attack=min(0.6, 0.35 * seconds), decay=0.0, sustain=1.0, release=RELEASE, hold=seconds)
    x = (voice + breath) * env
    peak = float(np.abs(x).max())
    return x / peak if peak > 0 else x


def _voicing(chord: Chord, ton: int, key_offset: int, center: float) -> list[int]:
    """The chord's upper tones (no root) each placed in the choir's range nearest `center`."""
    out = []
    for interval in chord.tones[1:4]:
        m = ton + key_offset + interval + 12
        while m - center > 6 and m - 12 >= RANGE[0]:
            m -= 12
        while center - m > 6 and m + 12 <= RANGE[1]:
            m += 12
        while m > RANGE[1]:
            m -= 12
        while m < RANGE[0]:
            m += 12
        out.append(m)
    return out


def choir_notes(plan: BarPlan, ton: int, center: float | None) -> tuple[list[tuple[int, float, float]], float]:
    """(midi, start beat, beats) of the choir in `plan`'s bar, and the voicing centre it leaves for the next bar:
    the bar's chord for the whole bar, or its first half then the passing chord."""
    center = CENTRE if center is None else center
    segments = [(0.0, 4.0, plan.chord)] if plan.passing is None else [(0.0, 2.0, plan.chord), (2.0, 2.0, plan.passing)]
    notes = []
    for start, beats, chord in segments:
        voiced = _voicing(chord, ton, plan.key_offset, center)
        notes += [(m, start, beats) for m in voiced]
        center = float(np.mean(voiced))
    return notes, center


def schedule(piece: Piece, plan: BarPlan, voice: float) -> None:
    """Add the choir's notes for `plan`'s bar to `piece` at `voice` (0-1)."""
    notes, piece.state["choir_center"] = choir_notes(plan, piece.ton, piece.state.get("choir_center"))
    vowel = "a" if plan.section in ("A", "B", "A'", "B'") else "o"
    beat = 60.0 / piece.style.bpm
    for i, (midi, start, beats) in enumerate(notes):
        seconds = max(0.25, round(beats * beat * 4) / 4)           # quarter-second buckets keep the cache small
        piece.add(sung(midi, seconds, vowel, piece.sr), start * beat, PANS[i % len(PANS)], GAIN * voice)
