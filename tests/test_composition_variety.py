"""Musical variety: a verse without a question phrase, a chorus with its own progression, a motif developed afresh
every cycle on the genre's own rhythms, and a counter-melody that can answer the lead instead of moving against it."""
import numpy as np

from gentle_stream import genres
from gentle_stream.composer import DEFAULT_PROFILE, ENERGY, Composer, Profile
from gentle_stream.style import MODES, Style

TON = 50
CHORUS = Profile(
    first_form=(("intro", 4), ("verse", 8), ("chorus", 8), ("A", 8), ("B", 8)),
    form=(("verse", 8), ("chorus", 8), ("A", 8), ("B", 8)),
    energy={**ENERGY, "verse": .4, "chorus": .9})


def plans(profile=CHORUS, seed=3, bars=60, **style):
    c = Composer(Style(**style), seed, TON, profile=profile)
    return c, [c.plan(b) for b in range(bars)]


def bars_of(ps, section):
    return [p for p in ps if p.section == section]


# ------------------------------------------------------------ verse and chorus
def test_a_verse_plays_its_melody_in_every_bar_without_a_question():
    c, ps = plans(lead_density=1.0)
    first_cycle = [p for p in ps if p.bar < 32]                   # the form runs on: 60 bars hold two cycles
    verse = [p for p in first_cycle if p.section == "verse"]
    assert len(verse) == 8 and all(p.melody for p in verse)
    assert all("lead" in p.layers for p in verse)
    assert verse[0].bar == 4 and verse[-1].bar == 11


def test_the_chorus_plays_the_style_hook():
    c, ps = plans(mode="major", progression=(1, 6, 3, 7), hook=(4, 5, 6, 4))
    chorus = bars_of(ps, "chorus")
    assert [p.chord.degree for p in chorus[:4]] == [4, 5, 6, 4]


def test_without_a_hook_the_chorus_uses_section_bs_progression():
    _, a = plans(mode="major", hook=(4, 5, 6, 4))
    _, b = plans(mode="major")
    assert [p.chord.degree for p in bars_of(a, "chorus")[:4]] == [4, 5, 6, 4]
    assert [p.chord.degree for p in bars_of(b, "chorus")[:4]] == [p.chord.degree for p in bars_of(b, "B")[:4]]


def test_the_hook_is_a_style_field_that_round_trips_and_varies_keeping_its_shape():
    s = Style.from_dict({"hook": [4, 5, 6, 4]})
    assert s.hook == (4, 5, 6, 4) and s.to_dict()["hook"] == [4, 5, 6, 4]
    assert Style().hook is None and Style().to_dict()["hook"] is None
    assert Style.from_dict({"hook": [9]}).hook is None            # invalid: not a degree
    rotated = Style(hook=(4, 5, 6, 4)).variation(np.random.default_rng(3)).hook
    assert rotated is not None and sorted(rotated) == sorted((4, 5, 6, 4))


# ------------------------------------------------------------ development per cycle
def test_each_cycle_develops_the_motif_differently():
    c = Composer(Style(), 7, TON)
    heads, tails = [], []
    for cycle in range(4):
        c.plan(cycle * 100)                                       # forces a cycle boundary
        heads.append(c.head)
        tails.append(tuple(n for n in c.motif if n[0] >= 4))
    assert len(set(tails)) > 1 and len(set(heads)) == 1


def test_the_development_draws_its_rhythm_from_the_profiles_own_bars():
    own = Profile(rhythms=(((0, 2), (2, 2)), ((0, 4),)))    # only two bars on offer: the shared set never plays
    c = Composer(Style(), 5, TON, profile=own)
    before = c.head
    c.plan(own.first_len)                                      # the second cycle develops the motif
    tail = tuple(n for n in c.motif if n[0] >= 4)
    assert c.head == before and {n[0] for n in tail} <= {4, 6}


