"""Meter: a style names 4/4 (the default), 6/8 or 12/8; the bar, the composer and the choir count its beats, and
4/4 keeps rendering exactly as before."""
import numpy as np
import pytest

from gentle_stream import genres
from gentle_stream.composer import Composer
from gentle_stream.engine import SR, Engine
from gentle_stream.style import METERS, Style

TON = 50


def test_the_meter_round_trips_and_a_style_without_one_is_four_four():
    assert Style().meter == "4/4" and Style().beats == 4
    for meter, beats in METERS.items():
        s = Style.from_dict({"meter": meter})
        assert (s.meter, s.beats) == (meter, beats) and s.to_dict()["meter"] == meter
    assert Style.from_dict({"meter": "3/4"}).meter == "4/4"          # unknown falls back
    assert Style(meter="6/8").variation(np.random.default_rng(2)).meter == "6/8"


@pytest.mark.parametrize("meter, beats", [("4/4", 4), ("6/8", 6), ("12/8", 12)])
def test_the_bar_lasts_as_many_beats_as_the_meter_has(meter, beats):
    e = Engine(Style(meter=meter, bpm=120), seed=1, samples=False)
    assert e.bar_seconds == pytest.approx(beats * 60 / 120)
    assert len(e.render_bar()) == round(e.sr * e.bar_seconds)


@pytest.mark.parametrize("meter", ["6/8", "12/8"])
def test_every_voice_stays_inside_the_bar(meter):
    beats = METERS[meter]
    c = Composer(Style(meter=meter, lead_density=1.0, energy=1.0), 4, TON)
    for bar in range(60):
        p = c.plan(bar)
        for voice in (p.melody, p.bass, p.counter):
            for n in voice:
                assert 0 <= n.beat < beats and n.length > 0 and n.beat + n.length <= beats + 0.51 * (beats / 4), \
                    (meter, bar, n)


@pytest.mark.parametrize("meter", ["6/8", "12/8"])
def test_phrases_still_end_held_every_four_bars(meter):
    beats = METERS[meter]
    c = Composer(Style(meter=meter, lead_density=1.0), 4, TON)
    main = ("A", "B", "A'", "B'", "release")
    ends = [p for p in (c.plan(b) for b in range(60)) if p.section in main and p.section_bar % 4 == 3]
    assert ends and all(len(p.melody) == 1 and p.melody[0].length == beats for p in ends)


