"""PM-025: audible pitch and articulation, not just control envelopes."""
from dataclasses import replace

import numpy as np
import pytest
from scipy.signal import correlate

from gentle_stream import samples, vocals
from gentle_stream.composer import Composer, Note
from gentle_stream.engine import Engine
from gentle_stream.style import Style
from gentle_stream.synth import SR, mtof


def pitch(x, target):
    x = x - np.mean(x)
    corr = correlate(x, x, mode="full", method="fft")[len(x) - 1:]
    lo, hi = int(SR / (target * 1.3)), int(SR / (target / 1.3))
    k = lo + int(np.argmax(corr[lo:hi]))
    a, b, c = corr[k - 1:k + 2]
    delta = 0.5 * (a - c) / (a - 2 * b + c)
    return SR / (k + delta)


@pytest.fixture(params=[False, True], ids=["procedural", "sampled"])
def backend(request):
    if not request.param:
        return None
    sf = samples.soundfont_path()
    renderer = samples.load_renderer(sf) if sf else None
    if renderer is None:
        pytest.skip("FluidSynth/soundfont unavailable")
    return samples.SampleInstruments(renderer, np.random.default_rng(3))


@pytest.mark.parametrize("midi", [60, 64, 67, 72])
def test_note_centres_follow_planned_pitch(backend, midi):
    x = vocals.melodic_note(midi, 1.0, "o", None, "lofi", backend)
    measured = pitch(x[int(0.45 * SR):int(0.55 * SR)], mtof(midi))
    assert abs(1200 * np.log2(measured / mtof(midi))) < 30
    assert np.isfinite(x).all()


@pytest.mark.parametrize("interval", [-4, -2, 2, 4, 5])
def test_close_notes_slide_then_reach_target(backend, interval):
    midi, previous = 64, 64 - interval
    x = vocals.melodic_note(midi, 0.6, "o", previous, "lofi", backend)
    early = pitch(x[int(0.02 * SR):int(0.05 * SR)], mtof(midi - interval * 0.6))
    late = pitch(x[int(0.14 * SR):int(0.24 * SR)], mtof(midi))
    cents = 1200 * np.log2(early / mtof(midi))
    if abs(interval) <= 4:
        assert cents * interval < 0 and abs(cents) > 40
    else:
        assert abs(cents) < 30
    assert abs(1200 * np.log2(late / mtof(midi))) < 30


def test_vocal_mode_replaces_only_the_genre_lead_at_threshold():
    plan = Composer(Style(), 3, 50).plan(8)
    plan = replace(plan, layers=frozenset({"lead", "bass"}), melody=(Note(0, 64, 1),))
    assert vocals.instrumental_plan(plan, 0.499) is plan
    changed = vocals.instrumental_plan(plan, 0.5)
    assert changed.layers == frozenset({"bass"})
    assert changed.melody == plan.melody and changed.bass == plan.bass


def test_engine_routes_original_melody_to_vocals_but_not_genre(monkeypatch):
    engine = Engine(Style(voice=0.8), seed=3, samples=False)
    plan = replace(engine.composer.plan(0), layers=frozenset({"lead"}), melody=(Note(0, 64, 1),))
    monkeypatch.setattr(engine.composer, "plan", lambda bar: plan)
    received = []
    monkeypatch.setattr(type(engine.genre), "schedule", lambda self, piece, p: received.append(p))
    sung = []
    monkeypatch.setattr(vocals, "schedule", lambda piece, p, *args: sung.append(p))
    engine.render_bar()
    assert "lead" not in received[0].layers
    assert sung[0] == plan
