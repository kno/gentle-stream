"""Live glide of the continuous style fields (PM-002): the playing piece evolves in place, and a constant style keeps
rendering exactly what it rendered before live glides existed.

The golden hashes were captured once from the base commit f4ffaea (before any live-evolution change) in a scratch
checkout: 120 bars per genre, seed 2026, procedural instruments, sha256 over the float32 bytes of every bar. They
are constants here on purpose; tests never read git history.
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
    ("default", "ambient"): "51d0bde57f73a78e1ed4b299694cbc38b778c70c60d532cd6cdc0e4c36658c7d",
    ("default", "chiptune"): "78c99d9aa9334eb764314e6891391f8de66a9a43260c5c1f91355310fd62ff44",
    ("default", "synthwave"): "b446a8674c60464c338085de8d85701f41f7a2b1546443a411edd7e664e8e082",
    ("default", "jazz"): "c603aa4d6c431c51ef0a5de5adb0df222dec75229a1aafe732deabeccd9a886e",
    ("default", "rock"): "cdb1f91c4982c1431de77ae487b8079143c0c8f492fb4d8bc7f95bcfdddd55e6",
    ("default", "electro"): "5c17b51ca1649aeccbe5e9867c36d52dd8c8e0efcbad014aa62deab6466a8b31",
    ("default", "electrohouse"): "486e5bd23ea6674b180d473ea0d10111613e276685236ed9ae46d6ad13673bf7",
    ("default", "cumbia"): "0735431a9336109f3ecaa0c17ebc5431b03a473f6ef399d46206763e8e92e5e5",
    ("default", "dubstep"): "553e7756005032287b4b779edf7ca0149774f1d62bbd2524e6c4d878dcb02203",
    ("busy", "lofi"): "3dcd51720d894c3402304fbc0865021dbba3b8d2318988bb2324cd8e77f56d82",
    ("busy", "ambient"): "8e608caaf659b6bcdaf4a995b6c5a8c6cf9f556a1aced1f0e995dc15d86b5683",
    ("busy", "chiptune"): "c787bc6bab63dcff80ae6c9703848658cfed4b8938a32f2a02dc798cd4f92b0d",
    ("busy", "synthwave"): "4eda4ff7bef7252e0544db8ab74276732448225f635a6523ed6166306a799c92",
    ("busy", "jazz"): "3a6e988ea51d0bb77f28a1f638cfd9793a8aa3c4f29cc04d6c61c041c5451e87",
    ("busy", "rock"): "b15a7204e1a04f79ddfe941c298799bf23f2b4b2eb20d88840419a8c270fb49a",
    ("busy", "electro"): "06545a6e8d4411b69e986f414a837f1d6ad6e8e25d93ba91bd67324ccabf8f3c",
    ("busy", "electrohouse"): "ea058a2aa73819e96d85a705441fe4cf8de2092497b12f1bb3693d2060f7c197",
    ("busy", "cumbia"): "192f2f1efb2930ec6f6123b926f41f6944d33681f51c97b2d6176de8d638583a",
    ("busy", "dubstep"): "8e3e46fefb9989acac29250ce4f20e08fd8ea3f9a06579bba80f48f0d24e0645",
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
