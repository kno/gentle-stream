"""Live glide of the continuous style fields (PM-002): the playing piece evolves in place, and a constant style keeps
rendering exactly what it rendered before live glides existed.

The golden hashes were captured once from the base commit f4ffaea (before any live-evolution change) in a scratch
checkout: 120 bars per genre, seed 2026, procedural instruments, sha256 over the float32 bytes of every bar. They
are constants here on purpose; tests never read git history. Every genre but lo-fi was captured again once its own
composition profile changed how it composes (feat/composition-profiles); lo-fi keeps the default profile and its
original hashes. Genres added later (pop, ballad, heavy) were captured when they were added.
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
    ("default", "ambient"): "0376b51777fdd1d633229a545e454d7341739301c6855cf429f960515b71c0ed",
    ("default", "chiptune"): "9bf2cbaf37ec6bb4a1ae09b153ae03d4c19cb7b369145fa9bd7b97a3dbaafe75",
    ("default", "synthwave"): "9e542413226aaff17b2a1a432d64e592d7967f98dd7302fbfca066d21f5a8ac6",
    ("default", "jazz"): "9980e36487c95ff5c9a4ced4e278332121bec8abd4119789a9eb9e280bc7094e",
    ("default", "rock"): "6a0430ff44a63bbcd797cf96b35712067ea126d45ef36f3201c575a338a13500",
    ("default", "electro"): "115dc12732dfadf1d6522382bb44656eeebf93d524905d31175e6053d8166755",
    ("default", "electrohouse"): "8146fc408654480e71d059d7587a79c8f63451d3df79a9761e34efc9c9cd3f3a",
    ("default", "cumbia"): "e3d4a5a2f9276d2206f3a4a36b9f2e85801b4b86182db3260cce0d2e77187bc5",
    ("default", "dubstep"): "4cfc5ac6524552c2774433bdcd639ff732763cb626be49a573da58b86e1f4e5c",
    ("default", "pop"): "4c5abade877ecdef99a596b4d80ce13c6e9b7eb9c7f96d659d3a50451fc199b2",
    ("default", "ballad"): "bd52ae12a84963c49049f0a7c4f05bdf98c95e1f624c3923113d5ccad6f2dac7",
    ("default", "heavy"): "6f92311f6bfa01a104edda40a9e7cd15afcba8976c7407f8520afe39e7d015cf",
    ("busy", "lofi"): "3dcd51720d894c3402304fbc0865021dbba3b8d2318988bb2324cd8e77f56d82",
    ("busy", "ambient"): "d216615910ee9e8e5ab6cf22c21a06b96b86f2d2f84ec035402051cb5d6ade0a",
    ("busy", "chiptune"): "9595522a1696ac308cd34f08948dc4969c0d2cefdaaf8f6b0281c596d84089e5",
    ("busy", "synthwave"): "3f7b2101c1e425536e442cb2876b6fc3cc8b4c6c8692b3efbb1b01c0ac13bdf0",
    ("busy", "jazz"): "b3635317422f0eda32b247ce2d59b7706e702c8e2d27c5374f2ba7742dea096a",
    ("busy", "rock"): "8544ebcc1fcd584dfb446267328a7d85da17edfb5602393456b93f19be8ff3b6",
    ("busy", "electro"): "9c6cf02e96d260f32fc225fe945d09e6de87a7543384b159f23ab4c524a786fa",
    ("busy", "electrohouse"): "43e1121c77001ab57c8c3bdef310e1b699844f743a94120c296c5d51381e990e",
    ("busy", "cumbia"): "a5c5d24053aa095a41351b3f6aff6ef383b701fee0d1b5716f48dd7df0a5c616",
    ("busy", "dubstep"): "71cf80f89d211948059724aea7b2cf1715499c41f8d596c2f316bc34bed3dd76",
    ("busy", "pop"): "20f86083fe0cff4a6287f33a926b2e43c0e20c8b421f05fa4ec2692781282b27",
    ("busy", "ballad"): "dad8c2b4e672a3901c3798cc79398df906dac31e412431b31c8ebd33394b2afb",
    ("busy", "heavy"): "e2865b589b6399f1281b72c1ec652aaef59be4e6ccd0ec3d8db789e6ca598678",
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
