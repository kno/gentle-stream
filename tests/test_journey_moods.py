"""PM-035: a mood during a journey adjusts the current stage instead of fighting the journey."""
from dataclasses import replace

import pytest

from gentle_stream import daemon
from gentle_stream.app import journey_line
from gentle_stream.engine import Engine
from gentle_stream.journey import Journey, JourneySnapshot
from gentle_stream.style import Style

BPM = 120.0   # one bar is 2 s

RAMP = Journey.from_dict({"version": 1, "name": "ramp", "title": "Ramp", "end": "sustain", "stages": [
    {"name": "Rise", "seconds": 60, "to": {"energy": 0.6, "brightness": 0.6}},
    {"name": "Hold", "seconds": 60, "to": {"energy": 0.7}}]})


def pair():
    """Two engines on the same journey: one gets the mood, the other is the journey alone."""
    a, b = (Engine(Style(bpm=BPM, energy=0.3, brightness=0.3, swing=0.05), seed=4, samples=False) for _ in range(2))
    a.queue_journey(RAMP)
    b.queue_journey(RAMP)
    return a, b


def bars(*engines, until):
    while engines[0].samples_out < until * engines[0].sr:
        for e in engines:
            e.render_bar()


def mood(e, **fields):
    """The mood a model would answer: the playing style with what the mood changes."""
    return replace(e.style, **fields)


# ------------------------------------------------------------ owned fields become an offset for the stage
def test_an_owned_field_follows_the_journey_with_the_mood_s_offset_until_the_stage_ends():
    a, b = pair()
    bars(a, b, until=20)
    a.queue_style(mood(a, energy=a.style.energy - 0.2, mood="darker"))
    for _ in range(19):                                    # the rest of "Rise" (20 s to 58 s)
        a.render_bar()
        b.render_bar()
        assert a.style.energy == pytest.approx(b.style.energy - 0.2, abs=0.011)   # one bar of the ramp at most
    bars(a, b, until=62)                                   # into "Hold"
    assert a.style.energy == pytest.approx(b.style.energy, abs=1e-9)     # the offset ended with the stage


def test_fields_the_journey_does_not_own_apply_directly_and_stay():
    a, b = pair()
    bars(a, b, until=20)
    a.queue_style(mood(a, swing=0.25, mood="lazy"))
    bars(a, b, until=70)
    assert a.style.swing == 0.25 and b.style.swing == 0.05            # still applied after the stage boundary
    assert a.style.energy == pytest.approx(b.style.energy, abs=1e-9)  # no owned field changed: no offset


def test_offsets_are_clamped_to_the_field_range():
    a, b = pair()
    bars(a, b, until=50)
    a.queue_style(mood(a, energy=1.0, mood="all out"))                # +0.45 or so on a ramp heading to 0.6
    bars(a, b, until=58)
    assert a.style.energy <= 1.0


def test_a_second_mood_changes_only_what_it_names():
    a, _ = pair()
    bars(a, until=10)
    a.queue_style(mood(a, energy=a.style.energy - 0.2, mood="darker"))
    a.render_bar()
    a.queue_style(mood(a, brightness=a.style.brightness + 0.1, mood="but brighter"))
    a.render_bar()
    snap = a.journey_snapshot
    assert snap is not None and snap.override is not None
    name, offsets = snap.override
    assert name == "but brighter"
    assert offsets["energy"] == pytest.approx(-0.2, abs=0.011) and offsets["brightness"] == pytest.approx(0.1,
                                                                                                            abs=0.011)


def test_the_bpm_a_model_copies_back_rounded_is_not_an_offset():
    a, _ = pair()
    owning_bpm = Journey.from_dict({"version": 1, "name": "t", "stages": [
        {"name": "Up", "seconds": 60, "to": {"bpm": 130}}]})
    a.queue_journey(owning_bpm)
    bars(a, until=11)
    a.queue_style(Style.from_dict(mood(a, energy=0.5, mood="calmer").to_dict()))   # bpm rounded to 0.1
    a.render_bar()
    snap = a.journey_snapshot
    assert snap is not None and snap.override is None                # energy is not owned here: nothing to name


def test_without_a_journey_a_mood_is_applied_as_before():
    e = Engine(Style(bpm=BPM, energy=0.3), seed=4, samples=False)
    e.render_bar()
    e.queue_style(mood(e, energy=0.8, mood="up"))
    e.render_bar()
    assert e.style.energy == 0.8 and e.journey_snapshot is None


# ------------------------------------------------------------ the status line names the override
def test_the_snapshot_names_the_override_until_the_stage_ends():
    a, _ = pair()
    bars(a, until=20)
    a.queue_style(mood(a, energy=a.style.energy - 0.2, brightness=a.style.brightness - 0.1, mood="darker"))
    a.render_bar()
    snap = a.journey_snapshot
    assert snap is not None and snap.override is not None
    assert snap.override[0] == "darker" and set(snap.override[1]) == {"energy", "brightness"}
    line = journey_line(snap)
    assert line.endswith(f' · mood "darker": brightness {snap.override[1]["brightness"]:+.2f}, energy '
                         f'{snap.override[1]["energy"]:+.2f} until "Rise" ends')
    bars(a, until=62)
    assert a.journey_snapshot is not None and a.journey_snapshot.override is None
    assert "mood" not in journey_line(a.journey_snapshot)


def test_a_mood_without_a_name_is_named_by_its_style():
    a, _ = pair()
    bars(a, until=20)
    a.queue_style(mood(a, energy=0.2, mood="", name="Night Drive"))
    a.render_bar()
    assert a.journey_snapshot is not None and a.journey_snapshot.override is not None
    assert a.journey_snapshot.override[0] == "Night Drive"


def test_the_override_travels_in_the_player_state_and_older_players_report_none():
    from tests.test_daemon import fake_player

    player = fake_player()
    player.engine.queue_journey(RAMP)
    player.engine.render_bar()
    player.engine.queue_style(mood(player.engine, energy=0.1, mood="darker"))
    player.engine.render_bar()
    player.now = player._meta()                                 # what the audio thread records for each bar
    data = daemon.state(player)["journey"]
    assert data["override"][0] == "darker" and "energy" in data["override"][1]
    snap = JourneySnapshot.from_dict(data)
    assert snap is not None and snap.override == ("darker", data["override"][1])
    del data["override"]
    old = JourneySnapshot.from_dict(data)
    assert old is not None and old.override is None


def test_a_restarted_or_edited_journey_drops_the_override():
    a, _ = pair()
    bars(a, until=20)
    a.queue_style(mood(a, energy=0.1, mood="darker"))
    a.render_bar()
    a.restart_journey()
    a.render_bar()
    assert a.journey_snapshot is not None and a.journey_snapshot.override is None
