"""Live glide of the continuous style fields (PM-002): the playing piece evolves in place, and a constant style keeps
rendering exactly what it rendered before live glides existed.

The golden hashes were captured once from the base commit f4ffaea (before any live-evolution change) in a scratch
checkout: 120 bars per genre, seed 2026, procedural instruments, sha256 over the float32 bytes of every bar. They
are constants here on purpose; tests never read git history. Every genre but lo-fi was captured again once its own
composition profile changed how it composes (feat/composition-profiles); lo-fi keeps the default profile and its
original hashes. Genres added later (pop, ballad, heavy) were captured when they were added, and every genre but lo-fi again
once its own composition profile and its developing tail changed how it writes (feat/composition-variety); lo-fi
keeps the default profile and its original hashes.
"""
import hashlib

import numpy as np
import pytest

from gentle_stream import genres
from gentle_stream.engine import GLIDE_FIELDS, SR, Engine
from gentle_stream.style import Style

GOLDEN_BARS = 120
GOLDEN_SEED = 2026
GOLDEN_STYLES = {
    "default": {},
    "busy": {"energy": 0.9, "lead_density": 0.8, "brightness": 0.7, "space": 0.3},
}
GOLDEN = {
    ("default", "lofi"): "589cef6fbb213f1ad92371949ef5bdbf3b5ffb2df02a7e9be664a8663b9f2439",
    ("default", "ambient"): "7f23e7d2572cdd96f40b80acfb38b1f3672d3906575ef8d72b5c308d37c65cd4",
    ("default", "chiptune"): "2550ebabaf8307abea181562b8eb30239ef528dddf9540149c558a5ab44172db",
    ("default", "synthwave"): "cd0bc2caeaca7ece4c73909548aaae0caba8af1a36b67d6a1940b15ec81ced7b",
    ("default", "jazz"): "fe66324f8645ad8a4ffe100c40a6911fe0c6cc8521e604644018d0805da8468a",
    ("default", "rock"): "1d570ee74d12f7136bde170439d4f00d4a9e1cd448284b074221c5c4ef1a757a",
    ("default", "electro"): "88393175e396fa8b5c8603ab0667628d6cb53c717158589188be76ddcb2078a0",
    ("default", "electrohouse"): "99585b23bbc0e17bc41d0b3fae999a97033c827d8af9e8e39aa102ab57387b67",
    ("default", "cumbia"): "6600531f75275ff684cac5122fe3415d691f3361b7bfb1ba3d413221799b4d54",
    ("default", "dubstep"): "e2aa4b6b22be6d35f8d31bc4006697d4b2e0febcd6e7b899d470fb7c83aae845",
    ("default", "pop"): "7614c85d588b5b6895feade5cac08070764cd5025223133a43a8b1027c9fc234",
    ("default", "ballad"): "11d9cf06c222ede07fc4067ee8ba392c4447a8789f7c5288fed20479b2ae9240",
    ("default", "heavy"): "cb189f32b39d90a7f73206a2dacbbfa9497ba130789cb576fa4bc95a1eee7d08",
    ("busy", "lofi"): "3dcd51720d894c3402304fbc0865021dbba3b8d2318988bb2324cd8e77f56d82",
    ("busy", "ambient"): "67b66f51b1349e4381de413bbd9c461ae9fb0a6fbc127d7b479c5eda83678e96",
    ("busy", "chiptune"): "99d14512ade290f6494ccb0686d3dc81097025cdec4903db5b7afed1caf98e9f",
    ("busy", "synthwave"): "b6e705187493873c130c400b456bcf1f34ef12da4ae5d4f40b8fafb4561823fa",
    ("busy", "jazz"): "983a2e9fb53a1a722e8a0f1c1a0398cb6fab079edfd36307b826bce14b119661",
    ("busy", "rock"): "c948fadaa99322a3740e5e2b038cf1e77975eab08302729b804840bc477bd75d",
    ("busy", "electro"): "13223a0c6b4baf9f0186447cc5c2a3f53d6f81826639832cc72a91b4ef2c0ce2",
    ("busy", "electrohouse"): "126927d4a5c73f5bbfc8eee1445a206b0144db40ac50623acc6b186b745f25a6",
    ("busy", "cumbia"): "e32eb992b057b6bb0c3d79f09956577afc2d6c6751de29e5b2c6d8778d3c82c3",
    ("busy", "dubstep"): "7585c20ec0b995cb7c4c15d6100ef1bb5823e0a16831c14432d14cf1df3464d1",
    ("busy", "pop"): "a8e145f2e5141aee47338e423895ad40e7ada1e5b8c7e6e73070595bf1750e9e",
    ("busy", "ballad"): "74666d054ef75b63ce96567a358991fda7b8afb2a3e2b3f65aeed4135e0e1cb4",
    ("busy", "heavy"): "7ba9709e4352d02e2b3e92aa844422d81f1e06dc29c63fe6fa100709edc39d99",
}


@pytest.fixture(autouse=True)
def procedural_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))


def render(engine, bars):
    return [engine.render_bar() for _ in range(bars)]


# ------------------------------------------------------------ a constant style is bit-identical to the base commit
def test_golden_hashes_cover_every_genre():
    assert {g for _, g in GOLDEN} == set(genres.NAMES)


@pytest.mark.parametrize("label, genre", sorted(GOLDEN))
def test_a_constant_style_renders_exactly_as_before_live_glides(label, genre):
    e = Engine(Style(genre=genre, **GOLDEN_STYLES[label]), seed=GOLDEN_SEED, samples=False)
    h = hashlib.sha256()
    for _ in range(GOLDEN_BARS):
        h.update(e.render_bar().tobytes())
    assert h.hexdigest() == GOLDEN[label, genre]


