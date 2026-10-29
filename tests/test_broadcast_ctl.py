"""PM-045 T5: the player broadcasts (`ctl stream start|stop`), reports it in its state, and while it does, speaks
phrases with espeak-ng and sings with the built-in choir instead of a pack that may not be redistributed."""
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from gentle_stream import broadcast, main, streamconf
from gentle_stream.broadcast import BroadcastError
from gentle_stream.engine import Engine
from gentle_stream.player import Player
from gentle_stream.style import Style
from tests.rtmp_fake import FakeIngest
from tests.test_daemon import runtime  # noqa: F401  (fixture: a private runtime dir and a fake audio device)
from tests.test_player import FakeStream

KEY = "SENTINEL-KEY-t5-0b0b-zz"
FAKE = str(Path(__file__).with_name("fake_encoder.py"))
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is needed for this check")


@pytest.fixture
def ingest(monkeypatch):
    monkeypatch.delenv(streamconf.KEY_ENV, raising=False)
    fake = FakeIngest()
    streamconf.save_url(fake.url)
    streamconf.save_key(KEY)
    return fake


def fake_encoder(monkeypatch, mode: str, out: Path) -> None:
    monkeypatch.setattr(broadcast, "encoder_command",
                        lambda sr: [sys.executable, FAKE, mode, str(out), "{video_fd}"])


def make_player(voices=None) -> Player:
    player = Player(Engine(Style(voice=0.4), seed=1, samples=False, voices=voices), stream_factory=FakeStream,
                    prebuffer=0.3)
    player.start()
    return player


def pull(player: Player, frames: int = 512) -> np.ndarray:
    stream = player._stream
    assert isinstance(stream, FakeStream)
    return stream.pull(frames)


def wait_for(predicate, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# ------------------------------------------------------------ the player
def test_the_broadcast_gets_the_audio_the_device_gets(ingest, monkeypatch, tmp_path):
    """S1 through the player: the blocks the callback gives the device are the blocks broadcast."""
    out = tmp_path / "pcm"
    fake_encoder(monkeypatch, "copy", out)
    player = make_player()
    try:
        status = player.stream_start()
        assert status["running"] and status["target"] == ingest.url
        played = []
        for _ in range(60):
            played.append(pull(player).copy())
            time.sleep(0.002)
        assert wait_for(lambda: player._broadcast is not None and player._broadcast._audio.empty())
        ended = player.stream_stop()
    finally:
        player.close()
    assert ended is not None and ended["dropped_frames"] == 0 and not ended["running"]
    assert out.read_bytes() == np.concatenate(played).tobytes()


def test_without_a_url_or_a_key_nothing_starts_and_the_reason_is_given(monkeypatch, tmp_path):
    monkeypatch.delenv(streamconf.KEY_ENV, raising=False)
    fake_encoder(monkeypatch, "copy", tmp_path / "pcm")
    player = make_player()
    try:
        with pytest.raises(BroadcastError, match=r"no ingest URL: run `gentle-stream stream url URL`"):
            player.stream_start()
        streamconf.save_url("rtmp://127.0.0.1:1/live2")
        with pytest.raises(BroadcastError, match=r"no stream key: run `gentle-stream stream key set`"):
            player.stream_start()
        assert player.streaming is None
    finally:
        player.close()


def test_a_failing_encoder_is_reported_and_the_music_keeps_playing(ingest, monkeypatch, tmp_path):
    """S3: the broadcast fails; the player's state says why and the device still gets audio."""
    monkeypatch.setenv("FAKE_KEY", KEY)
    fake_encoder(monkeypatch, "fail", tmp_path / "pcm")
    player = make_player()
    try:
        player.stream_start()
        assert wait_for(lambda: not (player.streaming or {}).get("running", True))
        status = player.streaming
        assert status is not None and "connection refused" in str(status["error"]) and KEY not in str(status)
        for _ in range(20):
            block = pull(player)
            assert np.isfinite(block).all()
        assert player.level > 0                                    # local playback untouched
    finally:
        player.close()


def test_starting_twice_is_refused_until_it_stops(ingest, monkeypatch, tmp_path):
    fake_encoder(monkeypatch, "copy", tmp_path / "pcm")
    player = make_player()
    try:
        player.stream_start()
        with pytest.raises(BroadcastError, match=f"already broadcasting to {ingest.url}"):
            player.stream_start()
        assert player.stream_stop() is not None
        assert player.stream_stop() is None                       # nothing to stop
    finally:
        player.close()


def test_closing_the_player_ends_the_broadcast(ingest, monkeypatch, tmp_path):
    fake_encoder(monkeypatch, "copy", tmp_path / "pcm")
    player = make_player()
    player.stream_start()
    process = player._broadcast._process if player._broadcast else None
    player.close()
    assert process is not None and process.poll() is not None
    ingest.wait()


# ------------------------------------------------------------ what may be broadcast
def test_a_pack_that_may_not_be_redistributed_gives_way_to_the_built_in_choir(ingest, monkeypatch, tmp_path):
    from gentle_stream.voicepacks import PackVoice, load_pack
    from tests.test_voicepacks import MANIFEST, make_pack

    pack = load_pack(make_pack(tmp_path / "pack", {**MANIFEST, "redistributable": False}))
    fake_encoder(monkeypatch, "copy", tmp_path / "pcm")
    player = make_player(PackVoice(pack))
    try:
        assert player.engine.vocals_backend == "pack: Test Choir"
        player.stream_start()
        assert player.engine.vocals_backend != "pack: Test Choir"
        player.stream_stop()
        assert player.engine.vocals_backend == "pack: Test Choir"
    finally:
        player.close()


def test_a_redistributable_pack_keeps_singing(ingest, monkeypatch, tmp_path):
    from gentle_stream.voicepacks import PackVoice, load_pack
    from tests.test_voicepacks import MANIFEST, make_pack

    pack = load_pack(make_pack(tmp_path / "pack", {**MANIFEST, "redistributable": True}))
    fake_encoder(monkeypatch, "copy", tmp_path / "pcm")
    player = make_player(PackVoice(pack))
    try:
        player.stream_start()
        assert player.engine.vocals_backend == "pack: Test Choir"
    finally:
        player.close()


@pytest.fixture
def tts(tmp_path, monkeypatch):
    from gentle_stream import speech
    from tests.test_speech_voices import FAKE as TTS

    bin_dir, log = tmp_path / "bin", tmp_path / "tts.log"
    bin_dir.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}:{Path(sys.executable).parent}")
    speech.clear_cache()

    def install(*names):
        for name in names:
            path = bin_dir / name
            path.write_text(TTS.format(python=sys.executable, log=str(log)))
            path.chmod(0o755)
        return log

    yield install
    speech.use_only(None)
    speech.clear_cache()


