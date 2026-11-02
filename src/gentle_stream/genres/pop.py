"""Pop: verse and chorus songs with a repeated chorus hook, a backbeat and a clean, bright mix.

The chorus (B, B') comes back with the same melody every time, doubled an octave up, over driving eighth-note bass
and block chords on every beat; the verses (A, A') are lighter. Kick on 1 and 3, snare and clap on 2 and 4, eighth
hats, a snare fill into each chorus and a crash on its first beat. With the samples backend the keys and the
Standard kit are FluidR3_GM, the bass a Finger Bass; without it the lo-fi voices play them, without the dust.
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
DRUMS = {"kick": (36, 105, 0.4, 0.30), "snare": (38, 105, 0.4, 0.20), "clap": (39, 100, 0.3, 0.14),
         "hat": (42, 85, 0.15, 0.05), "crash": (49, 105, 1.8, 0.08)}   # GM key, velocity, seconds, rms

# Intro, verse, chorus, verse, chorus, an instrumental bridge, the chorus twice more, a short outro.
PROFILE = Profile(
    first_form=(("intro", 4), ("A", 8), ("B", 8), ("A'", 8), ("B", 8), ("breakdown", 8), ("B'", 8), ("B'", 8),
                ("release", 4)),
    form=(("A", 8), ("B", 8), ("A'", 8), ("B", 8), ("breakdown", 8), ("B'", 8), ("B'", 8), ("release", 4)),
    energy={"intro": .35, "A": .5, "B": .85, "A'": .55, "breakdown": .4, "B'": .95, "release": .45},
    rhythms=(((0, .5), (.5, 1), (1.5, .5), (2, 2)), ((0, 1), (1, .5), (1.5, 1.5), (3, 1)),
             ((.5, .5), (1, .5), (1.5, .5), (2, 1), (3, 1)), ((0, 1.5), (1.5, .5), (2, 1), (3, 1)),
             ((0, .5), (.5, .5), (1, 1), (2, .5), (2.5, 1.5))),
    steps=(-1, 1, 0, -1, 2, 1), leap_chance=0.3, leap=4,
    progressions={"major": ((1, 5, 6, 4), (6, 4, 1, 5), (1, 6, 4, 5), (4, 1, 5, 6)),
                  "minor": ((1, 6, 3, 7), (1, 4, 6, 5), (6, 4, 1, 5))})


class Voices:
    """The keys and lead of `tone` (lo-fi's procedural voices or the shared FluidR3_GM set), a bass and a pop kit."""

    def __init__(self, tone, rng: np.random.Generator, sr: int = SR, sampled=None):
        self.tone, self.rng, self.sr, self.s = tone, rng, sr, sampled
        self._bass = Program(33, velocity=(60, 115), tail=0.1, rms=0.25)

    def keys(self, name: str):
        return getattr(self.tone, name)

    def bass(self, m, dur):
        return self.s.play(self._bass, m, dur, 0.8) if self.s is not None else self.tone.sub(m, dur)

    def drum(self, name: str) -> np.ndarray:
        if self.s is not None:
            key, vel, secs, rms = DRUMS[name]
            return self.s.hit(Hit(0, key, vel, secs, rms))
        n_secs = {"kick": .45, "snare": .25, "clap": .2, "hat": .07, "crash": 1.2}[name]
        n = int(n_secs * self.sr)
        t = np.arange(n) / self.sr
        noise = self.rng.standard_normal(n)
        if name == "kick":
            return self.tone.kick()
        if name == "hat":
            return self.tone.hat()
        if name == "snare":
            body = cast(np.ndarray, bp(noise, 1500, 8000))
            return body * np.exp(-t * 22) * 0.9 + np.sin(2 * np.pi * 185 * t) * np.exp(-t * 35) * 0.6
        if name == "clap":   # three quick bursts, then the tail
            env = sum(np.exp(-np.clip(t - d, 0, None) * 120) * (t >= d) for d in (0, 0.011, 0.022)) + np.exp(-t * 18) * 0.4
            return cast(np.ndarray, bp(noise, 900, 6000)) * env * 0.7
        return cast(np.ndarray, lp(hp(noise, 5000), 14000)) * np.exp(-t * 3.5) * 0.35   # crash


class PopGenre(Genre):
    name = "pop"
    description = ("pop song: verse and chorus with a catchy repeated chorus hook, piano or keys, backbeat drums "
                   "(kick on 1 and 3, snare and clap on 2 and 4), driving bass, clean and bright")
    bpm = (90, 128)
    modes = ("major", "minor", "mixolydian")
    profile = PROFILE
    voices = {"piano": "bright pop piano", "rhodes": "electric piano", "nylon": "acoustic guitar strums",
              "pad": "synth pad"}

    def instruments(self, rng: np.random.Generator, sr: int, sampled):
        return Voices(sampled or LofiInstruments(rng, sr), rng, sr, sampled)

    def schedule(self, piece, plan):
        p, s, v = plan, piece.style, piece.inst
        B = 60 / s.bpm
        BAR = 4 * B
        e, k, add = p.energy, p.key_offset, piece.add
        chorus = p.section in CHORUS
        keys = v.keys(s.chords)
        # chords: block chords on every beat in the chorus, on beats 1 and 3 in the verse, held where it is quiet
        halves = ((p.chord, 0, 2), (p.passing or p.chord, 2, 2))
        for chord, at, beats in halves:
            vc = piece.voice([x + k for x in chord.tones])
            piece.center = cast(int, float(np.mean(vc)))
            hits = ((at, 1), (at + 1, 1)) if chorus or s.chords == "nylon" else ((at, beats),)
            if s.chords == "pad" or p.section in ("intro", "breakdown"):
                hits = ((at, beats),)
            for b, ln in hits:
                for i, m in enumerate(vc):
                    add(keys(m, ln * B * 0.92, 0.85 if b == at else 0.7), b * B + i * 0.008, (i - 1.5) * 0.2,
                        0.10 if s.chords != "pad" else 0.16)
        # bass: the composer's line in the verse, driving eighths on the chord root in the chorus
        line = [n.midi for n in p.bass]
        if chorus and e >= 0.5 and line:
            second = line[1] if p.passing is not None and len(line) > 1 else line[0]
            for i in range(8):   # the passing chord's root (the composer's second note) from beat 3
                add(v.bass(second if i >= 4 else line[0], B * 0.45), i * B / 2, 0, 0.26 if i % 2 == 0 else 0.2)
        else:
            for i, n in enumerate(p.bass):
                add(v.bass(n.midi, n.length * B * 0.95), n.beat * B, 0, 0.28 if i == 0 else 0.2)
        # drums: backbeat, eighth hats, a fill into the chorus and a crash on its downbeat
        if "drums" in p.layers:
            dg = 0.7 + 0.6 * e
            kicks = (0, 2, 2.5) if chorus else (0, 2)
            if s.drums == "busy":
                kicks += (1.5, 3.5)
            for b in kicks:
                add(v.drum("kick"), b * B, 0, 0.40 * dg)
            fill = p.next_section in CHORUS and p.section_bar == p.section_len - 1 and s.drums != "soft"
            for b in (1, 3):
                if fill and b == 3:
                    continue
                add(v.drum("snare"), b * B, 0.05, 0.22 * dg)
                if chorus or s.drums == "busy":
                    add(v.drum("clap"), b * B + 0.004, -0.05, 0.14 * dg)
            if fill:
                for i in range(4):
                    add(v.drum("snare"), (3 + i / 4) * B, 0.05, (0.10 + 0.04 * i) * dg)
            if chorus and p.section_bar == 0:
                add(v.drum("crash"), 0, 0.3, 0.12 * dg)
            hat_g = {"soft": 0.03, "lofi": 0.05, "busy": 0.06}.get(s.drums, 0.05)
            steps = 16 if s.drums == "busy" and chorus else 8
            for h in range(steps):
                add(v.drum("hat"), h * BAR / steps, -0.3, hat_g * dg * (1.0 if h % 2 == 0 else 0.6))
        # lead: the melody, doubled an octave up in the chorus (the hook); the counter-melody on the keys
        if "lead" in p.layers:
            lead = v.keys(s.lead)
            for n in p.melody:
                add(lead(n.midi, n.length * B * 0.95, 0.9), n.beat * B, 0.12, 0.22)
                if chorus:
                    add(lead(n.midi + 12, n.length * B * 0.9, 0.7), n.beat * B + 0.01, -0.12, 0.08)
        if "counter" in p.layers:
            for n in p.counter:
                add(keys(n.midi, n.length * B * 0.95, 0.6), n.beat * B + 0.02, -0.25, 0.07)

    def master(self, style):
        s = style
        return Master(space=s.space * 0.8, reverb=0.06 + 0.16 * s.space, room=0.2 + 1.0 * s.space,
                      vinyl=s.vinyl * 0.15, wow=0.1, tone=int(4000 * 4 ** s.brightness), drive=1.4,
                      threshold=-18.0, ratio=3.0)


GENRE = PopGenre()
