"""Ballad: piano and strings, slow and expressive, building to a last chorus a step higher.

The verses (A, A') are a broken-chord piano over held bass notes, with no drums; the choruses (B, B') bring block
chords, a string section and soft drums (kick on 1, a side-stick on 3, quarter hats), and the last chorus always
lifts the key. The harmony moves twice a bar and the melody sings long notes with expressive leaps up. With the
samples backend the keys are FluidR3_GM, the strings a String Ensemble, the bass an Acoustic Bass and the drums the
Standard kit; without it the lo-fi voices play them (the warm pad stands in for the strings).
"""
from __future__ import annotations

from typing import cast

import numpy as np

from ..composer import Profile
from ..samples import Hit, Program
from ..synth import SR, bp, hp, lp
from .base import Genre, Master
from .lofi import Instruments as LofiInstruments

CHORUS = ("B", "B'")
ARPEGGIO = (0, 2, 1, 2, 0, 2, 1, 2)   # eighth-note order of the voicing's tones: low, high, middle, high...
DRUMS = {"kick": (36, 80, 0.4, 0.26), "stick": (37, 85, 0.2, 0.10), "hat": (42, 70, 0.15, 0.04),
         "crash": (49, 90, 1.8, 0.07)}   # GM key, velocity, seconds, rms

# Two verses before the first chorus, a short break, and a last chorus that always lifts the key.
PROFILE = Profile(
    first_form=(("intro", 4), ("A", 8), ("A'", 8), ("B", 8), ("breakdown", 4), ("B'", 8), ("release", 8)),
    form=(("A", 8), ("B", 8), ("A'", 8), ("B", 8), ("breakdown", 4), ("B'", 8), ("release", 4)),
    energy={"intro": .25, "A": .4, "B": .7, "A'": .45, "breakdown": .3, "B'": .9, "release": .35},
    tail_tilt=True,
    rhythms=(((0, 3), (3, 1)), ((0, 1.5), (1.5, .5), (2, 2)), ((0, 2), (2, 1), (3, 1)), ((.5, .5), (1, 3)),
             ((0, 1), (1, 1), (2, 2))),
    steps=(-1, 1, -1, 0, 2), leap_chance=0.4, leap=4, span=6, chords_per_bar=2,
    progressions={"major": ((1, 3, 4, 5), (1, 5, 6, 4), (1, 6, 4, 5), (4, 5, 3, 6)),
                  "minor": ((1, 6, 3, 7), (1, 4, 7, 3), (6, 4, 1, 5))},
    lift_chance=1.0, lift_at=("B'",))


class Voices:
    """The keys and lead of `tone` (lo-fi's procedural voices or the shared FluidR3_GM set), strings, a bass and a
    soft kit."""

    def __init__(self, tone, rng: np.random.Generator, sr: int = SR, sampled=None):
        self.tone, self.rng, self.sr, self.s = tone, rng, sr, sampled
        self._strings = Program(48, velocity=(40, 95), tail=0.9, rms=0.1)
        self._bass = Program(32, velocity=(50, 105), tail=0.3, rms=0.25)

    def keys(self, name: str):
        return getattr(self.tone, name)

    def strings(self, m, dur, vel=0.8):
        return self.s.play(self._strings, m, dur, vel) if self.s is not None else self.tone.pad(m, dur, vel)

    def bass(self, m, dur):
        return self.s.play(self._bass, m, dur, 0.7) if self.s is not None else self.tone.sub(m, dur)

    def drum(self, name: str) -> np.ndarray:
        if self.s is not None:
            key, vel, secs, rms = DRUMS[name]
            return self.s.hit(Hit(0, key, vel, secs, rms))
        if name == "kick":
            return self.tone.kick()
        if name == "hat":
            return self.tone.hat(0.7)
        n = int((0.1 if name == "stick" else 1.4) * self.sr)
        t = np.arange(n) / self.sr
        noise = self.rng.standard_normal(n)
        if name == "stick":   # a woody click
            return cast(np.ndarray, bp(noise, 1200, 4000)) * np.exp(-t * 70) + np.sin(2 * np.pi * 420 * t) * np.exp(-t * 60) * 0.5
        return cast(np.ndarray, lp(hp(noise, 4000), 12000)) * np.exp(-t * 3) * 0.25   # crash


