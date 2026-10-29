"""S11: stop and start again where it was: the style, the journey at the same moment, the volume, the binaural layer,
mute and live come back (the piece's exact bar cannot: the music is generated). `--fresh` starts from scratch."""
import json
import sys
import time
from pathlib import Path

import pytest

from gentle_stream import broadcast, main, session, streamconf
from gentle_stream.binaural import Binaural
from gentle_stream.engine import Engine
from gentle_stream.journey import BUILTIN
from gentle_stream.player import Player
from gentle_stream.style import Style
from tests.rtmp_fake import FakeIngest
from tests.test_daemon import runtime  # noqa: F401  (fixture: a private runtime dir and a fake audio device)
from tests.test_player import FakeStream

FAKE = str(Path(__file__).with_name("fake_encoder.py"))
WARM_UP = BUILTIN["warm-up"]


def make_player(style: Style | None = None, saved: dict | None = None) -> Player:
    """A player on a fake stream; with `saved`, resumed before it starts, as the background player does."""
    player = Player(Engine(style or Style(name="Rainy Desk", genre="jazz", bpm=84), seed=1, samples=False),
                    stream_factory=FakeStream, prebuffer=0.3)
    if saved is not None:
        assert player.resume(saved) == []
    player.start()
    return player


def play(player: Player, seconds: float) -> None:
    """Play `seconds` of audio: pull only what the producer has rendered (a tight loop would outrun it and read
    silence, so the journey would never become audible)."""
    stream = player._stream
    assert isinstance(stream, FakeStream)
    played, deadline = 0, time.monotonic() + 60
    while played < seconds * player.engine.sr and time.monotonic() < deadline:
        if player._buffered >= 1024:
            stream.pull(1024)
            played += 1024
        else:
            time.sleep(0.002)


# ------------------------------------------------------------ the engine
def test_a_journey_can_start_part_way():
    engine = Engine(Style(), seed=1, samples=False)
    engine.queue_journey(WARM_UP, at=200.0)
    engine.render_bar()
    assert engine.journey_seconds is not None and 200.0 < engine.journey_seconds < 205.0
    stage = engine.journey_snapshot
    assert stage is not None
    expected = next(i for i, s in enumerate(WARM_UP.stages, 1)
                    if sum(x.seconds for x in WARM_UP.stages[:i]) > 200.0)
    assert stage.stage == expected


# ------------------------------------------------------------ what is saved
def test_the_session_holds_what_resuming_needs():
    player = make_player()
    try:
        player.set_volume(0.55)
        player.set_muted(True)
        player.engine.queue_binaural(Binaural(180, 7, 0.04))
        play(player, 1.0)
        saved = player.session()
    finally:
        player.close()
    assert json.loads(json.dumps(saved)) == saved                    # plain JSON
    assert saved["version"] == 1 and saved["style"]["name"] == "Rainy Desk" and saved["style"]["genre"] == "jazz"
    assert saved["volume"] == 0.55 and saved["muted"] is True and saved["live"] is False
    assert saved["binaural"] == {"carrier": 180.0, "beat": 7.0, "level": 0.04} and saved["journey"] is None


def test_saving_is_atomic_and_a_bad_file_is_ignored():
    session.save({"version": 1, "style": Style().to_dict(), "volume": 0.8, "muted": False, "live": False,
                  "binaural": None, "journey": None})
    assert session.load() is not None and [p.name for p in session.path().parent.iterdir()] == ["session.json"]
    session.path().write_text("{not json")
    assert session.load() is None
    session.path().write_text(json.dumps({"version": 99}))
    assert session.load() is None
    session.clear()
    assert session.load() is None and not session.path().exists()


def test_autosave_writes_while_it_plays():
    player = make_player()
    try:
        saver = session.autosave(player, every=0.05)
        time.sleep(0.3)
        saver.stop()
        loaded = session.load()
        assert loaded is not None and loaded["style"]["name"] == "Rainy Desk"
    finally:
        player.close()


# ------------------------------------------------------------ resuming
def test_resume_brings_back_the_style_volume_mute_and_binaural():
    first = make_player()
    try:
        first.set_volume(0.55)
        first.set_muted(True)
        first.engine.queue_binaural(Binaural(180, 7, 0.04))
        play(first, 1.0)
        saved = first.session()
    finally:
        first.close()
    second = make_player(Style.from_dict(saved["style"]), saved)
    try:
        play(second, 1.0)
        assert second.now.style.name == "Rainy Desk" and second.now.style.genre == "jazz"
        assert second.volume == 0.55 and second.muted
        assert second.binaural == Binaural(180, 7, 0.04)
    finally:
        second.close()


