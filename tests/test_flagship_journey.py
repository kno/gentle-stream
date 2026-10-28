"""PM-021: ambient-to-synthwave is the 20-minute reference journey; its render keeps these regression metrics."""
import numpy as np
import pytest

from gentle_stream.engine import SR, Engine
from gentle_stream.journey import BUILTIN
from gentle_stream.style import Style

FLAGSHIP = BUILTIN["ambient-to-synthwave"]


def test_the_flagship_lasts_twenty_minutes_and_uses_every_continuity_feature():
    journey = FLAGSHIP
    assert journey.seconds == 20 * 60 and journey.end == "sustain"
    genres = [s.genre for s in journey.stages if s.genre is not None]
    assert genres[0] == "ambient" and genres[-1] == "synthwave" and "lofi" in genres
    assert any(s.transition for s in journey.stages)               # crossfaded genre steps (PM-020)
    assert any(s.layers for s in journey.stages)                   # parts entering per stage (PM-018)
    assert journey.drums == "energy"                               # drums build with the energy (PM-019)
    assert journey.owns_binaural                                    # the optional texture fades in and out (PM-015)
    assert any(s.curve != "linear" for s in journey.stages)


def onsets_per_second(x: np.ndarray) -> float:
    """Note onsets per second of mono `x`: frames whose energy jumps well above the recent average."""
    frame = 512
    usable = len(x) // frame * frame
    energy = np.sqrt(np.mean(np.square(x[:usable].reshape(-1, frame)), axis=1))
    floor = 0.1 * np.sqrt(np.mean(np.square(x)))
    onsets, last = 0, -10
    for i in range(8, len(energy)):
        if energy[i] > floor and energy[i] > 1.4 * np.mean(energy[i - 8:i]) and i - last > 4:
            onsets, last = onsets + 1, i
    return onsets / (len(x) / SR)


def rms_db(x: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(np.square(x)))))


@pytest.fixture(scope="module")
def flagship_render():
    """The whole journey rendered offline: (audio, bpm of each bar, seconds at each bar's start)."""
    e = Engine(Style(), seed=2026, samples=False)
    e.queue_journey(FLAGSHIP)
    bars, bpms, starts, t = [], [], [], 0.0
    while t < FLAGSHIP.seconds:
        starts.append(t)
        bpms.append(e.style.bpm)
        x = e.render_bar()
        bars.append(x.astype(np.float64).mean(axis=1))
        t += len(x) / SR
    return np.concatenate(bars), bpms, starts


def per_stage(audio: np.ndarray, measure) -> list[float]:
    out, begin = [], 0.0
    for stage in FLAGSHIP.stages:
        a, b = int(begin * SR), int((begin + stage.seconds) * SR)
        out.append(measure(audio[a + int(10 * SR): b]))             # skip the first seconds of each change
        begin += stage.seconds
    return out


@pytest.mark.slow
def test_the_tempo_never_falls_after_the_opening_stage(flagship_render):
    _, bpms, starts = flagship_render
    rising = [bpm for bpm, start in zip(bpms, starts, strict=True) if start >= FLAGSHIP.stages[0].seconds]
    assert all(b >= a - 1e-9 for a, b in zip(rising, rising[1:], strict=False))   # the first stage approaches 60
    assert rising[0] == pytest.approx(60.0, abs=0.5) and rising[-1] == pytest.approx(118.0, abs=0.5)


@pytest.mark.slow
def test_the_loudness_rises_within_bounds(flagship_render):
    audio, _, _ = flagship_render
    levels = per_stage(audio, rms_db)
    assert all(-35 <= level <= -6 for level in levels), levels
    # the bus compressor evens out loudness within a genre and each genre's master sets its level (measured at
    # 2026: ambient -18, lo-fi -13, synthwave -15 dBFS): no stage drops more than 2.5 dB, the end is 2.5 dB louder
    assert all(b >= a - 2.5 for a, b in zip(levels, levels[1:], strict=False)), levels
    assert levels[-1] - levels[0] >= 2.5, levels


@pytest.mark.slow
def test_the_onset_density_rises(flagship_render):
    audio, _, _ = flagship_render
    density = per_stage(audio, onsets_per_second)
    assert all(b >= 0.85 * a for a, b in zip(density, density[1:], strict=False)), density
    assert density[-1] >= 1.5 * density[0], density
