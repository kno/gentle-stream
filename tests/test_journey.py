"""Journeys (PM-004): a timeline of stages that moves the continuous style fields on its own, evaluated by the engine
once per bar on its rendered timeline, then sustained (or released) after the last stage."""
import time
from itertools import pairwise

import numpy as np
import pytest

from gentle_stream.engine import GLIDE_FIELDS, SR, Engine
from gentle_stream.journey import BUILTIN, Journey, Stage, unknown_journey
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


def test_a_journey_cancels_glides_of_the_fields_it_owns_and_keeps_the_others():
    e = Engine(Style(bpm=72), seed=27, samples=False)
    e.queue_glide({"bpm": 120, "space": 0.9}, 60)
    e.queue_journey(THREE)
    assert e.targets == {"space": 0.9}


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
        assert engine.journey_seconds == paused_at
        assert paused_at - 3.1 <= 0.5 + 240 / 60                  # ahead of what was heard by the prebuffer and a bar
        p.play()
        pull_seconds(stream, 3.0)
        wait_for(lambda: engine.journey_seconds > paused_at)
    finally:
        p.close()