def programs(log: Path) -> list[str]:
    """Which program spoke each phrase: say writes with -o, espeak-ng with -w."""
    from tests.test_speech_voices import argv

    return ["say" if "-o" in args else "espeak-ng" for args in argv(log)] if log.exists() else []


def test_while_broadcasting_phrases_are_spoken_with_espeak_ng(ingest, monkeypatch, tmp_path, tts):
    log = tts("say", "espeak-ng")
    fake_encoder(monkeypatch, "copy", tmp_path / "pcm")
    player = make_player()
    try:
        player.say("Before")
        player.stream_start()
        player.say("During")
        player.stream_stop()
        player.say("After")
    finally:
        player.close()
    assert programs(log) == ["say", "espeak-ng", "say"]


def test_a_journeys_phrases_already_spoken_with_say_are_spoken_again_with_espeak_ng(ingest, monkeypatch, tmp_path,
                                                                                    tts):
    from gentle_stream.journey import Journey

    log = tts("say", "espeak-ng")
    fake_encoder(monkeypatch, "copy", tmp_path / "pcm")
    journey = Journey.from_dict({"version": 1, "name": "talk", "stages": [
        {"name": "One", "seconds": 600, "to": {"energy": 0.3}, "phrases": ["Breathe in"], "phrase_every": 30}]})
    player = make_player()
    try:
        player.journey_start(journey.to_dict())
        assert wait_for(lambda: "Breathe in" in player.engine._phrase_clips)
        player.stream_start()
        assert wait_for(lambda: programs(log) == ["say", "espeak-ng"])
        assert wait_for(lambda: "Breathe in" in player.engine._phrase_clips)
    finally:
        player.close()


def test_phrases_without_espeak_ng_refuse_the_broadcast_with_the_reason(ingest, monkeypatch, tmp_path, tts):
    from gentle_stream.journey import Journey

    tts("say")
    fake_encoder(monkeypatch, "copy", tmp_path / "pcm")
    journey = Journey.from_dict({"version": 1, "name": "talk", "stages": [
        {"name": "One", "seconds": 600, "to": {"energy": 0.3}, "phrases": ["Breathe in"], "phrase_every": 30}]})
    player = make_player()
    try:
        player.journey_start(journey.to_dict())
        with pytest.raises(BroadcastError) as raised:
            player.stream_start()
        assert str(raised.value) == ("the journey speaks phrases, and a broadcast speaks them with Piper or "
                                     "espeak-ng, and neither is installed (macOS voices are licensed for personal use "
                                     "only); run gentle-stream setup-speech, install espeak-ng, or stop the journey")
        assert player.streaming is None
    finally:
        player.close()


