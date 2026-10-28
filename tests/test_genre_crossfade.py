"""PM-020: a stage can crossfade two genres over a number of bars."""
import time

import numpy as np
import pytest

from gentle_stream.engine import SR, Engine, crossfade_gains
from gentle_stream.journey import Journey
from gentle_stream.style import Style

STYLE = Style(genre="lofi", key="D", mode="minor", bpm=90, energy=0.6, drums="lofi")
DATA = {"version": 1, "name": "blend", "stages": [
    {"name": "Lofi", "seconds": 30, "to": {"bpm": 90}, "genre": "lofi"},
    {"name": "Synthwave", "seconds": 120, "genre": "synthwave", "transition": {"bars": 8}},
]}


def run(data, bars, style=STYLE):
    """Every rendered bar with the engine's state after it: (audio, genre, piece, crossfading)."""
    e = Engine(style, seed=9, samples=False)
    e.queue_journey(Journey.from_dict(data))
    rows = []
    for _ in range(bars):
        x = e.render_bar()
        rows.append((x, e.style.genre, e.piece, e.crossfading))
    return e, rows


def rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.square(x.astype(np.float64)))))


# ------------------------------------------------------------ the journey file
def test_a_stage_transition_is_parsed_and_written_back():
    journey = Journey.from_dict(DATA)
    assert journey.stages[1].transition == 8 and journey.stages[0].transition is None
    assert journey.to_dict()["stages"][1]["transition"] == {"bars": 8}
    assert "transition" not in journey.to_dict()["stages"][0]
    assert Journey.from_dict(journey.to_dict()) == journey


@pytest.mark.parametrize("transition, message", [
    (8, 'stage 1: "transition" must be an object'),
    ({}, 'stage 1: "transition.bars" must be a whole number from 1 to 32'),
    ({"bars": 0}, 'stage 1: "transition.bars" must be a whole number from 1 to 32'),
    ({"bars": 33}, 'stage 1: "transition.bars" must be a whole number from 1 to 32'),
    ({"bars": 4.5}, 'stage 1: "transition.bars" must be a whole number from 1 to 32'),
    ({"bars": True}, 'stage 1: "transition.bars" must be a whole number from 1 to 32'),
], ids=["not-an-object", "missing", "zero", "too-many", "fraction", "boolean"])
def test_a_malformed_transition_is_rejected(transition, message):
    with pytest.raises(ValueError, match=message):
        Journey.from_dict({"version": 1, "stages": [{"seconds": 10, "genre": "jazz", "transition": transition}]},
                          name="bad")


# ------------------------------------------------------------ the crossfade
def crossfade_span(rows):
    """(first, last) bar mixed from both pieces: the flag is read after each bar, and the bar that ends the
    crossfade has already handed over when it is read."""
    faded = [i for i in range(len(rows)) if rows[i][3] or (i > 0 and rows[i - 1][3])]
    return faded[0], faded[-1]


def test_both_genres_play_together_for_the_transition_bars_then_the_new_one_takes_over():
    _, rows = run(DATA, 40)
    first, last = crossfade_span(rows)
    assert last - first + 1 == 8                                    # eight bars of both
    assert all(row[1] == "lofi" for row in rows[:last])            # the outgoing piece leads until the end
    assert rows[last][1] == "synthwave" and rows[last][2] == rows[first][2] + 1
    assert not any(row[3] for row in rows[last:])


def test_the_rms_stays_within_3_db_across_the_transition():
    _, rows = run(DATA, 40)
    first, last = crossfade_span(rows)
    before = rms_db(np.concatenate([row[0] for row in rows[first - 4: first]]))
    after = rms_db(np.concatenate([row[0] for row in rows[last + 1: last + 5]]))
    reference = (before + after) / 2
    for x, *_ in rows[first: last + 1]:
        assert abs(rms_db(x) - reference) <= 3.0


def test_there_is_no_click_at_either_end():
    _, rows = run(DATA, 40)
    first, last = crossfade_span(rows)
    inner = max(np.abs(np.diff(row[0], axis=0)).max() for row in rows)
    for i in (first, last + 1):
        jump = np.abs(rows[i][0][0].astype(np.float64) - rows[i - 1][0][-1].astype(np.float64)).max()
        assert jump <= inner


def test_render_speed_stays_above_four_times_real_time_during_the_transition():
    e = Engine(STYLE, seed=9, samples=False)
    e.queue_journey(Journey.from_dict(DATA))
    while not e.crossfading:
        e.render_bar()
    t0, audio = time.perf_counter(), 0
    while e.crossfading:
        audio += len(e.render_bar())
    assert audio / SR / (time.perf_counter() - t0) > 4


def test_without_a_transition_the_genre_step_is_immediate():
    data = {**DATA, "stages": [DATA["stages"][0], {k: v for k, v in DATA["stages"][1].items() if k != "transition"}]}
    _, rows = run(data, 30)
    assert not any(row[3] for row in rows)
    switch = next(i for i, row in enumerate(rows) if row[1] == "synthwave")
    assert rows[switch][2] == rows[switch - 1][2] + 1


def test_next_during_the_transition_drops_the_incoming_piece():
    e = Engine(STYLE, seed=9, samples=False)
    e.queue_journey(Journey.from_dict(DATA))
    while not e.crossfading:
        e.render_bar()
    e.queue_next()
    e.render_bar()
    assert not e.crossfading


def test_the_crossfade_keeps_the_power_constant():
    p = np.linspace(0, 1, 101)
    g_out, g_in = crossfade_gains(p)
    assert np.allclose(g_out ** 2 + g_in ** 2, 1.0)
    assert (g_out[0], g_in[0]) == (1.0, 0.0) and g_in[-1] == 1.0 and abs(g_out[-1]) < 1e-12
    assert np.all(np.diff(g_out) <= 0) and np.all(np.diff(g_in) >= 0)
