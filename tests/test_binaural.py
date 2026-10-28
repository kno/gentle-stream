import math

import numpy as np
import pytest

from gentle_stream import genres
from gentle_stream.binaural import Binaural
from gentle_stream.engine import SR, Engine
from gentle_stream.player import Player
from gentle_stream.style import Style
from tests.test_player import FakeStream, pull_seconds, wait_for

FLOAT32 = 1e-6   # the engine returns float32: subtracting two renders leaves rounding of this order

def engine(style=None, seed=7):
    return Engine(style or Style(), seed=seed, samples=False)


def layer(setting, seconds, changes=None, style=None):
    """The binaural layer alone, bar by bar: the same engine rendered with and without it, subtracted (the layer
    is added after the master chain, so the difference is exactly the layer). `changes` maps a bar index to a
    setting queued before that bar."""
    with_layer, without = engine(style), engine(style)
    with_layer.queue_binaural(setting)
    bars = []
    while sum(len(b) for b in bars) < seconds * SR:
        if changes and len(bars) in changes:
            with_layer.queue_binaural(changes[len(bars)])
        bars.append(with_layer.render_bar().astype(np.float64) - without.render_bar().astype(np.float64))
    return bars


def max_step(setting):
    """The largest sample-to-sample step of the higher of the two sines."""
    return setting.level * 2 * math.sin(math.pi * (setting.carrier + setting.beat / 2) / SR)


# ------------------------------------------------------------ settings
@pytest.mark.parametrize("values", [(40, 0.5, 0.0), (1000, 40, 0.08), (200, 6, 0.05)])
def test_settings_inside_the_ranges_are_accepted(values):
    setting = Binaural(*values)
    assert (setting.carrier, setting.beat, setting.level) == values


@pytest.mark.parametrize("values, message", [
    ((39.9, 6, 0.05), "carrier must be between 40 and 1000 Hz"),
    ((1000.1, 6, 0.05), "carrier must be between 40 and 1000 Hz"),
    ((200, 0.4, 0.05), "beat must be between 0.5 and 40 Hz"),
    ((200, 40.1, 0.05), "beat must be between 0.5 and 40 Hz"),
    ((200, 6, -0.01), "level must be between 0 and 0.08"),
    ((200, 6, 0.081), "level must be between 0 and 0.08"),
    ((math.nan, 6, 0.05), "carrier must be between 40 and 1000 Hz"),
    ((200, math.inf, 0.05), "beat must be between 0.5 and 40 Hz"),
    ((True, 6, 0.05), "carrier must be a number"),
])
def test_settings_outside_the_ranges_are_rejected(values, message):
    with pytest.raises(ValueError, match=message):
        Binaural(*values)


def test_the_left_tone_is_below_the_carrier_and_the_right_one_above():
    assert Binaural(200, 6, 0.05).frequencies == (197.0, 203.0)


def test_the_setting_round_trips_as_a_dict():
    setting = Binaural(200, 6, 0.05)
    assert setting.to_dict() == {"carrier": 200.0, "beat": 6.0, "level": 0.05}
    assert Binaural.from_dict(setting.to_dict()) == setting


def test_binaural_is_off_by_default():
    assert engine().binaural is None


# ------------------------------------------------------------ acceptance criteria
def test_fft_finds_carrier_minus_and_plus_half_the_beat_on_left_and_right():
    setting = Binaural(200, 6, 0.05)
    x = np.concatenate(layer(setting, 2.0))[: 2 * SR]
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    bin_width = freqs[1]
    for channel, expected in zip((0, 1), setting.frequencies, strict=True):
        peak = freqs[np.argmax(np.abs(np.fft.rfft(x[:, channel])))]
        assert abs(peak - expected) <= bin_width


def test_the_phase_is_continuous_across_bar_boundaries():
    setting = Binaural(1000, 40, 0.08)
    bars = layer(setting, 12.0)
    x = np.concatenate(bars)
    assert np.abs(np.diff(x, axis=0)).max() <= max_step(setting) + FLOAT32
    assert len(bars) >= 3                                   # several boundaries were crossed


def test_a_new_setting_keeps_the_phase_continuous():
    first, second = Binaural(200, 6, 0.05), Binaural(400, 10, 0.05)
    x = np.concatenate(layer(first, 6.0, changes={2: second}))
    assert np.abs(np.diff(x, axis=0)).max() <= max(max_step(first), max_step(second)) + FLOAT32


@pytest.mark.parametrize("name", genres.NAMES)
def test_the_peak_stays_below_one_with_the_loudest_level(name):
    e = engine(Style(genre=name, energy=1.0, brightness=1.0, lead_density=1.0, space=1.0, vinyl=1.0))
    e.queue_binaural(Binaural(1000, 40, 0.08))
    x = np.concatenate([e.render_bar() for _ in range(8)])
    assert np.all(np.isfinite(x)) and np.max(np.abs(x)) < 1.0


def test_turning_it_off_renders_the_music_exactly_as_if_it_never_played():
    once, never = engine(), engine()
    once.queue_binaural(Binaural(200, 6, 0.05))
    for _ in range(3):
        once.render_bar()
        never.render_bar()
    once.queue_binaural(None)
    for _ in range(4):
        assert np.array_equal(once.render_bar(), never.render_bar())
    assert once.binaural is None


def test_a_setting_applies_from_the_next_rendered_bar():
    e = engine()
    e.queue_binaural(Binaural(200, 6, 0.05))
    assert e.binaural is None
    e.render_bar()
    assert e.binaural == Binaural(200, 6, 0.05)


def test_next_with_binaural_on_stays_click_free():
    streams = []

    def factory(**kw):
        streams.append(FakeStream(**kw))
        return streams[-1]

    e = Engine(Style(name="First"), seed=1)
    e.queue_binaural(Binaural(1000, 40, 0.08))
    p = Player(e, stream_factory=factory, prebuffer=0.5)
    p.start()
    try:
        wait_for(lambda: p.buffered_seconds >= 0.5)
        stream = streams[0]
        pull_seconds(stream, 0.5)
        before = p.underruns
        p.next()
        x = pull_seconds(stream, 0.3)
        assert p.underruns == before
        assert np.abs(np.diff(x, axis=0)).max() < 0.05
    finally:
        p.close()
