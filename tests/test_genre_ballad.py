"""Ballad genre traits (S5): broken-chord piano verses without drums, choruses with block chords, strings and soft
drums, two chords a bar, long notes, and a last chorus that always lifts the key. Measured from what `schedule`
plays through a spy voice set."""
import numpy as np

from gentle_stream import genres
from gentle_stream.composer import Composer
from gentle_stream.engine import SR
from gentle_stream.genres.base import Piece
from gentle_stream.style import Style

BALLAD = genres.get("ballad")
STYLE = Style(genre="ballad", mode="major", progression=(1, 5, 6, 4), bpm=70, energy=0.5, drums="soft",
              chords="piano", lead="rhodes", lead_density=1.0)


class Spy:
    def __init__(self):
        self.pending = []

    def _sound(self, voice, midi=None):
        self.pending.append((voice, midi))
        return np.zeros(8)

    def keys(self, name):
        return lambda m, dur, vel=1.0: self._sound(f"keys:{name}", m)

    def strings(self, m, dur, vel=0.8):
        return self._sound("strings", m)

    def bass(self, m, dur):
        return self._sound("bass", m)

    def drum(self, name):
        return self._sound(name)


def bars(style=STYLE, seed=3, count=None):
    """[(plan, [(voice, beat, midi)])] for the first cycle."""
    profile = BALLAD.profile
    composer = Composer(style, seed, 50, BALLAD.chord, profile=profile)
    spy, out = Spy(), []
    piece = Piece(style, np.random.default_rng(seed), spy, 50, SR, np.zeros((SR * 8, 2)))
    beat = 60 / style.bpm
    events = []

    def add(sig, t, pan=0.0, g=1.0):
        voice, midi = spy.pending.pop(0)
        events.append((voice, round(t / beat, 2), midi))

    piece.add = add
    for b in range(count or profile.first_len):
        plan = composer.plan(b)
        events.clear()
        BALLAD.schedule(piece, plan)
        out.append((plan, list(events)))
    return out


def test_ballad_is_registered_and_offered_to_the_model():
    assert "ballad" in genres.NAMES and genres.get("ballad") is BALLAD
    assert "ballad" in BALLAD.description and BALLAD.bpm[1] <= 84


def test_two_verses_come_before_the_first_chorus():
    order = [p.section for p, _ in bars() if p.section_bar == 0]
    assert order == ["intro", "A", "A'", "B", "breakdown", "B'", "release"]


def test_the_harmony_moves_twice_a_bar_outside_the_cadences():
    for plan, _ in bars():
        if plan.section in ("A", "A'", "B") and plan.section_bar < plan.section_len - 3:
            assert plan.passing is not None, plan.bar


def test_the_last_chorus_always_lifts_the_key_and_nothing_else_does():
    for seed in range(6):
        played = bars(seed=seed)
        assert {p.section for p, _ in played if p.key_offset} == {"B'"}, seed


def test_verses_play_broken_chords_in_eighths_and_no_drums():
    plan, events = next((p, e) for p, e in bars() if p.section == "A" and p.section_bar == 1)
    keys = sorted(b for v, b, _ in events if v == "keys:piano")
    assert keys == [i / 2 for i in range(8)]                 # one tone at a time, on every eighth
    assert not [v for v, _, _ in events if v in ("kick", "stick", "hat", "strings")]


def test_choruses_bring_block_chords_strings_and_soft_drums():
    plan, events = next((p, e) for p, e in bars() if p.section == "B" and p.section_bar == 1)
    keys = [round(b, 1) for v, b, _ in events if v == "keys:piano"]   # its tones a few ms apart: a soft strum
    assert set(keys) == {0, 2} and len(keys) >= 6           # whole voicings on beats 1 and 3
    held = [m for v, b, m in events if v == "strings" and b == 0]   # the chord, held from the downbeat
    assert len(held) >= 3
    counter = {n.midi for n in plan.counter}
    assert all(m in counter for v, b, m in events if v == "strings" and b != 0)   # the rest is the counter-melody
    assert [b for v, b, _ in events if v == "kick"] == [0]
    assert [b for v, b, _ in events if v == "stick"] == [2]
    assert sorted(b for v, b, _ in events if v == "hat") == [0, 1, 2, 3]


def test_a_crash_opens_the_last_chorus_only():
    crashes = [(p.section, p.section_bar) for p, e in bars() if ("crash", 0.0, None) in e]
    assert crashes == [("B'", 0)]


def test_the_melody_sings_long_notes():
    notes = [n for p, _ in bars() for n in p.melody]
    assert np.mean([n.length for n in notes]) >= 1.5        # beats; lo-fi's motif averages about 1


# ------------------------------------------------------------ compound time: a waltz
def waltz(**extra):
    from dataclasses import replace
    return replace(STYLE, meter="6/8", bpm=180, **extra)


def test_a_six_eight_verse_breaks_the_chord_in_groups_of_three():
    plan, events = next((p, e) for p, e in bars(waltz()) if p.section == "A" and p.section_bar == 1)
    keys = sorted({round(b, 2) for v, b, _ in events if v == "keys:piano"})
    assert keys == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]              # six eighths, two groups of three
    assert not [v for v, _, _ in events if v in ("kick", "stick", "hat")]


def test_a_six_eight_chorus_marks_each_half_of_the_bar():
    plan, events = next((p, e) for p, e in bars(waltz()) if p.section == "B" and p.section_bar == 1)
    keys = sorted({round(b) for v, b, _ in events if v == "keys:piano"})   # its tones a few ms apart
    assert keys == [0, 3]                                       # the chord on each half
    assert [round(b, 2) for v, b, _ in events if v == "kick"] == [0.0]
    assert [round(b, 2) for v, b, _ in events if v == "stick"] == [3.0]
    assert sorted({round(b, 2) for v, b, _ in events if v == "hat"}) == [0.0, 3.0]


def test_four_four_ballad_keeps_its_own_pattern():
    plan, events = next((p, e) for p, e in bars() if p.section == "A" and p.section_bar == 1)
    keys = sorted({round(b, 2) for v, b, _ in events if v == "keys:piano"})
    assert keys == [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5]     # eighths, as before