# ------------------------------------------------------------ the echo counter
def test_the_echo_counter_takes_the_leads_rhythm_from_the_bar_before():
    c, ps = plans(lead_density=1.0)
    echo = Composer(Style(lead_density=1.0), 3, TON, profile=CHORUS, echo_counter=True)
    plain = [echo.plan(b) for b in range(60)]
    for i, p in enumerate(plain):
        if "counter" not in p.layers or p.section_bar == 0 or not plain[i - 1].melody:
            continue   # a section's first bar has no bar before it inside the section: the plain pattern plays
        lead = plain[i - 1].melody[:2]
        assert [round(n.beat, 2) for n in p.counter] == [round(n.beat, 2) for n in lead], p.bar


def test_contrary_and_echo_counters_both_stay_on_the_chords_tones():
    for echo in (False, True):
        c = Composer(Style(lead_density=1.0, energy=1.0), 3, TON, profile=CHORUS, echo_counter=echo)
        for b in range(60):
            p = c.plan(b)
            chord = p.passing if p.passing is not None else p.chord
            tones = {(TON + t + p.key_offset) % 12 for t in p.chord.tones[:4]}
            passing = {(TON + t + p.key_offset) % 12 for t in chord.tones[:4]}
            tones |= passing if p.passing is not None else set()
            assert all(n.midi % 12 in tones for n in p.counter), (echo, p.bar)


# ------------------------------------------------------------ pop and the default
def test_pop_composes_a_verse_and_a_chorus_before_its_older_stages():
    pop = genres.get("pop")
    order = [n for n, _ in pop.profile.form]
    assert order[:2] == ["verse", "chorus"] and order[-1] == "release"
    assert order.count("chorus") >= 4                    # the chorus comes back, note for note
    assert pop.profile.energy["chorus"] > pop.profile.energy["verse"]
    assert pop.counter_mode == "echo"


def test_lofi_still_keeps_the_default_profile_and_no_hook():
    assert genres.get("lofi").profile is DEFAULT_PROFILE
    assert Style().hook is None and Composer(Style(), 1, TON).prog_chorus is None


def test_every_mode_still_plans_a_full_form_with_the_new_sections():
    for mode in MODES:
        c = Composer(Style(mode=mode, hook=(1, 5, 6, 4)), 2, TON, profile=CHORUS)
        ps = [c.plan(b) for b in range(48)]
        assert {p.section for p in ps} >= {"verse", "chorus"}
        assert all(p.melody or p.section in ("intro", "breakdown") for p in ps)


def tilts(profile, cycles=6):
    """How far above the head's last step each cycle's new tail starts (the first cycle does not develop)."""
    c = Composer(Style(), 9, TON, profile=profile)
    c._plan_cycle()
    out = []
    for _ in range(cycles):
        c._plan_cycle()
        head = [n for n in c.motif if n[0] < 4]
        tail = [n for n in c.motif if n[0] >= 4]
        out.append(tail[0][1] - (head[-1][1] - 1))
    return out


def test_the_developed_tail_starts_a_step_higher_or_lower_on_every_third_cycle():
    assert set(tilts(Profile(tail_tilt=True))) == {0, 1, -1}
    assert set(tilts(Profile(tail_tilt=False))) == {0}          # the default never tilts: lo-fi renders as before


def test_the_chorus_sings_a_step_above_the_verse():
    def melodies(bars_range):
        c = Composer(Style(lead_density=1.0), 4, TON, profile=CHORUS)
        return [n.midi for b in bars_range for n in c.plan(b).melody]

    assert np.mean(melodies(range(12, 20))) > np.mean(melodies(range(4, 12)))   # chorus over its verse


def test_a_repeated_section_the_cycle_lifts_plays_in_the_new_key():
    """A chorus repeated while the same cycle lifts the key cannot replay verbatim: it must move with the lift."""
    lifting = Profile(first_form=(("verse", 8), ("chorus", 8), ("chorus", 8), ("release", 4)),
                      form=(("verse", 8), ("chorus", 8), ("chorus", 8), ("release", 4)),
                      energy={**ENERGY, "verse": .4, "chorus": .9}, lift_chance=1.0, lift_at=("chorus",))
    c = Composer(Style(lead_density=1.0), 3, TON, profile=lifting)
    first = [c.plan(b) for b in range(8, 16)]
    second = [c.plan(b) for b in range(16, 24)]
    assert {p.key_offset for p in second} != {0}
    assert [p.chord.tones for p in second] != [p.chord.tones for p in first]