def test_without_phrases_a_missing_espeak_ng_does_not_stop_a_broadcast(ingest, monkeypatch, tmp_path, tts):
    tts("say")
    fake_encoder(monkeypatch, "copy", tmp_path / "pcm")
    player = make_player()
    try:
        assert player.stream_start()["running"]
        from gentle_stream.speech import SpeechError

        with pytest.raises(SpeechError, match="while broadcasting, phrases are spoken with Piper .* or espeak-ng"):
            player.say("Hello")
    finally:
        player.close()


# ------------------------------------------------------------ ctl
class FakeClient:
    def __init__(self, error: str | None = None, url: str = "rtmp://ingest/live2"):
        self.error, self.url, self.calls = error, url, []

    def stream_start(self):
        from gentle_stream.client import PlayerError

        self.calls.append("start")
        if self.error:
            raise PlayerError(self.error)
        return {"target": self.url, "seconds": 0.0, "dropped_frames": 0, "error": None, "running": True}

    def stream_stop(self):
        self.calls.append("stop")
        return None if self.error == "idle" else {"target": self.url, "seconds": 75.4, "dropped_frames": 3,
                                                  "error": None, "running": False}

    def detach(self):
        pass


def test_ctl_stream_start_and_stop_report_the_target_and_the_length(monkeypatch, capsys):
    from gentle_stream import client

    fake = FakeClient()
    monkeypatch.setattr(client, "connect", lambda: fake)
    assert main(["ctl", "stream", "start"]) == 0
    assert capsys.readouterr() == ("Broadcasting to rtmp://ingest/live2\n", "")
    assert main(["ctl", "stream", "stop"]) == 0
    assert capsys.readouterr() == ("Broadcast to rtmp://ingest/live2 ended after 1:15 (3 frames dropped)\n", "")


def test_ctl_stream_reports_the_players_refusal_and_an_idle_stop(monkeypatch, capsys):
    from gentle_stream import client

    monkeypatch.setattr(client, "connect", lambda: FakeClient("no stream key: run `gentle-stream stream key set`"))
    assert main(["ctl", "stream", "start"]) == 1
    assert capsys.readouterr() == ("", "gentle-stream: no stream key: run `gentle-stream stream key set`\n")
    monkeypatch.setattr(client, "connect", lambda: FakeClient("idle"))
    assert main(["ctl", "stream", "stop"]) == 1
    assert capsys.readouterr() == ("", "gentle-stream: not broadcasting\n")


@pytest.mark.parametrize("args", [["ctl", "stream"], ["ctl", "stream", "go"], ["ctl", "stream", "start", "x"]])
def test_ctl_stream_usage_errors(capsys, args):
    with pytest.raises(SystemExit) as e:
        main(args)
    assert e.value.code == 2 and "stream requires start or stop" in capsys.readouterr().err


def test_ctl_stream_without_a_player(capsys):
    assert main(["ctl", "stream", "start"]) == 1
    assert capsys.readouterr().err == "gentle-stream: nothing is playing\n"


# ------------------------------------------------------------ end to end, in the background player
@needs_ffmpeg
def test_the_background_player_broadcasts_and_its_status_never_shows_the_key(runtime, capsys, monkeypatch):  # noqa: F811
    import json

    monkeypatch.delenv(streamconf.KEY_ENV, raising=False)
    ingest = FakeIngest()
    streamconf.save_url(ingest.url)
    streamconf.save_key(KEY)
    assert main(["ctl", "status"]) == 0 and json.loads(capsys.readouterr().out) == {"running": False}
    from gentle_stream import client

    client.ensure().detach()                                  # start the background player
    assert main(["ctl", "stream", "start"]) == 0
    assert capsys.readouterr().out == f"Broadcasting to {ingest.url}\n"
    assert main(["ctl", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["stream"]["target"] == ingest.url and status["stream"]["running"] and KEY not in str(status)
    ps = subprocess.run(["ps", "-axo", "command="], capture_output=True, text=True, check=False).stdout
    assert "ffmpeg" in ps and KEY not in ps
    assert wait_for(lambda: {8, 9} <= {kind for kind, _, _ in ingest.media})
    assert main(["ctl", "stream", "stop"]) == 0
    out, err = capsys.readouterr()
    assert out.startswith(f"Broadcast to {ingest.url} ended after 0:0") and err == "" and KEY not in out
    ingest.wait()

