"""A genre's composition profile: the form, section energies and melodic character the composer writes with."""
import pytest

from gentle_stream import genres
from gentle_stream.composer import (
    DEFAULT_PROFILE,
    FIRST_FORM,
    FORM,
    Composer,
    Profile,
    cycle_position,
)
from gentle_stream.style import Style

TON = 50
SHORT = Profile(first_form=(("intro", 4), ("A", 8), ("B", 4), ("release", 4)), form=(("A", 8), ("B", 4), ("release", 4)))


def plans(profile, bars, seed=1):
    c = Composer(Style(), seed, TON, profile=profile)
    return [c.plan(b) for b in range(bars)]


def runs(ps):
    """[(section, bars)] in the order the sections play."""
    out = []
    for p in ps:
        if p.section_bar == 0:
            out.append([p.section, 0])
        out[-1][1] += 1
    return [tuple(r) for r in out]


def test_the_composer_plays_the_profile_form_then_loops_it():
    ps = plans(SHORT, 20 + 16 + 16)
    assert runs(ps) == [("intro", 4), ("A", 8), ("B", 4), ("release", 4)] + [("A", 8), ("B", 4), ("release", 4)] * 2


def test_without_a_profile_the_composer_plays_the_default_form():
    assert Composer(Style(), 1, TON).profile is DEFAULT_PROFILE
    assert DEFAULT_PROFILE.first_form == FIRST_FORM and DEFAULT_PROFILE.form == FORM
    first = sum(n for _, n in FIRST_FORM)
    assert runs(plans(None, first + sum(n for _, n in FORM))) == list(FIRST_FORM) + list(FORM)


def test_a_bar_plan_names_its_section_length_and_the_next_section():
    ps = plans(SHORT, 20 + 16)
    assert [(p.section, p.section_len, p.next_section) for p in (ps[0], ps[3], ps[4], ps[12], ps[16], ps[19])] == [
        ("intro", 4, "A"), ("intro", 4, "A"), ("A", 8, "B"), ("B", 4, "release"), ("release", 4, "A"),
        ("release", 4, "A")]
    assert (ps[35].section, ps[35].next_section) == ("release", "A")   # a looped cycle leads into the loop again


def test_the_default_plan_names_lengths_and_next_sections_of_the_default_form():
    ps = plans(None, 44)
    assert [(p.section, p.section_len, p.next_section) for p in (ps[0], ps[4], ps[12], ps[20], ps[28], ps[32], ps[43])] == [
        ("intro", 4, "A"), ("A", 8, "B"), ("B", 8, "A'"), ("A'", 8, "breakdown"), ("breakdown", 4, "B'"),
        ("B'", 8, "release"), ("release", 4, "A")]


def test_the_cycle_clock_follows_the_profile_form():
    assert SHORT.cycle_position(0) == (0, 20)
    assert SHORT.cycle_position(19) == (19, 20)
    assert SHORT.cycle_position(20) == (0, 16)
    assert SHORT.cycle_position(20 + 16 + 3) == (3, 16)
    assert cycle_position(0) == DEFAULT_PROFILE.cycle_position(0) == (0, 44)


def test_the_profile_energy_sets_each_section_energy():
    loud = Profile(energy={**DEFAULT_PROFILE.energy, "A": 0.9})
    default, louder = plans(None, 6), plans(loud, 6)
    assert louder[4].energy > default[4].energy
    assert louder[0].energy == default[0].energy


@pytest.mark.parametrize("kwargs, message", [
    ({"form": (("A", 8), ("chorus", 8))}, "unknown section 'chorus'"),
    ({"form": (("A", 6),)}, "section 'A' must last 4, 8 or 16 bars, not 6"),
    ({"form": ()}, "form must have at least one section"),
    ({"energy": {"A": 0.5}}, "energy has no value for 'intro'"),
    ({"chords_per_bar": 3}, "chords_per_bar must be 1 or 2"),
    ({"progressions": {"major": ((1, 9),)}}, "progressions for 'major' must be degrees 1 to 7"),
])
def test_an_invalid_profile_is_refused(kwargs, message):
    with pytest.raises(ValueError, match=message):
        Profile(**kwargs)


def test_every_genre_has_a_profile_the_engine_composes_with():
    for name, genre in genres.REGISTRY.items():
        assert isinstance(genre.profile, Profile), name


LONG = Profile(first_form=(("intro", 4), ("A", 16), ("B", 8), ("release", 4)), form=(("A", 16), ("B", 8), ("release", 4)))


def test_a_16_bar_section_plays_and_loops():
    ps = plans(LONG, 32 + 28)
    assert runs(ps) == [("intro", 4), ("A", 16), ("B", 8), ("release", 4), ("A", 16), ("B", 8), ("release", 4)]
    assert {p.section_len for p in ps[4:20]} == {16}


def test_a_16_bar_section_carries_two_question_answer_phrases():
    c = Composer(Style(lead_density=1.0), 1, TON, profile=LONG)
    a = [c.plan(b) for b in range(4, 20)]
    assert all(p.melody for p in a)
    assert [len(p.melody) for p in a[7:8]] == [1] and [len(p.melody) for p in a[15:16]] == [1]   # each phrase ends held
    assert all("lead" in p.layers for p in a)


def test_the_counter_melody_holds_the_last_bar_of_every_four_bar_phrase():
    c = Composer(Style(energy=1.0), 1, TON, profile=LONG)
    a = [c.plan(b) for b in range(4, 20)]
    assert all(len(p.counter) == (1 if p.section_bar % 4 == 3 else 2) for p in a)


def test_two_chords_per_bar_move_the_harmony_on_beat_three():
    two = Profile(chords_per_bar=2)
    style = Style(mode="major", progression=(1, 5, 6, 4))
    c = Composer(style, 1, TON, profile=two)
    a = [c.plan(b) for b in range(4, 12)]          # section A: cadence on its last two bars
    for p in a[:5]:
        assert p.passing is not None and p.passing.degree != p.chord.degree
    assert [p.chord.degree for p in a[:3]] == [1, 6, 1] and [p.passing.degree for p in a[:3]] == [5, 4, 5]
    assert a[-1].chord.degree == 1 and a[-1].passing is None    # the cadence lands on the tonic and holds it


def test_one_chord_per_bar_keeps_passing_chords_for_cadences_only():
    a = [Composer(Style(mode="major"), 1, TON).plan(b) for b in range(4, 12)]
    assert all(p.passing is None for p in a[:5])


def test_custom_b_progressions_are_used_and_a_missing_mode_falls_back():
    own = Profile(progressions={"major": ((2, 3, 2, 3),)})
    c = Composer(Style(mode="major", progression=(1, 5, 6, 4)), 1, TON, profile=own)
    b = [c.plan(i) for i in range(12, 18)]
    assert [p.chord.degree for p in b[:4]] == [2, 3, 2, 3]
    minor = Composer(Style(mode="minor", progression=(1, 6, 3, 7)), 1, TON, profile=own)
    assert minor.plan(12).chord.degree != 0     # minor is not named: the shared progressions still play