# ------------------------------------------------------------ engine glides
def test_glide_fields_are_the_continuous_style_fields():
    assert set(GLIDE_FIELDS) == {"bpm", "energy", "brightness", "space", "swing", "vinyl", "lead_density",
                                 "voice"}


def test_a_glide_moves_every_named_field_in_place_without_a_new_piece():
    e = Engine(Style(energy=0.2, brightness=0.2, space=0.2, swing=0.0, vinyl=0.0, lead_density=0.1), seed=1)
    e.render_bar()
    piece, bar = e.piece, e.bar
    e.queue_glide({"energy": 1.0, "brightness": 0.9, "space": 0.8, "swing": 0.2, "vinyl": 0.6,
                   "lead_density": 0.9}, 0)
    e.render_bar()
    s = e.style
    assert (s.energy, s.brightness, s.space, s.swing, s.vinyl, s.lead_density) == (1.0, 0.9, 0.8, 0.2, 0.6, 0.9)
    assert e.piece == piece and e.bar == bar + 1
    assert e.composer.style == s and e._piece.style == s


def test_each_field_glides_with_its_own_target_and_duration():
    e = Engine(Style(energy=0.2, brightness=0.2), seed=2)
    e.queue_glide({"energy": 1.0}, 4.0)
    e.queue_glide({"brightness": 1.0}, 40.0)    # a second request adds a glide, it does not cancel the first
    seen = []
    for _ in range(6):
        e.render_bar()
        seen.append((e.style.energy, e.style.brightness))
    energies, lights = zip(*seen, strict=True)
    assert energies[-1] == 1.0 and 0.2 < lights[-1] < 1.0                     # energy done, brightness still going
    assert list(energies) == sorted(energies) and list(lights) == sorted(lights)
    assert e.targets == {"brightness": 1.0}


def test_glide_values_are_clamped_like_style_from_dict():
    e = Engine(seed=3)
    e.queue_glide({"energy": 7, "swing": 0.9, "bpm": 500, "vinyl": -1}, 0)
    e.render_bar()
    assert (e.style.energy, e.style.swing, e.style.bpm, e.style.vinyl) == (1.0, 0.3, 140.0, 0.0)


@pytest.mark.parametrize("fields", [{"genre": 1.0}, {"colour": 0.5}, {"energy": 0.9, "key": 2}, {}])
def test_unknown_or_discrete_fields_are_rejected_and_nothing_is_applied(fields):
    e = Engine(Style(energy=0.2), seed=4)
    with pytest.raises(ValueError):
        e.queue_glide(fields, 0)
    e.render_bar()
    assert e.style.energy == 0.2 and e.targets == {}


def test_queue_tempo_is_a_bpm_glide():
    e = Engine(Style(bpm=72), seed=5)
    e.queue_tempo(120, 0)
    assert e.targets == {"bpm": 120.0} and e.target_bpm == 120.0
    e.render_bar()
    assert e.style.bpm == 120.0 and e.target_bpm is None


def test_a_new_style_or_next_cancels_every_glide():
    e = Engine(Style(energy=0.2), seed=6)
    e.queue_glide({"energy": 1.0, "bpm": 100}, 30)
    e.queue_style(Style(energy=0.3))
    assert e.targets == {}
    e.queue_glide({"energy": 1.0}, 30)
    e.queue_next()
    assert e.targets == {}


def test_a_glide_queued_after_a_new_style_applies_to_the_new_piece():
    e = Engine(Style(energy=0.2), seed=10)
    e.render_bar()
    e.queue_style(Style(name="New", energy=0.3))
    e.queue_glide({"energy": 0.9}, 0)    # after the style: it is not cancelled, it starts on the new piece
    e.render_bar()
    assert e.style.name == "New" and e.piece == 2 and e.style.energy == 0.9 and e.targets == {}


def test_an_energy_and_colour_glide_stays_click_free_and_under_full_scale():
    e = Engine(Style(drums="soft", energy=0.1, brightness=0.1, space=0.1), seed=7)
    e.queue_glide({"energy": 1.0, "brightness": 1.0, "space": 1.0, "vinyl": 1.0}, 12)
    bars = render(e, 8)
    x = np.concatenate(bars)
    assert np.max(np.abs(x)) < 1.0
    inner = np.concatenate([np.abs(np.diff(b, axis=0)) for b in bars])
    limit = np.max(inner)
    for a, b in zip(bars, bars[1:], strict=False):
        assert np.all(np.abs(b[0] - a[-1]) <= limit)


def test_the_same_glide_at_the_same_bar_is_deterministic():
    def run():
        e = Engine(Style(energy=0.3), seed=8)
        render(e, 2)
        e.queue_glide({"energy": 1.0, "lead_density": 1.0, "brightness": 0.9}, 6)
        return np.concatenate(render(e, 5))

    assert np.array_equal(run(), run())


def test_gliding_energy_makes_the_playing_cycle_louder():
    """Energy now reaches the composer at plan time: the same cycle gets more energetic, not only the next one."""
    calm = Engine(Style(energy=0.2), seed=9)
    hot = Engine(Style(energy=0.2), seed=9)
    render(calm, 6)
    render(hot, 6)
    hot.queue_glide({"energy": 1.0}, 0)
    plan_calm, plan_hot = calm.composer.plan(7), hot.composer.plan(7)   # bar 7 of the same, already planned cycle
    render(hot, 1)
    assert hot.composer.plan(7).energy > plan_calm.energy
    assert plan_hot.energy == plan_calm.energy   # nothing changes before the glide is applied at a bar boundary
    assert sum(len(b) for b in render(hot, 1)) == int(round(240 / 72 * SR))   # tempo untouched
