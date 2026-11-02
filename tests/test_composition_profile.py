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
    ({"form": (("A", 6),)}, "section 'A' must last 4 or 8 bars"),
    ({"form": ()}, "form must have at least one section"),
    ({"energy": {"A": 0.5}}, "energy has no value for 'intro'"),
])
def test_an_invalid_profile_is_refused(kwargs, message):
    with pytest.raises(ValueError, match=message):
        Profile(**kwargs)


def test_every_genre_has_a_profile_the_engine_composes_with():
    for name, genre in genres.REGISTRY.items():
        assert isinstance(genre.profile, Profile), name
