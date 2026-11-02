"""Heavy genre traits (S5): metal at any energy and drum level (chugs in sixteenths, double kick, china), riff-like
lines composed with its own profile; rock keeps its rock flavor unless busy and energetic."""
import numpy as np

from gentle_stream import genres
from gentle_stream.composer import Composer
from gentle_stream.engine import SR
from gentle_stream.genres.base import Piece
from gentle_stream.genres.heavy import GENRE as HEAVY
from gentle_stream.genres.rock import GENRE as ROCK
from gentle_stream.style import Style

BPM = 120.0
B = 60 / BPM


class Spy:
    """The rock voice set, recording every call by kind."""

    def __init__(self):
        self.pending = []

    def _sig(self, kind, **info):
        self.pending.append((kind, info))
        return np.zeros(8)

    def guitar(self, notes, dur, vel=1.0, tone="piano", mute=False, take=0):
        return self._sig("guitar", mute=mute, take=take)

    def lead(self, m, dur, vel=1.0, tone="piano", vibrato=0.0):
        return self._sig("lead", midi=m)

    def strings(self, m, dur, vel=1.0):
        return self._sig("strings")

    def bass(self, m, dur, vel=1.0):
        return self._sig("bass")

    def __getattr__(self, drum):
        if drum.startswith("_"):
            raise AttributeError(drum)
        return lambda *a, **k: self._sig(drum)


def events(style, sections, seed=5):
    """[(plan, [(kind, t, info)])] for the bars of `sections` in the first cycle of heavy's form."""
    spy = Spy()
    piece = Piece(style, np.random.default_rng(seed), spy, 45, SR, np.zeros((int(30 * SR), 2)))
    HEAVY.start(piece)
    comp = Composer(style, seed, 45, HEAVY.chord, profile=HEAVY.profile)
    out = []
    for bar in range(HEAVY.profile.first_len):
        plan = comp.plan(bar)
        log = []

        def add(sig, t, pan=0.0, g=1.0, log=log):
            kind, info = spy.pending.pop(0)
            log.append((kind, t, info))

        piece.add = add
        HEAVY.schedule(piece, plan)
        if plan.section in sections:
            out.append((plan, log))
    return out


def on_grid(t, step):
    return abs(t / step - round(t / step)) < 0.02


def calm(**kw):
    return Style(**({"genre": "heavy", "bpm": BPM, "mode": "minor", "drums": "lofi", "energy": 0.4} | kw))


def test_heavy_is_registered_and_its_own_genre():
    assert "heavy" in genres.NAMES and genres.get("heavy") is HEAVY
    assert HEAVY.profile is not ROCK.profile and "metal" in HEAVY.description


def test_heavy_is_metal_at_any_energy_and_drum_level_and_rock_stays_rock():
    for drums in ("soft", "lofi", "busy"):
        for energy in (0.1, 0.5, 0.9):
            assert HEAVY.flavor(calm(drums=drums, energy=energy)) == "metal"
    assert ROCK.flavor(Style(genre="rock", drums="lofi", energy=0.6)) == "rock"
    assert ROCK.flavor(Style(genre="rock", drums="busy", energy=0.9)) == "metal"


def test_even_a_calm_style_chugs_in_sixteenths_with_a_double_kick():
    for plan, ev in events(calm(), ("B",)):
        muted = [t for k, t, info in ev if k == "guitar" and info["take"] == 0 and info["mute"]]
        assert len(muted) >= 9 and all(on_grid(t, B / 4) for t in muted), plan.bar
        kicks = [t for k, t, _ in ev if k == "kick"]
        assert len(kicks) >= 14 and all(on_grid(t, B / 4) for t in kicks), plan.bar


def test_the_master_is_the_metal_one_for_a_calm_style():
    assert HEAVY.master(calm()).drive == ROCK.master(Style(genre="rock", drums="busy", energy=0.9)).drive


def test_riff_lines_stay_close_and_repeat_notes():
    comp = Composer(calm(), 5, 45, HEAVY.chord, profile=HEAVY.profile)
    lines = [comp.plan(b).melody for b in range(HEAVY.profile.first_len)]
    notes = [n.midi for line in lines for n in line]
    steps = [abs(b - a) for a, b in zip(notes, notes[1:], strict=False)]
    assert np.mean(steps) < 3.0                       # semitones: riffs hammer a few notes
    assert sum(s == 0 for s in steps) >= len(steps) // 5


def test_heavy_has_a_riff_intro_and_a_16_bar_last_chorus():
    comp = Composer(calm(), 5, 45, profile=HEAVY.profile)
    plans = [comp.plan(b) for b in range(HEAVY.profile.first_len)]
    starts = [(p.section, p.section_len) for p in plans if p.section_bar == 0]
    assert starts[0] == ("intro", 8) and ("B'", 16) in starts
