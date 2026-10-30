"""What the engine gives a sung phrase: the planned melody of the coming bars, even where the lead does not play it,
the chord's tones where no melody is planned (S4); and a clip played from an exact bar with its own duck (S5)."""
import logging

import numpy as np
import pytest

from gentle_stream.engine import Engine
from gentle_stream.sing import Note
from gentle_stream.style import Style


def engine(**style):
    return Engine(Style(**{"bpm": 120.0, **style}), seed=4, samples=False)


def planned(e, bar):
    return e.composer.plan(bar)


def first_bar(e, test, limit=200):
    return next(b for b in range(limit) if test(planned(e, b)))


def test_the_coming_melody_is_the_planned_one_in_seconds_from_the_bar():
    e = engine()
    bar = first_bar(e, lambda p: p.melody and planned(e, p.bar + 1).melody)
    beat = e.bar_seconds / 4
    want = tuple(Note(k * e.bar_seconds + n.beat * beat, n.length * beat, n.midi)
                 for k in (0, 1) for n in planned(e, bar + k).melody)
    assert e.melody_ahead(bar, 2) == want


def test_the_melody_is_sung_where_the_lead_does_not_play_it():
    e = engine(lead_density=0.2)
    bar = first_bar(e, lambda p: p.melody and "lead" not in p.layers)
    beat = e.bar_seconds / 4
    assert e.melody_ahead(bar, 1) == tuple(Note(n.beat * beat, n.length * beat, n.midi)
                                           for n in planned(e, bar).melody)


def test_the_chord_tones_carry_the_bars_key_lift(monkeypatch):
    from dataclasses import replace

    e = engine()
    bar = first_bar(e, lambda p: not p.melody)
    lifted = replace(planned(e, bar), key_offset=2)
    monkeypatch.setattr(e.composer, "plan", lambda b: lifted)
    tones = lifted.chord.tones
    assert [n.midi for n in e.melody_ahead(bar, 1)] == [e.ton + 2 + tones[i % len(tones)] + 12 for i in range(4)]


def test_a_bar_with_no_melody_planned_offers_its_chords_tones_one_a_beat():
    e = engine()
    bar = first_bar(e, lambda p: not p.melody)
    plan = planned(e, bar)
    beat = e.bar_seconds / 4
    tones = plan.chord.tones
    want = tuple(Note(i * beat, beat, e.ton + plan.key_offset + tones[i % len(tones)] + 12) for i in range(4))
    assert e.melody_ahead(bar, 1) == want


# ------------------------------------------------------------ a clip on an exact bar
def bars(e, n):
    return np.concatenate([e.render_bar() for _ in range(n)]).astype(float)


def test_a_clip_for_an_exact_bar_starts_on_its_first_sample_with_a_6_db_duck():
    a, b = engine(), engine()
    n = round(a.bar_seconds * a.sr)
    clip = np.zeros(int(1.5 * a.sr))
    clip[0] = 0.3
    a.queue_speech(clip, at_bar=3, duck_db=6.0)
    with_clip, without = bars(a, 6), bars(b, 6)
    diff = with_clip - without
    assert np.all(diff[:3 * n] == 0)
    assert diff[3 * n, 0] == pytest.approx(0.3, abs=1e-6)
    held = slice(3 * n + int(0.1 * a.sr), 3 * n + int(1.4 * a.sr))
    loud = np.abs(without[held, 0]) > 1e-4
    gain = with_clip[held, 0][loud] / without[held, 0][loud]
    assert np.allclose(gain, 10 ** (-6 / 20), atol=1e-4)


def test_a_clip_whose_bar_has_passed_is_dropped_and_logged(caplog):
    a, b = engine(), engine()
    for e in (a, b):
        bars(e, 4)
    clip = np.full(a.sr, 0.2)
    with caplog.at_level(logging.WARNING, logger="gentle_stream.engine"):
        a.queue_speech(clip, at_bar=3, duck_db=6.0)                 # the bar just gone
        a.queue_speech(np.zeros(10), duck_db=0.0)                   # a spoken one behind it still plays
        diff = bars(a, 4) - bars(b, 4)
    assert np.all(diff == 0)
    assert a._speech_queue == []
    assert "a sung phrase arrived after its bar (3, now 4) and is skipped" in caplog.text


def test_a_clip_for_an_exact_bar_waits_while_another_plays_and_is_dropped_if_that_makes_it_late(caplog):
    a, b = engine(), engine()
    n = round(a.bar_seconds * a.sr)
    long = np.zeros(int(2.5 * n))
    long[0] = 0.1
    sung = np.zeros(n)
    sung[0] = 0.3
    a.queue_speech(long)                             # plays bars 0 to 2
    a.queue_speech(sung, at_bar=1, duck_db=6.0)      # its bar comes while the other still plays
    with caplog.at_level(logging.WARNING, logger="gentle_stream.engine"):
        diff = bars(a, 6) - bars(b, 6)
    assert not np.any(np.isclose(diff[:, 0], 0.3, atol=1e-6))
    assert "after its bar (1, now 3)" in caplog.text


def test_spoken_phrases_keep_their_3_db_duck():
    a, b = engine(), engine()
    silent = np.zeros(a.sr)
    a.queue_speech(silent)
    with_clip, without = bars(a, 2), bars(b, 2)
    held = slice(int(0.1 * a.sr), int(0.9 * a.sr))
    loud = np.abs(without[held, 0]) > 1e-4
    assert np.allclose(with_clip[held, 0][loud] / without[held, 0][loud], 10 ** (-3 / 20), atol=1e-4)
