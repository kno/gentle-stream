"""Pop genre traits (S5): verse/chorus form with a repeated chorus hook doubled an octave up, a backbeat, eighth
hats, driving bass in the chorus, a fill into each chorus and a crash on its downbeat. Measured from what
`schedule` plays through a spy voice set."""
from dataclasses import replace

import numpy as np
import pytest

from gentle_stream import genres
from gentle_stream.composer import Composer
from gentle_stream.engine import SR
from gentle_stream.genres.base import Piece
from gentle_stream.style import Style

POP = genres.get("pop")
STYLE = Style(genre="pop", mode="major", progression=(1, 5, 6, 4), bpm=120, energy=0.7, drums="lofi",
              chords="rhodes", lead="piano", lead_density=1.0)


class Spy:
    """Every sound a bar asks for, as (voice, beat, midi or None), paired with its `add`."""

    def __init__(self):
        self.pending, self.events = [], []

    def _sound(self, voice, midi=None):
        self.pending.append((voice, midi))
        return np.zeros(8)

    def keys(self, name):
        return lambda m, dur, vel=1.0: self._sound(f"keys:{name}", m)

    def bass(self, m, dur):
        return self._sound("bass", m)

    def drum(self, name):
        return self._sound(name)


def bars(style=STYLE, seed=3, count=None):
    """[(plan, [(voice, beat, midi)])] for the first cycle."""
    profile = POP.profile
    composer = Composer(style, seed, 50, POP.chord, profile=profile)
    spy, out = Spy(), []
    piece = Piece(style, np.random.default_rng(seed), spy, 50, SR, np.zeros((SR * 8, 2)))
    beat = 60 / style.bpm

    def add(sig, t, pan=0.0, g=1.0):
        voice, midi = spy.pending.pop(0)
        spy.events.append((voice, round(t / beat, 3), midi))

    piece.add = add
    for b in range(count or profile.first_len):
        plan = composer.plan(b)
        spy.events = []
        POP.schedule(piece, plan)
        out.append((plan, list(spy.events)))
    return out


def test_pop_is_registered_and_offered_to_the_model():
    assert "pop" in genres.NAMES and genres.get("pop") is POP
    assert "chorus" in POP.description and POP.profile is not genres.get("lofi").profile


def test_the_form_alternates_verses_and_a_repeated_chorus():
    order = [(p.section, p.section_len) for p, _ in bars() if p.section_bar == 0]
    assert order == [("intro", 4), ("A", 8), ("B", 8), ("A'", 8), ("B", 8), ("breakdown", 8), ("B'", 8), ("B'", 8),
                     ("release", 4)]


def test_both_choruses_sing_the_same_hook():
    played = bars()
    choruses = [[p.melody for p, _ in played if p.section == "B" and p.section_bar == i] for i in range(8)]
    assert all(len(set(c)) == 1 for c in choruses)    # the second B repeats the first note for note
    assert any(c[0] for c in choruses)


def test_the_chorus_melody_is_doubled_an_octave_up_and_the_verse_is_not():
    checked = set()
    for plan, events in bars():
        if "lead" not in plan.layers or not plan.melody or plan.section not in ("A", "A'", "B", "B'"):
            continue
        lead = [(b, m) for v, b, m in events if v == "keys:piano"]
        up = [any(m == n.midi + 12 and abs(b - n.beat) < 0.05 for b, m in lead) for n in plan.melody]
        assert all(up) if plan.section in ("B", "B'") else not any(up), plan.bar
        checked.add(plan.section[0])
    assert checked == {"A", "B"}


@pytest.mark.parametrize("section", ["A", "B"])
def test_backbeat_kick_on_one_and_three_snare_on_two_and_four(section):
    plan, events = next((p, e) for p, e in bars() if p.section == section and p.section_bar == 1)
    kicks = sorted(b for v, b, _ in events if v == "kick")
    snares = sorted(b for v, b, _ in events if v == "snare")
    assert {0, 2} <= set(kicks)
    assert snares == [1, 3]
    assert sorted(b for v, b, _ in events if v == "hat") == [i / 2 for i in range(8)]   # eighth hats


def test_claps_double_the_snare_only_in_the_chorus():
    for plan, events in bars():
        if plan.section_bar != 1 or "drums" not in plan.layers:
            continue
        claps = [round(b, 1) for v, b, _ in events if v == "clap"]   # a few ms behind the snare: a flam, not a mask
        assert claps == ([1, 3] if plan.section in ("B", "B'") else []), plan.section


def test_a_snare_fill_leads_into_every_chorus_and_a_crash_opens_it():
    played = bars()
    for plan, events in played:
        last_before_chorus = plan.next_section in ("B", "B'") and plan.section_bar == plan.section_len - 1
        fill = [b for v, b, _ in events if v == "snare" and b >= 3]
        if "drums" in plan.layers and last_before_chorus:
            assert fill == [3, 3.25, 3.5, 3.75], plan.bar
        if plan.section in ("B", "B'") and plan.section_bar == 0 and "drums" in plan.layers:
            assert ("crash", 0.0, None) in events


def test_the_chorus_bass_drives_eighth_notes_on_the_roots_and_the_verse_plays_the_composer_line():
    for plan, events in bars():
        notes = [(b, m) for v, b, m in events if v == "bass"]
        if plan.section in ("B", "B'"):
            assert [b for b, _ in notes] == [i / 2 for i in range(8)]
            assert {m for b, m in notes if b < 2} == {plan.bass[0].midi}
        elif plan.section in ("A", "A'"):
            assert notes == [(n.beat, n.midi) for n in plan.bass]


def test_soft_drums_skip_the_fill():
    soft = replace(STYLE, drums="soft")
    for plan, events in bars(soft):
        if plan.next_section in ("B", "B'") and plan.section_bar == plan.section_len - 1 and "drums" in plan.layers:
            assert sorted(b for v, b, _ in events if v == "snare") == [1, 3]
