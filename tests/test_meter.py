"""Meter: a style names 4/4 (the default), 6/8 or 12/8; the bar, the composer and the choir count its beats, and
4/4 keeps rendering exactly as before."""
import numpy as np
import pytest

from gentle_stream import genres
from gentle_stream.composer import Composer
from gentle_stream.engine import Engine
from gentle_stream.style import METERS, Style

TON = 50


def test_the_meter_round_trips_and_a_style_without_one_is_four_four():
    assert Style().meter == "4/4" and Style().beats == 4
    for meter, beats in METERS.items():
        s = Style.from_dict({"meter": meter})
        assert (s.meter, s.beats) == (meter, beats) and s.to_dict()["meter"] == meter
    assert Style.from_dict({"meter": "3/4"}).meter == "4/4"          # unknown falls back
    assert Style(meter="6/8").variation(np.random.default_rng(2)).meter == "6/8"


@pytest.mark.parametrize("meter, beats", [("4/4", 4), ("6/8", 6), ("12/8", 12)])
def test_the_bar_lasts_as_many_beats_as_the_meter_has(meter, beats):
    e = Engine(Style(meter=meter, bpm=120), seed=1, samples=False)
    assert e.bar_seconds == pytest.approx(beats * 60 / 120)
    assert len(e.render_bar()) == round(e.sr * e.bar_seconds)


@pytest.mark.parametrize("meter", ["6/8", "12/8"])
def test_every_voice_stays_inside_the_bar(meter):
    beats = METERS[meter]
    c = Composer(Style(meter=meter, lead_density=1.0, energy=1.0), 4, TON)
    for bar in range(60):
        p = c.plan(bar)
        for voice in (p.melody, p.bass, p.counter):
            for n in voice:
                assert 0 <= n.beat < beats and n.length > 0 and n.beat + n.length <= beats + 0.51 * (beats / 4), \
                    (meter, bar, n)


@pytest.mark.parametrize("meter", ["6/8", "12/8"])
def test_phrases_still_end_held_every_four_bars(meter):
    beats = METERS[meter]
    c = Composer(Style(meter=meter, lead_density=1.0), 4, TON)
    main = ("A", "B", "A'", "B'", "release")
    ends = [p for p in (c.plan(b) for b in range(60)) if p.section in main and p.section_bar % 4 == 3]
    assert ends and all(len(p.melody) == 1 and p.melody[0].length == beats for p in ends)


@pytest.mark.parametrize("name", genres.NAMES)
def test_every_genre_renders_in_six_eight(name, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    e = Engine(Style(genre=name, meter="6/8", bpm=120), seed=3, samples=False)
    audio = np.concatenate([e.render_bar() for _ in range(8)])
    assert np.all(np.isfinite(audio)) and np.abs(audio).max() <= 0.9 + 1e-6
    assert np.abs(audio).max() > 0.01          # it plays, not silence