def test_resume_brings_back_the_journey_at_the_same_moment():
    first = make_player()
    try:
        first.journey_start(WARM_UP.to_dict())
        play(first, 20.0)
        rendered, buffered = first.engine.journey_seconds, first._buffered
        saved = first.session()
        was = first.now.journey
    finally:
        first.close()
    assert was is not None and saved["journey"]["journey"]["name"] == WARM_UP.name
    assert 15.0 < saved["journey"]["seconds"] < 25.0
    assert rendered is not None and buffered > 0
    assert abs(saved["journey"]["seconds"] - (rendered - buffered / 44100)) < 0.05   # what is heard, not rendered
    second = make_player(Style.from_dict(saved["style"]), saved)
    try:
        play(second, 1.0)
        now = second.now.journey
        assert now is not None and now.title == was.title and now.stage == was.stage
        assert second.engine.journey_seconds is not None
        assert abs(second.engine.journey_seconds - saved["journey"]["seconds"]) < 6.0   # within a bar or two
    finally:
        second.close()


def test_resume_starts_the_broadcast_again(monkeypatch, tmp_path):
    monkeypatch.delenv(streamconf.KEY_ENV, raising=False)
    ingest = FakeIngest()
    streamconf.save_url(ingest.url)
    streamconf.save_key("SENTINEL-KEY-resume-55")
    monkeypatch.setattr(broadcast, "encoder_command",
                        lambda sr: [sys.executable, FAKE, "copy", str(tmp_path / "pcm"), "{video_fd}"])
    player = make_player()
    try:
        assert player.resume_live({"live": True}) is None
        assert (player.streaming or {}).get("running")
    finally:
        player.close()


def test_a_broadcast_that_cannot_start_again_is_reported_not_raised(monkeypatch):
    monkeypatch.delenv(streamconf.KEY_ENV, raising=False)
    player = make_player()
    try:
        error = player.resume_live({"live": True})
        assert error is not None and error.startswith("no ingest URL")
        assert player.streaming is None
        assert player.resume_live({"live": False}) is None
    finally:
        player.close()


# ------------------------------------------------------------ the background player, end to end
def status(capsys) -> dict:
    assert main(["ctl", "status"]) == 0
    return json.loads(capsys.readouterr().out)


def wait_for(predicate, timeout: float = 20.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.1)
    return False


def test_stop_and_start_comes_back_muted_on_the_same_journey(runtime, capsys):  # noqa: F811
    from gentle_stream import client

    client.ensure().detach()
    assert main(["ctl", "mute"]) == 0
    assert main(["journey", "play", "warm-up"]) == 0
    capsys.readouterr()
    assert wait_for(lambda: (status(capsys)["journey"] or {}).get("progress", 0) > 0.05)
    before = status(capsys)
    assert main(["ctl", "stop"]) == 0
    assert wait_for(lambda: not (runtime / "player.sock").exists(), 10)
    client.ensure().detach()
    assert wait_for(lambda: status(capsys)["journey"] is not None)
    after = status(capsys)
    assert after["muted"] is True and after["name"] == before["name"]
    assert after["journey"]["name"] == "warm-up" and after["journey"]["stage"] == before["journey"]["stage"]
    assert after["journey"]["progress"] >= before["journey"]["progress"] - 0.05   # not back to the start


def test_fresh_forgets_the_saved_session(runtime, capsys, monkeypatch):  # noqa: F811
    from gentle_stream import client
    from gentle_stream.app import StreamApp

    session.save({"version": 1, "style": Style(name="Old Session").to_dict(), "volume": 0.3, "muted": True,
                  "live": False, "binaural": None, "journey": None})
    seen = []
    monkeypatch.setattr(StreamApp, "run", lambda self: seen.append(True))
    assert main(["--fresh"]) == 0 and seen == [True]
    loaded = session.load()
    assert loaded is None or loaded["style"]["name"] != "Old Session"
    now = status(capsys)
    assert now["muted"] is False and now["name"] != "Old Session"
    client.connect().close()


def test_help_lists_fresh(capsys):
    with pytest.raises(SystemExit):
        main(["--help"])
    assert "--fresh" in capsys.readouterr().out
