"""PM-037: open-ended stages last until you move on."""
import math

import pytest

from gentle_stream import journey_command
from gentle_stream.app import journey_line
from gentle_stream.bridge import journey_rules
from gentle_stream.engine import Engine
from gentle_stream.journey import Journey, stage_diff
from gentle_stream.style import Style

BPM = 120.0   # one bar is 2 s


def make(**open_stage):
    return Journey.from_dict({"version": 1, "name": "flow", "title": "Flow", "end": "sustain", "stages": [
        {"name": "Warm", "seconds": 20, "to": {"energy": 0.4}},
        {"name": "Flow", "seconds": "open", "to": {"energy": 0.8}, **open_stage},
        {"name": "Cool", "seconds": 20, "to": {"energy": 0.2}}]})


# ------------------------------------------------------------ the format
def test_an_open_stage_round_trips_with_its_ramp():
    j = make(ramp=40)
    flow = j.stages[1]
    assert flow.open and flow.ramp == 40 and math.isinf(flow.seconds)
    data = j.to_dict()
    assert data["stages"][1]["seconds"] == "open" and data["stages"][1]["ramp"] == 40
    assert Journey.from_dict(data).to_dict() == data
    assert "ramp" not in data["stages"][0] and data["stages"][0]["seconds"] == 20


def test_the_ramp_defaults_to_two_minutes():
    assert make().stages[1].ramp == 120


@pytest.mark.parametrize("stage, message", [
    ({"seconds": "forever"}, '"seconds" must be a number between 10 and 14400$'),   # the PM-007 message, unchanged
    ({"seconds": 60, "ramp": 30}, '"ramp" is only for "seconds": "open"'),
    ({"seconds": "open", "ramp": 5}, '"ramp" must be a number between 10 and 14400'),
    ({"seconds": "open", "ramp": "slow"}, '"ramp" must be a number between 10 and 14400'),
])
def test_bad_open_stages_are_refused(stage, message):
    with pytest.raises(ValueError, match=message):
        Journey.from_dict({"version": 1, "name": "x", "stages": [{"name": "A", "to": {}, **stage}]})


def test_open_stages_do_not_count_in_the_total_limit():
    stages = [{"name": f"S{i}", "seconds": 14400, "to": {}} for i in range(3)]
    j = Journey.from_dict({"version": 1, "name": "x", "stages": [*stages, {"name": "On", "seconds": "open", "to": {}}]})
    assert math.isinf(j.seconds)


# ------------------------------------------------------------ the timeline
def test_an_open_stage_ramps_then_holds_and_never_ends():
    j = make(ramp=40)
    start = {"energy": 0.0}
    assert j.at(20 + 20, start)[2]["energy"] == pytest.approx(0.6)        # halfway up the 40 s ramp (0.4 -> 0.8)
    assert j.at(20 + 40, start)[2]["energy"] == pytest.approx(0.8)
    index, progress, values = j.at(1e7, start)                             # days later
    assert (index, progress, values["energy"]) == (1, 1.0, pytest.approx(0.8))
    assert j.stage_index(1e7) == 1


def run_to(e, seconds):
    while e.samples_out < seconds * e.sr:
        e.render_bar()


def test_the_engine_stays_in_an_open_stage_until_skipped():
    e = Engine(Style(bpm=BPM, energy=0.2), seed=3, samples=False)
    e.queue_journey(make(ramp=20))
    run_to(e, 300)
    snap = e.journey_snapshot
    assert snap is not None and (snap.stage, snap.stage_name, snap.open) == (2, "Flow", True)
    assert snap.seconds_left is None
    assert e.style.energy == pytest.approx(0.8)


def test_skip_moves_to_the_next_stage_from_the_bar_after():
    e = Engine(Style(bpm=BPM, energy=0.2), seed=3, samples=False)
    e.queue_journey(make(ramp=20))
    run_to(e, 100)
    e.skip_journey()
    e.render_bar()                                                         # the bar after the skip
    snap = e.journey_snapshot
    assert snap is not None and (snap.stage, snap.stage_name, snap.open) == (3, "Cool", False)
    assert snap.progress == pytest.approx(0.0, abs=1e-9)                   # "Cool" starts here
    assert snap.seconds_left == pytest.approx(20)
    run_to(e, 100 + 2 + 10)
    assert e.style.energy == pytest.approx(0.8 + (0.2 - 0.8) * 0.5, abs=0.06)   # Cool ramps from Flow's 0.8


def test_skip_closes_the_open_stage_where_it_was():
    e = Engine(Style(bpm=BPM), seed=3, samples=False)
    e.queue_journey(make(ramp=20))
    run_to(e, 100)
    e.skip_journey()
    e.render_bar()
    current = e.journey
    assert current is not None and not current.stages[1].open
    assert current.stages[1].seconds == pytest.approx(80)                  # 20 s to 100 s
    assert math.isfinite(current.seconds)


def test_an_open_stage_reports_the_tempo_its_ramp_reaches():
    tempo = Journey.from_dict({"version": 1, "name": "x", "stages": [
        {"name": "Up", "seconds": "open", "ramp": 60, "to": {"bpm": 120}},
        {"name": "Down", "seconds": 60, "to": {"bpm": 70}}]})   # what the open stage's end would be at infinity
    snap = tempo.snapshot(10, {"bpm": 80.0}, 86.7)
    assert snap.target_bpm == 120 and snap.open


def test_without_open_stages_journeys_are_unchanged():
    plain = Journey.from_dict({"version": 1, "name": "x", "stages": [{"name": "A", "seconds": 30, "to": {}}]})
    assert "ramp" not in plain.to_dict()["stages"][0]
    snap = plain.snapshot(10, {}, 100)
    assert snap.open is False and snap.seconds_left == pytest.approx(20)


# ------------------------------------------------------------ status and text
def test_the_journey_line_says_open_instead_of_a_time_left():
    snap = make().snapshot(60, {"energy": 0.2}, BPM)
    line = journey_line(snap)
    assert line.endswith("· open") and "left" not in line
    before = make().snapshot(5, {"energy": 0.2}, BPM)                       # an open stage ahead: no end time yet
    assert journey_line(before).endswith("· open-ended")


def test_the_diff_and_the_list_show_open_stages(tmp_path, monkeypatch, capsys):
    closed = Journey.from_dict({"version": 1, "name": "flow", "stages": [
        {"name": "Warm", "seconds": 20, "to": {"energy": 0.4}},
        {"name": "Flow", "seconds": 60, "to": {"energy": 0.8}}]})
    assert stage_diff(closed, make(ramp=30))[1] == "  ~ Flow: 60 s -> open (ramp 30 s)"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from gentle_stream.journey import JourneyStore
    JourneyStore().save("Open one", make())
    assert journey_command("list") == 0
    assert "Open one" in (out := capsys.readouterr().out) and "3 stages, open-ended" in out


def test_the_journey_rules_offer_open_stages():
    rules = journey_rules()
    assert '"seconds": "open"' in rules and '"ramp"' in rules
