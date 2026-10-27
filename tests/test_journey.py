"""Journeys (PM-004): a timeline of stages that moves the continuous style fields on its own, evaluated by the engine
once per bar on its rendered timeline, then sustained (or released) after the last stage."""
import time
from itertools import pairwise

import numpy as np
import pytest

from gentle_stream.engine import GLIDE_FIELDS, SR, Engine
from gentle_stream.journey import (
    BUILTIN,
    Journey,
    JourneySnapshot,
    Stage,
    unknown_journey,
)
from gentle_stream.player import Player
from gentle_stream.style import Style
from tests.test_player import FakeStream, pull_seconds, wait_for


@pytest.fixture(autouse=True)
def procedural_backend(tmp_path, monkeypatch):
    """These tests pin the procedural instruments: no soundfont in an empty cache."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))


START = {"bpm": 72.0, "energy": 0.2}
THREE = Journey("three", (Stage("Rise", 10, {"bpm": 90.0, "energy": 0.5}),
                          Stage("Hold", 10, {"energy": 0.8}),
                          Stage("Peak", 10, {"bpm": 120.0})))


def bpm_of(bar):
    return 240.0 / (len(bar) / SR)


# ------------------------------------------------------------ PM-007 file schema
@pytest.mark.parametrize("data", [None, [], {}, {"version": 2, "stages": []}, {"version": 1},
                                  {"version": 1, "stages": []}], ids=["null", "array", "missing-version", "bad-version", "missing-stages", "empty-stages"])
def test_pm007_rejects_invalid_file_shapes(data):
    with pytest.raises(ValueError):
        Journey.from_dict(data)


def test_pm007_rejects_stage_count_and_total_duration_exactly():
    with pytest.raises(ValueError, match=r'^"stages" must contain at most 24 stages$'):
        Journey.from_dict({"version": 1, "stages": [{"seconds": 10, "to": {}}] * 25})
    with pytest.raises(ValueError, match=r'^combined stage duration must be at most 43200 seconds$'):
        Journey.from_dict({"version": 1, "stages": [{"seconds": 14400, "to": {}}] * 4})


@pytest.mark.parametrize("data", [
    {"version": 1, "name": 3, "stages": [{"seconds": 10, "to": {}}]},
    {"version": 1, "stages": [{"name": 3, "seconds": 10, "to": {}}]},
    {"version": 1, "stages": [{"seconds": 10, "to": []}]},
], ids=["bad-top-name", "bad-stage-name", "bad-to"])
def test_pm007_rejects_structural_types(data):
    with pytest.raises(ValueError):
        Journey.from_dict(data)


def test_pm007_normalizes_every_continuous_field_to_its_declared_bound():
    warnings = []
    source = {"version": 1, "stages": [{"seconds": 10, "to": {
        "bpm": -1, "energy": 2, "brightness": -1, "space": 2,
        "swing": -1, "vinyl": 2, "lead_density": -1}}]}
    journey = Journey.from_dict({**source, "name": "bounds"}, warnings)
    assert journey.stages[0].to == {"bpm": 50.0, "energy": 1.0, "brightness": 0.0,
                                    "space": 1.0, "swing": 0.0, "vinyl": 1.0, "lead_density": 0.0}


@pytest.mark.parametrize("value", [True, 9, 14401, float("nan")], ids=["bool", "low", "high", "nan"])
def test_pm007_seconds_exact_error(value):
    with pytest.raises(ValueError, match=r'^stage 3: "seconds" must be a number between 10 and 14400$'):
        Journey.from_dict({"version": 1, "stages": [{"seconds": 10, "to": {}}, {"seconds": 10, "to": {}},
                                                       {"seconds": value, "to": {}}]})


def test_pm007_round_trip_and_unknown_keys_and_clamping_warnings():
    warnings = []
    journey = Journey.from_dict({"version": 1, "name": "x", "ignored": 1, "stages": [
        {"name": "s", "seconds": 10, "to": {field: 999}, "ignored": True} for field in GLIDE_FIELDS]}, warnings)
    assert len(warnings) == len(GLIDE_FIELDS)
    assert Journey.from_dict(journey.to_dict()) == journey
    assert journey.to_dict()["version"] == 1


@pytest.mark.parametrize("data", [
    {"version": 1, "stages": [{"seconds": 10, "to": {"nope": 1}}]},
    {"version": 1, "stages": [{"seconds": 10, "to": {}, "genre": "nope"}]},
    {"version": 1, "stages": [{"seconds": 10, "to": {}}], "end": "nope"},
])
def test_pm007_rejects_invalid_categories(data):
    with pytest.raises(ValueError):
        Journey.from_dict(data)


# ------------------------------------------------------------ Journey.at (pure)
def test_at_starts_from_the_given_values():
    assert THREE.at(0, START) == (0, 0.0, {"bpm": 72.0, "energy": 0.2})


@pytest.mark.parametrize("t, expected", [
    (10, (1, 0.0, {"bpm": 90.0, "energy": 0.5})),
    (20, (2, 0.0, {"bpm": 90.0, "energy": 0.8})),
    (30, (2, 1.0, {"bpm": 120.0, "energy": 0.8})),
], ids=["first-boundary", "second-boundary", "end"])
def test_at_returns_the_exact_stage_values_at_stage_boundaries(t, expected):
    assert THREE.at(t, START) == expected


@pytest.mark.parametrize("t, stage, bpm, energy", [
    (5, 0, 81.0, 0.35),
    (15, 1, 90.0, 0.65),
    (25, 2, 105.0, 0.8),
    (2.5, 0, 76.5, 0.275),
], ids=["first-mid", "second-mid", "third-mid", "first-quarter"])
def test_at_interpolates_linearly_from_the_previous_stage(t, stage, bpm, energy):
    index, progress, values = THREE.at(t, START)
    assert index == stage and progress == pytest.approx((t % 10) / 10)
    assert values == {"bpm": pytest.approx(bpm), "energy": pytest.approx(energy)}


def test_at_holds_the_final_values_after_the_end_and_clamps_negative_time():
    assert THREE.at(1e6, START) == (2, 1.0, {"bpm": 120.0, "energy": 0.8})
    assert THREE.at(-3, START) == THREE.at(0, START)


def test_at_is_pure():
    start = dict(START)
    first = THREE.at(12.5, start)
    assert THREE.at(12.5, start) == first and start == START


def test_a_journey_names_the_fields_it_owns_and_its_length():
    assert THREE.fields == ("bpm", "energy") and THREE.seconds == 30.0


@pytest.mark.parametrize("make", [
    lambda: Journey("x", ()),
    lambda: Journey("x", (Stage("a", 10, {"genre": 1.0}),)),
    lambda: Journey("x", (Stage("a", 0, {"bpm": 90.0}),)),
    lambda: Journey("x", (Stage("a", 10, {"bpm": 90.0}),), end="fade"),
    lambda: Journey("x", (Stage("a", 10, {"bpm": float("nan")}),)),
], ids=["no-stages", "discrete-field", "zero-seconds", "unknown-end", "nan-value"])
def test_an_invalid_journey_is_refused(make):
    with pytest.raises(ValueError):
        make()


def test_the_built_in_warm_up_climbs_tempo_and_energy_over_about_ten_minutes_and_sustains():
    warm = BUILTIN["warm-up"]
    assert warm.end == "sustain" and 540 <= warm.seconds <= 660 and len(warm.stages) >= 3
    assert warm.description
    _, _, first = warm.at(warm.stages[0].seconds, {"bpm": 72.0, "energy": 0.5, "brightness": 0.5,
                                                    "lead_density": 0.5})
    _, _, last = warm.at(warm.seconds, first)
    assert first["bpm"] == 60.0 and first["energy"] == 0.2
    assert last["bpm"] == 100.0 and last["energy"] == 0.9
    for journey in BUILTIN.values():
        assert set(journey.fields) <= set(GLIDE_FIELDS) and journey.name in BUILTIN


def test_unknown_journey_names_the_built_ins():
    assert unknown_journey("nope") == f'no journey called "nope" (choose from {", ".join(BUILTIN)})'


# ------------------------------------------------------------ the engine runs it
def test_a_three_stage_journey_rendered_offline_follows_the_plan_bar_by_bar():
    e = Engine(Style(bpm=72, energy=0.2), seed=21, samples=False)
    e.queue_journey(THREE)
    t, checked = 0.0, 0
    while t < THREE.seconds + 3:
        bar = e.render_bar()
        _, _, plan = THREE.at(t, START)
        assert abs(bpm_of(bar) - plan["bpm"]) <= 0.1            # the bar's own length says its tempo
        assert e.style.bpm == pytest.approx(plan["bpm"], abs=0.1) and e.style.energy == pytest.approx(plan["energy"])
        t += len(bar) / SR
        checked += 1
    assert checked >= 12 and e.piece == 1                       # in place: one piece throughout


def test_journey_time_is_the_rendered_seconds_since_it_started():
    e = Engine(Style(bpm=72), seed=22, samples=False)
    assert e.journey is None and e.journey_seconds is None
    e.render_bar()
    e.queue_journey(THREE)
    assert e.journey is None                                    # applied at the next bar, on the render thread
    bars = [e.render_bar() for _ in range(3)]
    assert e.journey is THREE
    assert e.journey_seconds == pytest.approx(sum(map(len, bars)) / SR)


def test_sustain_holds_the_final_values_for_fifty_more_bars():
    short = Journey("short", (Stage("a", 2, {"bpm": 130.0}), Stage("b", 2, {"energy": 0.9}),
                              Stage("c", 2, {"bpm": 140.0, "brightness": 0.8})))
    e = Engine(Style(bpm=120, energy=0.2), seed=23, samples=False)
    e.queue_journey(short)
    while e.journey_seconds is None or e.journey_seconds < short.seconds + 2:
        e.render_bar()
    for _ in range(50):
        bar = e.render_bar()
        assert len(bar) == round(240 / 140 * SR)
        assert (e.style.bpm, e.style.energy, e.style.brightness) == (140.0, 0.9, 0.8)
    assert e.journey is short


def test_release_drops_the_journey_after_the_last_stage_and_leaves_the_music_as_it_is():
    short = Journey("short", (Stage("a", 2, {"bpm": 130.0}), Stage("b", 2, {"energy": 0.9})), end="release")
    e = Engine(Style(bpm=120, energy=0.2), seed=24, samples=False)
    e.queue_journey(short)
    for _ in range(6):
        e.render_bar()
    assert e.journey is None and e.journey_seconds is None
    assert (e.style.bpm, e.style.energy) == (130.0, 0.9)           # the final values, reached before release
    e.queue_style(Style(bpm=80, energy=0.3))
    e.render_bar()
    assert (e.style.bpm, e.style.energy) == (80.0, 0.3)             # nothing owns the fields any more


@pytest.mark.parametrize("change", ["style", "next"])
def test_a_new_piece_during_a_journey_takes_the_journey_values_on_the_next_bar(change):
    e = Engine(Style(name="A", bpm=72, energy=0.2), seed=25, samples=False)
    e.queue_journey(THREE)
    t = 0.0
    for _ in range(4):
        t += len(e.render_bar()) / SR
    piece = e.piece
    if change == "style":
        e.queue_style(Style(name="B", genre="jazz", bpm=130, energy=0.95, brightness=0.1))
    else:
        e.queue_next()
    bar = e.render_bar()
    _, _, plan = THREE.at(t, START)
    assert e.piece == piece + 1 and e.bar == 1 and e.journey is THREE
    assert abs(bpm_of(bar) - plan["bpm"]) <= 0.1
    for style in (e.style, e._piece.style, e.composer.style):     # the piece starts with the journey's values
        assert style.bpm == pytest.approx(plan["bpm"], abs=0.1) and style.energy == pytest.approx(plan["energy"])
    if change == "style":
        assert (e.style.name, e.style.genre, e.style.brightness) == ("B", "jazz", 0.1)   # the rest is the mood's


def test_stop_journey_leaves_the_music_as_it_is():
    e = Engine(Style(bpm=72, energy=0.2), seed=26, samples=False)
    e.queue_journey(THREE)
    for _ in range(4):
        e.render_bar()
    e.stop_journey()
    e.render_bar()
    held = (e.style.bpm, e.style.energy)
    assert e.journey is None and held != (72.0, 0.2)
    for _ in range(3):
        e.render_bar()
    assert (e.style.bpm, e.style.energy) == held


DRIVEN = 'is driven by the journey "three"; stop it first (gentle-stream journey stop)'


def test_a_journey_cancels_glides_of_the_fields_it_owns_when_it_starts_and_keeps_the_others():
    e = Engine(Style(bpm=72), seed=27, samples=False)
    e.queue_glide({"bpm": 120, "space": 0.9}, 60)
    e.queue_journey(THREE)
    assert e.targets == {"bpm": 120.0, "space": 0.9}             # cancelled when it starts, not when queued
    e.render_bar()
    assert e.targets == {"space": 0.9}


# ------------------------------------------------------------ J1: a journey's fields cannot be glided
@pytest.mark.parametrize("when", ["queued", "running"])
def test_a_field_driven_by_the_journey_cannot_be_glided_and_nothing_is_applied(when):
    e = Engine(Style(bpm=72, energy=0.2), seed=33, samples=False)
    e.queue_journey(THREE)
    if when == "running":
        e.render_bar()
    with pytest.raises(ValueError) as error:
        e.queue_glide({"space": 0.9, "energy": 0.9}, 30)
    assert str(error.value) == f"energy {DRIVEN}"
    with pytest.raises(ValueError, match=r'^bpm is driven by the journey "three"'):
        e.queue_tempo(120, 30)
    assert e.targets == {}                                        # atomic: space was not queued either
    e.queue_glide({"space": 0.9, "swing": 0.1}, 30)             # fields the journey leaves alone still glide
    assert e.targets == {"space": 0.9, "swing": 0.1}


def test_after_a_queued_stop_or_replacement_only_the_next_journey_drives_its_fields():
    e = Engine(Style(bpm=72), seed=34, samples=False)
    e.queue_journey(THREE)
    e.render_bar()
    e.stop_journey()
    e.queue_glide({"bpm": 100}, 30)                               # from the next bar on, no journey drives bpm
    calm = Journey("calm", (Stage("Soft", 30, {"energy": 0.5}),))
    e.queue_journey(calm)
    e.queue_glide({"brightness": 0.9}, 30)
    with pytest.raises(ValueError, match='^energy is driven by the journey "calm"'):
        e.queue_glide({"energy": 0.9}, 30)


@pytest.mark.parametrize("end", ["stop", "release"])
def test_when_a_journey_ends_the_music_stays_exactly_where_it_left_it(end):
    journey = Journey("three", THREE.stages, end="release" if end == "release" else "sustain")
    e = Engine(Style(bpm=72, energy=0.2), seed=35, samples=False)
    e.queue_journey(journey)
    for _ in range(4):
        e.render_bar()
    with pytest.raises(ValueError):
        e.queue_tempo(140, 1)                                     # what used to take over when the journey ended
    if end == "stop":
        e.stop_journey()
        e.render_bar()
    else:
        while e.journey is not None:
            e.render_bar()
    held = (e.style.bpm, e.style.energy, len(e.render_bar()))
    assert e.journey is None and e.targets == {}
    for _ in range(5):
        assert (e.style.bpm, e.style.energy, len(e.render_bar())) == held


# ------------------------------------------------------------ J2: a stopped queued journey cancels nothing
def test_a_journey_queued_and_stopped_before_the_next_bar_leaves_earlier_glides_running():
    e = Engine(Style(bpm=72), seed=36, samples=False)
    e.queue_glide({"bpm": 120}, 20)
    e.render_bar()
    e.queue_journey(THREE)
    e.stop_journey()
    e.render_bar()
    assert e.journey is None and e.targets == {"bpm": 120.0}
    before = e.style.bpm
    e.render_bar()
    assert 72.0 < before < e.style.bpm < 120.0                    # still gliding


# ------------------------------------------------------------ J3: journey state follows the rendered bars
def test_journey_and_journey_seconds_describe_the_last_rendered_bar_even_mid_render():
    e = Engine(Style(bpm=72), seed=37, samples=False)
    seen = []
    schedule = e._schedule_bar

    def watching():                                               # what another thread sees while a bar renders
        seen.append((e.journey, e.journey_seconds))
        schedule()

    e._schedule_bar = watching
    e.render_bar()
    e.queue_journey(THREE)
    first = len(e.render_bar()) / SR                              # the journey's first bar
    second = first + len(e.render_bar()) / SR
    e.stop_journey()
    e.render_bar()
    assert seen == [(None, None), (None, None), (THREE, pytest.approx(first)), (THREE, pytest.approx(second))]
    assert (e.journey, e.journey_seconds) == (None, None)


def test_genre_stages_switch_at_old_piece_phrase_boundaries_preserving_the_journey_and_style():
    journey = Journey("genres", (Stage("ambient", 2.0, {"bpm": 60, "energy": 0.2}, genre="ambient"),
                                 Stage("lofi", 20.0, {"bpm": 80, "energy": 0.5}, genre="lofi"),
                                 Stage("synth", 20.0, {"bpm": 118, "energy": 0.9}, genre="synthwave")))
    style = Style(genre="ambient", key="C", mode="minor", progression=(1, 4, 6, 5))
    e = Engine(style, seed=40, samples=False)
    e.queue_journey(journey)
    changes = []
    old_piece = e.piece
    while len(changes) < 2:
        old_bar, old_genre, old_values = e.bar, e.style.genre, (e.style.bpm, e.style.energy)
        e.render_bar()
        if e.piece != old_piece:
            changes.append((old_bar, old_genre, e.style.genre, old_values, (e.style.bpm, e.style.energy)))
            assert e.composer.plan(0).section == "A"
            assert (e.style.key, e.style.mode, e.style.progression) == ("C", "minor", (1, 4, 6, 5))
            old_piece = e.piece
    assert [(bar % 4, old, new) for bar, old, new, _, _ in changes] == [(0, "ambient", "lofi"),
                                                                           (0, "lofi", "synthwave")]
    assert changes[0][4][0] < 80 and changes[0][4][1] < 0.5       # journey values, not a style reset
    assert changes[1][4][0] < 118 and changes[1][4][1] < 0.9


def test_builtin_ambient_to_synthwave_has_three_genre_stages_and_sustains():
    journey = BUILTIN["ambient-to-synthwave"]
    assert [s.genre for s in journey.stages] == ["ambient", "lofi", "synthwave"]
    assert journey.end == "sustain" and journey.stages[-1].to["bpm"] == 118.0


def test_a_journey_renders_deterministically_and_joins_bars_without_clicks():
    def run():
        e = Engine(Style(bpm=72, energy=0.2, drums="soft"), seed=28, samples=False)
        e.queue_journey(THREE)
        return [e.render_bar() for _ in range(10)]

    a, b = run(), run()
    assert all(np.array_equal(x, y) for x, y in zip(a, b, strict=True))
    inner = np.concatenate([np.abs(np.diff(x, axis=0)) for x in a])
    for x, y in pairwise(a):
        assert np.all(np.abs(y[0] - x[-1]) <= np.max(inner))
    assert max(np.max(np.abs(x)) for x in a) < 1.0


# ------------------------------------------------------------ progress snapshots
def test_the_engine_snapshots_the_journey_progress_of_each_bar_it_renders():
    e = Engine(Style(bpm=72, energy=0.2), seed=30, samples=False)
    e.render_bar()
    assert e.journey_snapshot is None                           # no journey, no snapshot
    e.queue_journey(THREE)
    t, snaps = 0.0, []
    snap: JourneySnapshot | None = None
    while t < THREE.seconds + 4:
        bar = e.render_bar()
        snaps.append((t, e.journey_snapshot, e.style.bpm))
        t += len(bar) / SR
    assert snaps[0][1] == JourneySnapshot("three", "Three", 1, 3, "Rise", 0.0, 72.0, 90.0, 30.0)
    for t, snap, bpm in snaps:
        index, progress, _ = THREE.at(t, START)
        assert snap is not None
        assert (snap.name, snap.title, snap.stage, snap.stages) == ("three", "Three", index + 1, 3)
        assert snap.stage_name == THREE.stages[index].name and snap.progress == pytest.approx(progress)
        assert snap.bpm == bpm and snap.target_bpm == (90.0, 90.0, 120.0)[index]   # "Hold" keeps 90 bpm
        assert snap.seconds_left == (None if t >= THREE.seconds else pytest.approx(THREE.seconds - t))
    assert snap is not None and snap.progress == 1.0 and snap.seconds_left is None   # sustaining at the end


def test_a_released_journey_leaves_no_snapshot_and_a_journey_without_tempo_targets_the_current_bpm():
    calm = Journey("calm", (Stage("Soft", 3, {"energy": 0.5}),), end="release")
    e = Engine(Style(bpm=80), seed=31, samples=False)
    e.queue_journey(calm)
    e.render_bar()
    snap = e.journey_snapshot
    assert snap is not None and snap.target_bpm == snap.bpm == 80.0
    for _ in range(3):
        e.render_bar()
    assert e.journey is None and e.journey_snapshot is None


def test_stopping_a_journey_clears_the_snapshot_from_the_next_bar():
    e = Engine(Style(bpm=72), seed=32, samples=False)
    e.queue_journey(THREE)
    e.render_bar()
    e.stop_journey()
    assert e.journey_snapshot is not None
    e.render_bar()
    assert e.journey_snapshot is None


def test_built_in_stages_are_immutable_and_journeys_compare_and_hash_by_value():
    stage = BUILTIN["warm-up"].stages[0]
    with pytest.raises(TypeError):
        stage.to["bpm"] = 140.0                                   # type: ignore[index]
    assert stage.to["bpm"] == 60.0
    source = {"bpm": 90.0}
    copy = Stage("Rise", 10, source)
    source["bpm"] = 140.0                                         # the stage keeps what it was given
    assert copy.to == {"bpm": 90.0} and copy == Stage("Rise", 10, {"bpm": 90.0})
    twin = Journey("three", tuple(Stage(s.name, s.seconds, dict(s.to)) for s in THREE.stages))
    assert twin == THREE and hash(twin) == hash(THREE)


def test_a_journey_title_defaults_to_its_capitalised_name():
    assert BUILTIN["warm-up"].title == "Warm-up"
    assert Journey("x", THREE.stages, title="Morning Climb").title == "Morning Climb"


def test_a_snapshot_round_trips_through_json_in_a_fixed_key_order():
    import json

    snap = JourneySnapshot("warm-up", "Warm-up", 2, 4, "Wake", 0.625, 66.5, 72.0, 412.25)
    data = snap.to_dict()
    assert list(data) == ["name", "title", "stage", "stages", "stage_name", "progress", "bpm", "target_bpm",
                          "seconds_left"]
    assert JourneySnapshot.from_dict(json.loads(json.dumps(data))) == snap
    sustaining = JourneySnapshot("warm-up", "Warm-up", 4, 4, "Glow", 1.0, 100.0, 100.0, None)
    assert JourneySnapshot.from_dict(sustaining.to_dict()) == sustaining


@pytest.mark.parametrize("data", [None, {}, {"name": "x"}, [1], {**JourneySnapshot(
    "a", "A", 1, 1, "s", 0.0, 60.0, 60.0, 1.0).to_dict(), "stage": "one"}], ids=["null", "empty", "partial", "list",
                                                                             "bad-type"])
def test_a_missing_or_malformed_snapshot_reads_as_none(data):
    assert JourneySnapshot.from_dict(data) is None


# ------------------------------------------------------------ the player pauses it
def test_pausing_the_player_stops_journey_time_bounded_by_the_prebuffer():
    streams = []
    engine = Engine(Style(bpm=120), seed=29, samples=False)
    engine.queue_journey(BUILTIN["warm-up"])
    p = Player(engine, stream_factory=lambda **kw: streams.append(FakeStream(**kw)) or streams[-1], prebuffer=0.5)
    p.start()
    stream = streams[0]
    try:
        pull_seconds(stream, 3.0)
        p.pause()
        pull_seconds(stream, 0.1)                                  # the fade-out
        wait_for(lambda: p.buffered_seconds >= 0.5)
        paused_at = engine.journey_seconds
        for _ in range(20):                                        # 2 s of callbacks while paused, and time to render
            pull_seconds(stream, 0.1)
        time.sleep(0.3)
        assert paused_at is not None
        assert engine.journey_seconds == paused_at
        assert paused_at - 3.1 <= 0.5 + 240 / 60                  # ahead of what was heard by the prebuffer and a bar
        p.play()
        pull_seconds(stream, 3.0)
        wait_for(lambda: engine.journey_seconds is not None and engine.journey_seconds > paused_at)
    finally:
        p.close()
