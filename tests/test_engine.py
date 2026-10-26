import time

import numpy as np
import pytest

from gentle_stream.engine import SR, Engine
from gentle_stream.style import Style


@pytest.fixture(autouse=True)
def procedural_backend(tmp_path, monkeypatch):
    """These tests pin the procedural instruments: no soundfont in an empty cache (samples: test_samples.py)."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))


def render(engine, bars):
    return [engine.render_bar() for _ in range(bars)]


def test_bar_shape_and_length_follow_the_tempo():
    e = Engine(Style(bpm=80), seed=1)
    assert e.backend == "procedural"
    bar = e.render_bar()
    assert bar.dtype == np.float32 and bar.shape == (int(round(3.0 * SR)), 2)


def test_output_is_audible_and_never_clips():
    x = np.concatenate(render(Engine(Style(drums="busy", energy=1.0, brightness=1.0), seed=2), 10))
    assert np.max(np.abs(x)) < 1.0
    rms_db = 20 * np.log10(np.sqrt(np.mean(x[SR:] ** 2)))
    assert -30 < rms_db < -6


def test_same_seed_is_deterministic():
    a = np.concatenate(render(Engine(seed=7), 3))
    b = np.concatenate(render(Engine(seed=7), 3))
    assert np.array_equal(a, b)


def test_bars_join_without_clicks():
    """The step across each bar boundary is no larger than the steps inside the music itself."""
    bars = render(Engine(Style(drums="soft"), seed=3), 8)
    inner = np.concatenate([np.abs(np.diff(b, axis=0)) for b in bars])
    limit = np.max(inner)
    for a, b in zip(bars, bars[1:]):
        assert np.all(np.abs(b[0] - a[-1]) <= limit)


def test_renders_much_faster_than_real_time():
    e = Engine(Style(chords="pad", lead="nylon", drums="busy"), seed=4)
    t0 = time.perf_counter()
    bars = render(e, 6)
    elapsed = time.perf_counter() - t0
    assert elapsed < sum(len(b) for b in bars) / SR / 4


def test_queued_style_starts_a_new_piece_at_the_next_bar():
    e = Engine(Style(name="A", bpm=72), seed=5)
    e.render_bar()
    e.queue_style(Style(name="B", bpm=120))
    assert e.style.name == "A"            # nothing changes mid-bar
    bar = e.render_bar()
    assert e.style.name == "B" and e.piece == 2 and len(bar) == int(round(2.0 * SR))


def test_next_keeps_the_mood_and_changes_the_piece():
    base = Style(name="Rain", mood="rainy night", mode="dorian", energy=0.3, brightness=0.2)
    e = Engine(base, seed=6)
    e.render_bar()
    first_seed = e.seed
    e.queue_next()
    e.render_bar()
    assert e.piece == 2 and e.seed != first_seed
    assert (e.style.mood, e.style.mode, e.style.energy, e.style.brightness) == ("rainy night", "dorian", 0.3, 0.2)


def test_a_queued_style_wins_over_a_queued_next():
    e = Engine(seed=8)
    e.queue_style(Style(name="Chosen"))
    e.queue_next()
    e.render_bar()
    assert e.style.name == "Chosen" and e.piece == 2


@pytest.mark.parametrize("mode", ["minor", "major", "dorian", "phrygian", "lydian", "mixolydian"])
def test_every_mode_and_instrument_renders(mode):
    for chords, lead in (("piano", "rhodes"), ("nylon", "pad"), ("pad", "none")):
        x = np.concatenate(render(Engine(Style(mode=mode, chords=chords, lead=lead), seed=9), 3))
        assert np.all(np.isfinite(x)) and np.max(np.abs(x)) > 0.01


def test_engine_follows_the_song_form():
    e = Engine(Style(bpm=120), seed=10)
    seen = []
    for _ in range(20):
        e.render_bar()
        if not seen or seen[-1] != e.section:
            seen.append(e.section)
    assert seen == ["intro", "A", "B"]
    e.queue_next()
    e.render_bar()
    assert e.section == "intro" and e.bar == 1


def test_reverb_tail_rings_on_after_the_music_stops():
    """The convolution reverb keeps its tail across bars: silence the scheduler and the next bar still rings."""
    e = Engine(Style(space=1.0, vinyl=0.0, drums="busy", energy=1.0), seed=11)
    render(e, 4)
    e._schedule_bar = lambda: None
    e._acc[:] = 0                                  # no note tails left: only the master chain's state remains
    quiet = e.render_bar()
    rms = lambda a: float(np.sqrt(np.mean(a ** 2)))
    late = quiet[int(0.5 * SR):int(0.8 * SR)]      # after the 0.35 s early-reflection room has died out
    assert rms(late) > 1e-3 and rms(quiet[-SR // 4:]) < rms(late)


def test_queued_tempo_glides_bar_lengths_and_lands_on_the_target():
    e = Engine(Style(bpm=72), seed=12)
    e.queue_tempo(120, 10.0)
    lengths = [len(e.render_bar()) for _ in range(40)]   # 40 bars at ~0.5-1s each comfortably exceeds 10s
    # bar lengths strictly decrease while the glide runs, then settle at the target bar length
    glide_lengths = [n for n in lengths if n != lengths[-1]]
    assert all(a >= b for a, b in zip(glide_lengths, glide_lengths[1:])) and len(set(glide_lengths)) > 1
    assert lengths[-1] == int(round(2.0 * SR))          # 240 / 120 bpm = 2.0 s/bar


def test_queued_tempo_does_not_start_a_new_piece():
    e = Engine(Style(bpm=72), seed=13)
    e.render_bar()
    piece, bar = e.piece, e.bar
    e.queue_tempo(120, 5.0)
    for _ in range(20):
        e.render_bar()
        assert e.piece == piece
    assert e.bar == bar + 20


def test_bar_boundaries_during_a_tempo_glide_pass_the_no_click_check():
    e = Engine(Style(bpm=72, drums="soft"), seed=14)
    e.queue_tempo(120, 2.0)
    bars = render(e, 8)
    inner = np.concatenate([np.abs(np.diff(b, axis=0)) for b in bars])
    limit = np.max(inner)
    for a, b in zip(bars, bars[1:]):
        assert np.all(np.abs(b[0] - a[-1]) <= limit)


def test_same_seed_and_tempo_command_render_identical_audio():
    def run():
        e = Engine(Style(bpm=72), seed=15)
        e.render_bar()
        e.queue_tempo(118, 3.0)
        return np.concatenate(render(e, 6))

    assert np.array_equal(run(), run())


def test_queue_style_cancels_an_active_glide():
    e = Engine(Style(name="A", bpm=72), seed=16)
    e.queue_tempo(120, 5.0)
    e.render_bar()   # elapsed == 0 at this boundary: bpm has not moved yet, only the glide is now active
    e.render_bar()
    assert e.style.bpm != 72.0
    e.queue_style(Style(name="B", bpm=90))
    e.render_bar()
    assert e.target_bpm is None and e.style.bpm == 90.0


def test_zero_second_tempo_glide_applies_at_the_next_bar():
    e = Engine(Style(bpm=72), seed=17)
    e.queue_tempo(100, 0)
    e.render_bar()
    assert e.style.bpm == 100.0 and e.target_bpm is None


def test_queued_tempo_is_clamped_to_the_valid_range():
    e = Engine(Style(bpm=72), seed=18)
    e.queue_tempo(300, 0)
    e.render_bar()
    assert e.style.bpm == 140.0
    e.queue_tempo(-10, 0)
    e.render_bar()
    assert e.style.bpm == 50.0
