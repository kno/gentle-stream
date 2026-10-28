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


def test_vocal_mode_replaces_only_the_genre_lead_at_threshold_with_a_melodic_voice():
    plan = Composer(Style(), 3, 50).plan(8)
    plan = replace(plan, layers=frozenset({"lead", "bass"}), melody=(Note(0, 64, 1),))
    assert vocals.instrumental_plan(plan, 0.499, melodic=True) is plan
    changed = vocals.instrumental_plan(plan, 0.5, melodic=True)
    assert changed.layers == frozenset({"bass"})
    assert changed.melody == plan.melody and changed.bass == plan.bass


def test_without_a_melodic_voice_the_genre_keeps_its_lead_at_any_voice():
    plan = replace(Composer(Style(), 3, 50).plan(8), layers=frozenset({"lead", "bass"}), melody=(Note(0, 64, 1),))
    assert vocals.instrumental_plan(plan, 1.0) is plan


def engine_with(plan_layers, monkeypatch, melodic):
    engine = Engine(Style(voice=0.8), seed=3, samples=False)
    engine.melodic_vocals = melodic
    plan = replace(engine.composer.plan(0), layers=plan_layers, melody=(Note(0, 64, 1),))
    monkeypatch.setattr(engine.composer, "plan", lambda bar: plan)
    received, sung = [], []
    monkeypatch.setattr(type(engine.genre), "schedule", lambda self, piece, p: received.append(p))
    monkeypatch.setattr(vocals, "schedule", lambda piece, p, voice, sampled, melodic: sung.append((p, melodic)))
    engine.render_bar()
    return plan, received, sung


def test_engine_routes_original_melody_to_vocals_but_not_genre_with_a_melodic_voice(monkeypatch):
    plan, received, sung = engine_with(frozenset({"lead"}), monkeypatch, melodic=True)
    assert "lead" not in received[0].layers
    assert sung[0] == (plan, True)


def test_until_a_voice_pack_provides_a_melodic_voice_the_engine_keeps_the_lead_and_the_choir_pads(monkeypatch):
    assert Engine(Style(voice=0.8), seed=3, samples=False).melodic_vocals is False   # no M8 voice pack yet
    plan, received, sung = engine_with(frozenset({"lead"}), monkeypatch, melodic=False)
    assert received[0] == plan
    assert sung[0] == (plan, False)


def test_without_a_melodic_voice_the_choir_schedules_the_pad_even_at_high_voice(monkeypatch):
    from gentle_stream.genres.base import Piece

    monkeypatch.setattr(vocals, "_melody", lambda *a: pytest.fail("the vocal melody ran"))
    style = Style(voice=0.9)
    piece = Piece(style, np.random.default_rng(0), None, 50, SR, np.zeros((SR * 8, 2)))
    plan = replace(Composer(style, 3, 50).plan(8), layers=frozenset({"lead"}))
    vocals.schedule(piece, plan, 0.9)
    assert "choir_center" in piece.state                # the pad voiced its chord
