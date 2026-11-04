"""Ballad cadences at finite render and release-journey boundaries, never at live Stop."""

import json

import numpy as np
from scipy.io import wavfile

from gentle_stream import main
from gentle_stream.engine import SR, Engine
from gentle_stream.journey import Journey, Stage
from gentle_stream.style import Style


def test_ballad_render_cadences_without_changing_the_prefix_or_duration(tmp_path, capsys):
    out = tmp_path / "ballad.wav"
    mood = tmp_path / "style.json"
    mood.write_text(json.dumps({"genre": "ballad", "bpm": 120}))
    assert main(["render", "--procedural", "--mood-file", str(mood), "--seed", "9", "--seconds", "8", str(out)]) == 0
    assert capsys.readouterr() == (f"wrote {out}: 8 s, ballad, seed 9\n", "")
    rate, rendered = wavfile.read(out)
    assert (rate, rendered.dtype, rendered.shape) == (SR, np.dtype("int16"), (8 * SR, 2))
    engine = Engine(Style(genre="ballad", bpm=120), seed=9, samples=False)
    plain = np.concatenate([engine.render_bar() for _ in range(5)])[:8 * SR]
    plain = np.round(np.clip(plain, -1, 1) * 32767).astype(np.int16)
    assert np.array_equal(rendered[:4 * SR], plain[:4 * SR])
    assert not np.array_equal(rendered[4 * SR:], plain[4 * SR:])


def test_short_ballad_render_lands_on_tonic_with_exact_length(tmp_path, capsys):
    out = tmp_path / "short.wav"
    assert main(["render", "--procedural", "--genre", "ballad", "--seconds", "1", "--seed", "7", str(out)]) == 0
    assert capsys.readouterr() == (f"wrote {out}: 1 s, ballad, seed 7\n", "")
    rate, audio = wavfile.read(out)
    assert rate == SR and audio.shape == (SR, 2) and np.max(np.abs(audio.astype(np.int32))) > 0
    assert np.max(np.abs(audio[-1])) == 0


def test_six_eight_ballad_render_keeps_its_prefix_before_the_cadence(tmp_path, capsys):
    mood, out = tmp_path / "meter.json", tmp_path / "waltz.wav"
    mood.write_text(json.dumps({"genre": "ballad", "meter": "6/8", "bpm": 140}))
    assert main(["render", "--procedural", "--mood-file", str(mood), "--seconds", "8", "--seed", "7", str(out)]) == 0
    assert capsys.readouterr() == (f"wrote {out}: 8 s, ballad, seed 7\n", "")
    rate, audio = wavfile.read(out)
    assert rate == SR and audio.shape == (8 * SR, 2)
    engine = Engine(Style(genre="ballad", meter="6/8", bpm=140), seed=7, samples=False)
    unbounded = np.concatenate([engine.render_bar() for _ in range(4)])[:8 * SR]
    unbounded = np.round(np.clip(unbounded, -1, 1) * 32767).astype(np.int16)
    prefix = round(2 * engine.bar_seconds * SR)
    assert np.array_equal(audio[:prefix], unbounded[:prefix])
    assert not np.array_equal(audio[prefix:], unbounded[prefix:])


def test_ballad_finale_resolves_dominant_to_tonic_without_changing_the_form():
    engine = Engine(Style(genre="ballad", bpm=120, mode="major"), seed=19, samples=False)
    original = engine.composer.plan(1)
    dominant = engine.composer.finale_plan(1, 0)
    tonic = engine.composer.finale_plan(2, 1)
    assert (dominant.chord.degree, tonic.chord.degree) == (5, 1)
    assert dominant.section == tonic.section == "finale"
    assert len(dominant.melody) == len(tonic.melody) == 1
    assert all(p.layers == frozenset({"chords", "bass", "lead"}) for p in (dominant, tonic))
    assert engine.composer.plan(1) == original


def test_release_journey_cadences_once_then_music_continues():
    journey = Journey("finite", (Stage("last", 6, {}),), end="release")
    engine = Engine(Style(genre="ballad", bpm=120), seed=19, samples=False)
    engine.queue_journey(journey)
    sections, bars = [], []
    for _ in range(5):
        bar = engine.render_bar()
        assert len(bar) == 2 * SR and np.isfinite(bar).all()
        sections.append(engine.section)
        bars.append(bar)
    assert sections[:4] == ["intro", "finale", "finale", "intro"]
    assert np.max(np.abs(bars[3][0] - bars[2][-1])) < 0.05  # no click when the stream resumes
    assert engine.journey is None and engine.bar == 5


def test_tempo_ramp_does_not_repeat_the_release_cadence():
    journey = Journey("ramp", (Stage("faster", 8, {"bpm": 140}),), end="release")
    engine = Engine(Style(genre="ballad", bpm=60), seed=5, samples=False)
    engine.queue_journey(journey)
    steps = []
    original = engine.composer.finale_plan

    def record(bar, step):
        steps.append(step)
        return original(bar, step)

    engine.composer.finale_plan = record
    for _ in range(7):
        engine.render_bar()
        if engine.journey is None and steps:
            break
    assert steps == [0, 1]
    assert engine.journey is None


def test_sustaining_journey_and_explicit_stop_do_not_trigger_a_finale():
    journey = Journey("endless", (Stage("last", 2, {}),), end="sustain")
    engine = Engine(Style(genre="ballad", bpm=120), seed=19, samples=False)
    engine.queue_journey(journey)
    for _ in range(5):
        engine.render_bar()
        assert engine.section != "finale"
    engine.stop_journey()
    engine.render_bar()
    assert engine.section != "finale" and engine.journey is None