@pytest.mark.parametrize("name", genres.NAMES)
def test_every_genre_renders_in_six_eight(name, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    e = Engine(Style(genre=name, meter="6/8", bpm=120), seed=3, samples=False)
    audio = np.concatenate([e.render_bar() for _ in range(8)])
    assert np.all(np.isfinite(audio)) and np.abs(audio).max() <= 0.9 + 1e-6
    assert np.abs(audio).max() > 0.01          # it plays, not silence


# ------------------------------------------------------------ a journey can be a waltz
def test_a_journey_names_its_meter_and_round_trips():
    from gentle_stream.journey import Journey

    j = Journey.from_dict({"version": 1, "name": "waltz", "meter": "6/8",
                           "stages": [{"name": "One", "seconds": 30, "to": {"bpm": 120}}]})
    assert j.meter == "6/8" and j.to_dict()["meter"] == "6/8"
    plain = Journey.from_dict({"version": 1, "name": "plain", "stages": [{"name": "One", "seconds": 30, "to": {}}]})
    assert plain.meter is None and "meter" not in plain.to_dict()
    with pytest.raises(ValueError, match='"meter" must be one of 4/4, 6/8, 12/8'):
        Journey.from_dict({"version": 1, "name": "x", "meter": "3/4", "stages": [{"name": "A", "seconds": 30, "to": {}}]})


def test_a_journey_in_six_eight_starts_a_piece_in_six_eight_and_keeps_running():
    from gentle_stream.journey import Journey

    e = Engine(Style(bpm=120), seed=1, samples=False)
    assert e.bar_seconds == pytest.approx(2.0)
    e.queue_journey(Journey.from_dict({"version": 1, "name": "waltz", "meter": "6/8", "stages": [
        {"name": "One", "seconds": 30, "to": {"bpm": 120}}]}))
    e.render_bar()
    e.render_bar()
    assert e.bar_seconds == pytest.approx(3.0) and e.journey is not None
    assert e.composer.beats == 6


def test_a_journey_without_a_meter_leaves_the_bar_alone():
    from gentle_stream.journey import Journey

    e = Engine(Style(meter="6/8", bpm=120), seed=1, samples=False)
    e.queue_journey(Journey.from_dict({"version": 1, "name": "plain",
                                       "stages": [{"name": "One", "seconds": 30, "to": {"energy": 0.9}}]}))
    e.render_bar()
    e.render_bar()
    assert e.bar_seconds == pytest.approx(3.0) and e.journey is not None


def test_the_tempo_bound_follows_the_meter():
    from gentle_stream.engine import bpm_range

    assert bpm_range("4/4") == (50.0, 140.0)
    assert bpm_range("6/8") == (75.0, 210.0) and bpm_range("12/8") == (150.0, 420.0)


def test_a_six_eight_journey_keeps_its_waltz_tempo_and_four_four_still_stops_at_140():
    from gentle_stream.journey import Journey

    def stage(meter):
        data = {"version": 1, "name": "w", "stages": [{"name": "A", "seconds": 40, "to": {"bpm": 184}}]}
        j = Journey.from_dict({**data, "meter": meter} if meter else data)
        return j.stages[0].to["bpm"]

    assert stage("6/8") == 184.0 and stage("12/8") == 184.0 and stage(None) == 140.0


def test_a_glide_in_six_eight_reaches_a_waltz_tempo():
    for meter, want in (("6/8", 184.0), ("4/4", 140.0)):
        e = Engine(Style(meter=meter, bpm=120), seed=1, samples=False)
        e.queue_glide({"bpm": 184}, 0)
        e.render_bar()
        e.render_bar()
        assert e.style.bpm == pytest.approx(want), meter


def test_resuming_into_a_saved_style_does_not_start_a_new_piece_for_the_meter():
    """A resumed journey brings the meter its saved style already has; queuing another piece would drop the resumption."""
    from gentle_stream.journey import Journey

    e = Engine(Style(bpm=120), seed=1, samples=False)
    walk = Journey.from_dict({"version": 1, "name": "waltz", "meter": "6/8", "stages": [
        {"name": "One", "seconds": 600, "to": {"bpm": 120}}]})
    e.queue_journey(walk, at=120.0, start={"bpm": 120.0})
    e.render_bar()
    e.render_bar()
    assert e.bar_seconds == pytest.approx(2.0)          # the bar did not change: no fresh piece
    assert e._pending_style is None
    assert e.journey is not None and e.journey.meter == "6/8"   # the journey runs, the piece was not restarted


def lofi_events(meter, section="A", bar=5, seed=4):
    """[(kind, beat)] of one lo-fi bar, scheduled through a spy instrument set."""
    from gentle_stream.genres.base import Piece
    from gentle_stream.genres.lofi import GENRE

    style = Style(genre="lofi", meter=meter, bpm=120, energy=0.7, swing=0.0)   # the grid itself, not the swing
    spy_pending, events = [], []
    piece = Piece(style, np.random.default_rng(seed), None, 50, SR, np.zeros((SR * 8, 2)))

    class Spy:
        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            return lambda *a, **k: spy_pending.append(name) or np.zeros(8)

    piece.inst = Spy()
    GENRE.start(piece)
    beat = 60 / style.bpm

    def add(sig, t, pan=0.0, g=1.0):
        events.append((spy_pending.pop(0), round(t / beat, 2)))

    piece.add = add
    comp = Composer(style, seed, 50, GENRE.chord, profile=GENRE.profile)
    plan = next(comp.plan(b) for b in range(60) if comp.plan(b).section == section and comp.plan(b).section_bar == bar)
    GENRE.schedule(piece, plan)
    return events


def test_lofi_hats_follow_the_groups_of_three_in_six_eight():
    events = lofi_events("6/8")
    hats = [b for kind, b in events if kind == "hat"]
    assert hats == [0, 1, 2, 3, 4, 5]                     # one per eighth, the bar's six beats
    assert sorted(b for kind, b in events if kind == "kick") == [0, 3]


def test_lofi_keeps_its_four_four_pattern():
    events = lofi_events("4/4")
    from gentle_stream.genres.lofi import KICK_PATTERNS

    hats = [b for kind, b in events if kind == "hat"]
    assert hats == [0, 0.5, 1, 1.5, 2, 2.5, 3, 3.5]        # eighths as before
    kicks = tuple(sorted(b for kind, b in events if kind == "kick"))
    assert kicks in KICK_PATTERNS                           # its own four-beat patterns, drawn per piece


def test_electrohouse_lfo_follows_the_bar_s_own_beats():
    from gentle_stream.genres.electrohouse import GENRE

    plan = Composer(Style(genre="electrohouse"), 3, 50, profile=GENRE.profile).plan(3)   # never the first bar
    cut = GENRE.bass_cut
    assert cut(plan, 0, None) == cut(plan, 0, None, 4)        # 4/4 keeps exactly its own numbers
    assert cut(plan, 0, None, 6) != cut(plan, 0, None, 4)     # the phase counts the bar's pulses


def test_electrohouse_build_progress_follows_the_bar_s_own_beats():
    from gentle_stream.genres.electrohouse import GENRE

    plan = Composer(Style(genre="electrohouse"), 3, 50, profile=GENRE.profile).plan(0)
    cut = GENRE.bass_cut
    # mid-build, the cutoff differs when progress uses four versus six pulses per bar
    assert cut(plan, 3, 1, 6) != cut(plan, 3, 1, 4)


def test_electrohouse_schedule_hands_the_cut_the_bar_s_beats(monkeypatch):
    from gentle_stream.genres import electrohouse as E
    from gentle_stream.genres.base import Piece

    seen = []
    real = E.GENRE.bass_cut

    def spy(p, beat, build, beats=4):
        seen.append(beats)
        return real(p, beat, build, beats)

    monkeypatch.setattr(E.GENRE, "bass_cut", spy)
    style = Style(genre="electrohouse", meter="6/8", bpm=180)
    piece = Piece(style, np.random.default_rng(5), None, 50, SR, np.zeros((SR * 8, 2)))

    class Spy:
        def __getattr__(self, name):
            if name.startswith("_"):
                raise AttributeError(name)
            return lambda *a, **k: np.zeros(8)

    piece.inst = Spy()
    E.GENRE.start(piece)
    piece.add = lambda *a, **k: None
    plan = Composer(style, 5, 50, E.GENRE.chord, profile=E.GENRE.profile).plan(20)
    E.GENRE.schedule(piece, plan)
    assert seen and set(seen) == {6}