class BalladGenre(Genre):
    name = "ballad"
    description = ("ballad: slow, emotional piano and strings, broken-chord verses, soft drums only in the chorus, "
                   "long expressive melody, a last chorus that lifts the key")
    bpm = (56, 84)
    modes = ("major", "minor")
    profile = PROFILE
    voices = {"piano": "grand piano", "rhodes": "electric piano", "nylon": "nylon guitar", "pad": "string pad"}

    def instruments(self, rng: np.random.Generator, sr: int, sampled):
        return Voices(sampled or LofiInstruments(rng, sr), rng, sr, sampled)

    def schedule(self, piece, plan):
        p, s, v = plan, piece.style, piece.inst
        B = 60 / s.bpm
        e, k, add = p.energy, p.key_offset, piece.add
        chorus = p.section in CHORUS
        keys = v.keys(s.chords)
        # a compound bar (6/8, 12/8) breathes in groups of three: a waltz's oom-pah-pah, not four beats stretched
        compound = s.beats > 4
        group = 3 if compound else 2
        starts = tuple(range(0, s.beats, group)) if compound else (0, 2)
        for chord, at in ([(p.chord, 0), (p.passing or p.chord, s.beats // 2)] if compound
                          else [(p.chord, 0), (p.passing or p.chord, 2)]):
            vc = piece.voice([x + k for x in chord.tones])
            piece.center = cast(int, float(np.mean(vc)))
            if chorus or s.chords == "pad":
                length = (group if compound else 2) * B * 0.95
                for i, m in enumerate(vc):
                    add(keys(m, length, 0.75), at * B + i * 0.012, (i - 1.5) * 0.2, 0.09)
            elif compound:      # the broken chord follows the bar's groups of three
                for j in range(group):
                    tone = ARPEGGIO[j % len(ARPEGGIO)]
                    m = vc[min(tone, len(vc) - 1)]
                    add(keys(m, B * 1.4, 0.65 + 0.1 * (j == 0)), (at + j) * B, (tone - 1) * 0.25, 0.08)
            else:
                for j, tone in enumerate(ARPEGGIO[:4]):
                    m = vc[min(tone, len(vc) - 1)]
                    add(keys(m, 1.5 * B, 0.65 + 0.1 * (j == 0)), (at + j / 2) * B, (tone - 1) * 0.25, 0.08)
        # strings: the chord held through the bar from the first chorus on, and under the release
        if chorus or p.section == "release":
            for i, m in enumerate(piece.voice([x + k for x in p.chord.tones])):
                add(v.strings(m - 12 if i == 0 else m, s.beats * B * 0.98, 0.5 + 0.4 * e), 0, (i - 1) * 0.35, 0.10)
        # bass: the composer's line, held
        for i, n in enumerate(p.bass):
            add(v.bass(n.midi, n.length * B * 0.98), n.beat * B, 0, 0.24 if i == 0 else 0.16)
        # drums: only in the chorus, soft: kick on 1, side-stick on 3, quarter hats, a crash opening the last one
        if "drums" in p.layers and chorus:
            dg = 0.6 + 0.5 * e
            add(v.drum("kick"), 0, 0, 0.34 * dg)
            if s.drums == "busy":
                add(v.drum("kick"), (s.beats / 2 + 0.5 if compound else 2.5) * B, 0, 0.22 * dg)
            if compound:    # a soft side-stick where each half of the bar turns, and one hat per group
                for b in starts[1:]:
                    add(v.drum("stick"), b * B, 0.1, 0.16 * dg)
                for b in starts:
                    add(v.drum("hat"), b * B, -0.3, 0.035 * dg)
            else:
                add(v.drum("stick"), 2 * B, 0.1, 0.16 * dg)
                for b in range(4):
                    add(v.drum("hat"), b * B, -0.3, 0.035 * dg)
            if p.section == "B'" and p.section_bar == 0:
                add(v.drum("crash"), 0, 0.3, 0.10 * dg)
        # lead: the melody, a touch louder in the chorus; the counter-melody on the strings
        if "lead" in p.layers:
            lead = v.keys(s.lead)
            for n in p.melody:
                add(lead(n.midi, n.length * B * 0.97, 0.9), n.beat * B, 0.1, 0.24 if chorus else 0.2)
        if "counter" in p.layers:
            for n in p.counter:
                add(v.strings(n.midi, n.length * B * 0.95, 0.5), n.beat * B + 0.03, -0.3, 0.06)

    def master(self, style):
        s = style
        return Master(space=0.3 + 0.7 * s.space, reverb=0.12 + 0.25 * s.space, room=0.4 + 1.6 * s.space,
                      vinyl=s.vinyl * 0.1, wow=0.05, tone=int(3200 * 4 ** s.brightness), drive=1.3,
                      threshold=-20.0, ratio=2.0)


GENRE = BalladGenre()
