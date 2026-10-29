"""S7: mute here, keep broadcasting. Muting silences the speakers only; the broadcast and the session recording keep
the sound (at its volume), the TUI keeps showing it, and pause still stops the music for everyone."""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from gentle_stream import broadcast, main, streamconf
from gentle_stream.engine import Engine
from gentle_stream.player import Player
from gentle_stream.style import Style
from tests.rtmp_fake import FakeIngest
from tests.test_app import FakeShell, make_app, text
from tests.test_player import FakeStream

FAKE = str(Path(__file__).with_name("fake_encoder.py"))


def make_player() -> Player:
    player = Player(Engine(Style(), seed=1, samples=False), stream_factory=FakeStream, prebuffer=0.3)
    player.start()
    return player


def pull(player: Player, frames: int = 512) -> np.ndarray:
    stream = player._stream
    assert isinstance(stream, FakeStream)
    return stream.pull(frames).copy()


def test_muted_the_speakers_go_silent_without_a_click_and_come_back():
    player = make_player()
    try:
        for _ in range(10):
            pull(player)
        assert not player.muted
        before = pull(player)
        player.set_muted(True)
        first = pull(player)
        # a fade over 30 ms (longer than a block), not a step: the block starts with the music and goes down
        assert np.abs(first[:32]).max() > 0.5 * np.abs(before[-32:]).max() > 0
        assert np.sqrt(np.mean(first[-64:] ** 2)) < 0.8 * np.sqrt(np.mean(first[:64] ** 2))
        silent = first
        for _ in range(4):
            silent = pull(player)
        assert np.abs(silent).max() == 0.0
        assert player.level > 0                                     # the TUI still shows the music
        player.set_muted(False)
        back = silent
        for _ in range(4):
            back = pull(player)
        assert np.abs(back).max() > 0.01
    finally:
        player.close()


def test_muted_the_broadcast_and_the_recording_keep_the_sound(monkeypatch, tmp_path):
    monkeypatch.delenv(streamconf.KEY_ENV, raising=False)
    ingest = FakeIngest()
    streamconf.save_url(ingest.url)
    streamconf.save_key("SENTINEL-KEY-mute-1a1a")
    out = tmp_path / "pcm"
    monkeypatch.setattr(broadcast, "encoder_command",
                        lambda sr: [sys.executable, FAKE, "copy", str(out), "{video_fd}"])
    player = make_player()
    try:
        for _ in range(10):
            pull(player)
        player.stream_start()
        player.record_start(str(tmp_path / "rec.wav"))
        player.set_muted(True)
        heard = []
        for _ in range(40):
            heard.append(pull(player))
            time.sleep(0.002)
        assert np.abs(np.concatenate(heard[10:])).max() == 0.0      # nothing from the speakers
        time.sleep(0.3)
        player.record_stop()
        player.stream_stop()
    finally:
        player.close()
    sent = np.frombuffer(out.read_bytes(), dtype=np.float32)
    assert np.abs(sent[-512 * 2 * 20:]).max() > 0.01                # the broadcast kept the music
    from scipy.io import wavfile

    _, recorded = wavfile.read(tmp_path / "rec.wav")
    assert np.abs(recorded[-512 * 20:]).max() > 300                 # and so did the recording


def test_pause_still_stops_the_music_for_everyone():
    player = make_player()
    try:
        player.set_muted(True)
        player.pause()
        block = pull(player)
        for _ in range(6):
            block = pull(player)
        assert np.abs(block).max() == 0.0 and player.muted
    finally:
        player.close()


# ------------------------------------------------------------ the background player and ctl
def test_the_daemon_mutes_and_reports_it():
    from gentle_stream.daemon import handle, state
    from tests.test_daemon import fake_player

    player = fake_player()
    assert state(player)["muted"] is False and list(state(player))[-2:] == ["muted", "output"]
    assert handle(player, {"cmd": "mute", "on": True})["ok"] and player.muted
    assert handle(player, {"cmd": "mute", "on": False})["ok"] and not player.muted
    assert handle(player, {"cmd": "mute", "on": "yes"}) == {"ok": False, "error": "bad request: on must be true or false"}
    assert not player.muted


class FakeClient:
    def __init__(self):
        self.calls = []

    def mute(self, on: bool) -> None:
        self.calls.append(on)

    def detach(self):
        pass


def test_ctl_mute_and_unmute(monkeypatch, capsys):
    from gentle_stream import client

    fake = FakeClient()
    monkeypatch.setattr(client, "connect", lambda: fake)
    assert main(["ctl", "mute"]) == 0
    assert capsys.readouterr() == ("Muted here; a broadcast or a recording keeps the sound\n", "")
    assert main(["ctl", "unmute"]) == 0
    assert capsys.readouterr() == ("Sound back here\n", "")
    assert fake.calls == [True, False]


def test_ctl_mute_without_a_player(capsys):
    assert main(["ctl", "mute"]) == 1
    assert capsys.readouterr().err == "gentle-stream: nothing is playing\n"


@pytest.mark.parametrize("args", [["ctl", "mute", "now"], ["ctl", "unmute", "x"]])
def test_ctl_mute_takes_no_arguments(capsys, args):
    with pytest.raises(SystemExit) as e:
        main(args)
    assert e.value.code == 2 and "takes no arguments" in capsys.readouterr().err


def test_ctl_status_reports_muted(monkeypatch, capsys):
    from types import SimpleNamespace

    from gentle_stream import client

    fake = SimpleNamespace(now=SimpleNamespace(style=Style(name="X"), journey=None), playing=True, bpm=72.0,
                           target_bpm=None, binaural=None, streaming=None, muted=True, output={"name": "X"},
                           detach=lambda: None)
    monkeypatch.setattr(client, "connect", lambda: fake)
    assert main(["ctl", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["muted"] is True and list(status)[-2:] == ["muted", "output"]


# ------------------------------------------------------------ the TUI
@pytest.mark.asyncio
async def test_M_mutes_here_and_the_state_line_says_so():
    app, player = make_app(FakeShell())
    async with app.run_test() as pilot:
        await pilot.press("M")
        await pilot.pause(0.6)
        assert player.muted
        assert "MUTED here" in text(app, "#state")
        assert "Muted here; a broadcast or a recording keeps the sound" in text(app, "#status")
        await pilot.press("M")
        await pilot.pause(0.6)
        assert not player.muted and "MUTED" not in text(app, "#state")


def test_the_palette_offers_mute_here():
    from gentle_stream.app import StreamApp

    assert "Mute here" in {title for title, _, _ in StreamApp.palette_actions()}
