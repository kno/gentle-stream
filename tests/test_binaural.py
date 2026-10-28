import math
from typing import cast

import numpy as np
import pytest

from gentle_stream import genres
from gentle_stream.binaural import FADE_SECONDS, Binaural
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
    setting, or a (setting, glide seconds) pair, queued before that bar."""
    with_layer, without = engine(style), engine(style)
    with_layer.queue_binaural(setting)
    bars = []
    while sum(len(b) for b in bars) < seconds * SR:
        if changes and len(bars) in changes:
            change = changes[len(bars)]
            with_layer.queue_binaural(*(change if isinstance(change, tuple) else (change,)))
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


def test_once_it_has_faded_out_the_music_renders_exactly_as_if_it_never_played():
    once, never = engine(), engine()
    once.queue_binaural(Binaural(200, 6, 0.05))
    for _ in range(3):
        once.render_bar()
        never.render_bar()
    once.queue_binaural(None)
    fading = once.render_bar() - never.render_bar()           # the 2 s fade-out fits in one bar
    assert np.abs(fading).max() > 0 and len(fading) >= FADE_SECONDS * SR
    for _ in range(4):
        assert np.array_equal(once.render_bar(), never.render_bar())
    assert once.binaural is None


def test_a_setting_applies_from_the_next_rendered_bar():
    with_layer, without = engine(), engine()
    with_layer.queue_binaural(Binaural(200, 6, 0.05))
    assert np.abs(with_layer.render_bar() - without.render_bar()).max() > 0


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


# ------------------------------------------------------------ PM-014: fades and glides
def envelope(x, window=SR // 50):
    """The peak level of each `window` samples of one channel."""
    usable = len(x) // window * window
    return np.abs(x[:usable]).reshape(-1, window).max(axis=1)


def instantaneous_frequency(x):
    """Hz per sample from the phase differences of the analytic signal, averaged over 10 ms."""
    from scipy.signal import hilbert

    analytic = cast(np.ndarray, hilbert(x))
    phase = np.unwrap(np.angle(analytic))
    hz = np.diff(phase) * SR / (2 * math.pi)
    window = SR // 100
    usable = len(hz) // window * window
    return hz[:usable].reshape(-1, window).mean(axis=1)


def test_enabling_starts_from_silence_and_fades_in_over_two_seconds():
    setting = Binaural(200, 6, 0.05)
    x = np.concatenate(layer(setting, 4.0))[:, 0]
    assert x[0] == 0.0
    assert np.abs(x[: SR // 100]).max() < 0.01 * setting.level       # the first 10 ms are still almost silent
    rising = envelope(x[: int(FADE_SECONDS * SR)])
    assert np.all(np.diff(rising) >= -1e-4) and rising[-1] > 0.95 * setting.level
    assert envelope(x[int(2.2 * SR): 3 * SR]).min() > 0.98 * setting.level


def test_disabling_fades_out_over_two_seconds_then_stays_silent():
    setting = Binaural(200, 6, 0.05)
    bars = layer(setting, 12.0, changes={2: None})
    before, after = np.concatenate(bars[:2])[:, 0], np.concatenate(bars[2:])[:, 0]
    assert abs(after[0] - before[-1]) <= max_step(setting) + FLOAT32     # the fade starts where the tone was
    falling = envelope(after[: int(FADE_SECONDS * SR)])
    assert falling[0] > 0.95 * setting.level and np.all(np.diff(falling) <= 1e-4)
    assert np.abs(after[int(FADE_SECONDS * SR):]).max() <= FLOAT32


def test_a_glide_moves_the_frequencies_monotonically_and_keeps_the_phase_continuous():
    first, second = Binaural(200, 6, 0.05), Binaural(400, 10, 0.05)
    bars = layer(first, 16.0, changes={1: (second, 8.0)})
    start = len(bars[0])
    x = np.concatenate(bars)
    assert np.abs(np.diff(x, axis=0)).max() <= max(max_step(first), max_step(second)) + FLOAT32
    for channel, (low, high) in enumerate(zip(first.frequencies, second.frequencies, strict=True)):
        hz = instantaneous_frequency(x[start: start + 8 * SR, channel])[5:-5]   # away from the edges
        assert np.all(np.diff(hz) >= -0.05)                                     # monotonic, within the estimate
        t = (np.arange(5, 5 + len(hz)) + 0.5) / 100                             # each 10 ms window's middle
        assert np.allclose(hz, low + (high - low) * t / 8.0, atol=0.5)          # linear from one to the other
    after = instantaneous_frequency(x[start + 9 * SR: start + 11 * SR, 0])[5:-5]
    assert np.allclose(after, second.frequencies[0], atol=0.5)                  # it holds the target


def test_a_glide_with_no_time_changes_at_the_next_bar_like_pm_013():
    first, second = Binaural(200, 6, 0.05), Binaural(400, 10, 0.05)
    bars = layer(first, 12.0, changes={1: (second, 0.0)})
    hz = instantaneous_frequency(bars[1][:, 1])[5:-5]
    assert np.allclose(hz, second.frequencies[1], atol=0.5)


def test_turning_it_on_again_while_it_fades_out_comes_back_without_a_jump():
    setting = Binaural(200, 6, 0.05)
    with_layer, without = engine(), engine()
    with_layer.queue_binaural(setting)
    for _ in range(2):
        with_layer.render_bar()
        without.render_bar()
    with_layer.queue_binaural(None)
    with_layer.render_bar()
    without.render_bar()
    with_layer.queue_binaural(setting)
    x = (with_layer.render_bar() - without.render_bar())[:, 0]
    assert np.abs(np.diff(x)).max() <= max_step(setting) + FLOAT32
    assert envelope(x[int(2.2 * SR):]).min() > 0.98 * setting.level


def test_the_engine_reports_the_setting_it_is_heading_to():
    e = engine()
    e.queue_binaural(Binaural(200, 6, 0.05))
    assert e.binaural == Binaural(200, 6, 0.05)                 # queued: already what it will play
    e.render_bar()
    e.queue_binaural(Binaural(300, 6, 0.05), 30.0)
    e.render_bar()
    assert e.binaural == Binaural(300, 6, 0.05)                 # the target, while it glides there
    e.queue_binaural(None)
    assert e.binaural is None                                   # off at once, while it fades out


@pytest.mark.parametrize("seconds", [-1.0, 3600.1, math.nan])
def test_glide_seconds_outside_0_to_3600_are_rejected(seconds):
    with pytest.raises(ValueError, match="seconds must be between 0 and 3600"):
        engine().queue_binaural(Binaural(), seconds)
