"""Heavy: metal always on, built from riffs.

The rock genre's guitars, bass, kit and master in their metal flavor at any energy and drum level: sixteenth-note
chugs and gallops, double kick, china accents, a harder master. What makes it its own genre is how it composes: a
long riff intro, riff-like lines that hammer a few notes in eighths and sixteenths, a half-time break and a 16-bar
last chorus. `rock` keeps its own metal mode for busy, energetic styles.
"""
from __future__ import annotations

from ..composer import Profile
from .rock import RockGenre

# A riff intro, verse and chorus twice, a breakdown, a long last chorus and a short outro.
PROFILE = Profile(
    first_form=(("intro", 8), ("A", 8), ("B", 8), ("A'", 8), ("B", 8), ("breakdown", 8), ("B'", 16), ("release", 4)),
    form=(("A", 8), ("B", 8), ("A'", 8), ("B", 8), ("breakdown", 8), ("B'", 16), ("release", 4)),
    energy={"intro": .5, "A": .7, "B": .9, "A'": .75, "breakdown": .5, "B'": 1.0, "release": .5},
    tail_tilt=True,
    rhythms=(((0, .5), (.5, .5), (1, .5), (1.5, .5), (2, 1), (3, 1)),
             ((0, .25), (.25, .25), (.5, .5), (1.5, .5), (2, .5), (2.5, .5), (3, 1)),
             ((0, 1), (1, .5), (1.5, .5), (2, .5), (2.5, 1.5)), ((0, .75), (.75, .75), (1.5, .5), (2, 2))),
    steps=(0, 0, -1, 1, 0, -1), leap_chance=0.1, leap=4, span=3,
    progressions={"minor": ((1, 6, 7, 1), (1, 7, 6, 5), (1, 4, 6, 7)), "phrygian": ((1, 2, 1, 7), (1, 2, 3, 2))})


class HeavyGenre(RockGenre):
    name = "heavy"
    description = ("heavy metal: riff-based songs, sixteenth-note palm-muted chugs and gallops, double kick and china "
                   "accents at any energy, a hard and dense master")
    bpm = (100, 140)
    modes = ("minor", "phrygian")
    profile = PROFILE
    counter_mode = "echo"

    @staticmethod
    def flavor(style) -> str:
        return "metal"


GENRE = HeavyGenre()
