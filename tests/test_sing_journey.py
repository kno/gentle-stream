"""A journey's stage can sing its phrases (S2): `"sing": true`. The engine decides a sung phrase one phrase boundary
ahead and hands it to the player, which sings it on that boundary's notes; spoken stages are unchanged."""
import itertools
import logging
import sys

import numpy as np
import pytest

from gentle_stream import bridge, sing, speech
from gentle_stream.engine import Engine
from gentle_stream.journey import Journey, stage_diff
from gentle_stream.style import Style
from tests.test_sing_say import FAKE_VOICE

BPM = 120.0                      # one bar is 2 s, a phrase boundary every 8 s
ABSENT = object()


def journey(sing_=True, phrases=("Keep going", "Almost there"), every=20, **extra):
    push = {"name": "Push", "seconds": 64, "to": {"energy": 0.8}, "phrases": list(phrases), "phrase_every": every,
            **extra}
    if sing_ is not ABSENT:
        push["sing"] = sing_
    return Journey.from_dict({"version": 1, "name": "song", "title": "Song", "end": "sustain", "stages": [
        {"name": "Warm", "seconds": 30, "to": {"energy": 0.4}}, push,
        {"name": "Rest", "seconds": 40, "to": {"energy": 0.3}}]})


# ------------------------------------------------------------ the format
def test_a_stage_can_sing_and_round_trips():
    j = journey()
    assert j.stages[1].sing is True and j.stages[0].sing is False
    assert j.to_dict()["stages"][1]["sing"] is True
    assert "sing" not in j.to_dict()["stages"][0]
    assert Journey.from_dict(j.to_dict()) == j
    assert "sing" not in journey(sing_=False).to_dict()["stages"][1]                # false is the default


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_sing_must_be_true_or_false(value):
    with pytest.raises(ValueError, match='^stage 2: "sing" must be true or false$'):
        journey(sing_=value)


def test_sing_needs_phrases():
    with pytest.raises(ValueError, match='^stage 1: "sing" needs "phrases"$'):
        Journey.from_dict({"version": 1, "name": "x", "stages": [{"name": "A", "seconds": 30,
                                                                    "to": {"energy": 0.4}, "sing": True}]})


def test_switching_sing_shows_in_the_edit_diff():
    before, after = journey(sing_=False), journey()
    assert any("Push" in line and "phrases changed" in line for line in stage_diff(before, after))


def test_the_prompt_schema_tells_the_model_about_sing():
    assert '"sing": true' in bridge.journey_rules()


# ------------------------------------------------------------ the engine
def run(j, seconds=134, sing_requests=True, provide=True):
    """(requests, spoken, engine): the sung phrases asked for as (bar, text), and the spoken ones queued."""
    e = Engine(Style(bpm=BPM), seed=5, samples=False)
    requests, spoken = [], []
    if sing_requests:
        e.sing_requests = lambda text, bar: requests.append((bar, text))
    if provide:
        for text in j.phrases:
            e.provide_phrase(text, np.full(1000, 0.01))
    real = e.queue_speech
    e.queue_speech = lambda clip, every=1, **kw: spoken.append(e.bar) or real(clip, every, **kw)  # type: ignore
    e.queue_journey(j)
    while e.samples_out < seconds * e.sr:
        e.render_bar()
    return requests, spoken, e


def test_a_singing_stage_asks_for_each_phrase_one_boundary_ahead():
    requests, spoken, _ = run(journey(every=20))
    bars = [bar for bar, _ in requests]
    assert spoken == []                                                   # nothing spoken in a sung stage
    assert bars and all(bar % 4 == 0 for bar in bars)
    times = [bar * 2.0 for bar in bars]
    assert times[0] == 32 and all(30 <= t < 94 for t in times)           # inside the stage, its first boundary
    assert all(b - a >= 20 for a, b in itertools.pairwise(times))         # once per interval
    assert {text for _, text in requests} <= {"Keep going", "Almost there"}


def test_a_spoken_stage_is_unchanged():
    requests, spoken, _ = run(journey(sing_=False))
    assert requests == [] and spoken


def test_without_a_singer_a_singing_stage_speaks():
    requests, spoken, _ = run(journey(), sing_requests=False)
    assert requests == [] and spoken


# ------------------------------------------------------------ the player
@pytest.fixture
def voice(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", str(bin_dir))
    path = bin_dir / "say"
    path.write_text(FAKE_VOICE.format(python=sys.executable))
    path.chmod(0o755)
    speech.clear_cache()
    yield
    speech.clear_cache()


def player_with(j):
    from tests.test_daemon import fake_player

    player = fake_player()
    player.journey_start(j.to_dict())
    return player


def test_the_player_sings_a_requested_phrase_on_its_bar(voice):
    player = player_with(journey())
    bar = player.engine.bar + 8
    requests = player.engine.sing_requests
    assert requests is not None
    requests("Keep going", bar)
    player.singer_idle(10)
    [clip] = [c for c in player.engine._speech_queue if c.at_bar is not None]
    assert clip.at_bar == bar and clip.duck_db == sing.SING_DUCK_DB
    assert np.abs(clip.clip).max() > 0.05


def test_a_phrase_that_cannot_be_sung_is_logged_and_the_journey_plays_on(voice, caplog):
    player = player_with(journey())
    requests = player.engine.sing_requests
    assert requests is not None
    with caplog.at_level(logging.WARNING, logger="gentle_stream.player"):
        requests("   ", player.engine.bar + 8)
        player.singer_idle(10)
    assert "a journey phrase will not be sung: a phrase must have between 1 and 200 characters" in caplog.text
    assert [c for c in player.engine._speech_queue if c.at_bar is not None] == []


def test_without_pyworld_a_singing_journey_speaks_and_says_why(voice, monkeypatch, caplog):
    monkeypatch.setattr(sing, "available", lambda: False)
    with caplog.at_level(logging.WARNING, logger="gentle_stream.player"):
        player = player_with(journey())
    assert player.engine.sing_requests is None
    assert f"the journey's phrases are spoken, not sung: {sing.INSTALL_HINT}" in caplog.text
