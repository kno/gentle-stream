"""PM-036: record exactly what the player gives the device into a WAV file."""
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile

from gentle_stream import daemon, main, recorder
from gentle_stream.engine import Engine
from gentle_stream.player import Player
from gentle_stream.recorder import Recorder, RecordError
from gentle_stream.style import Style
from tests.test_player import FakeStream

SR = 48000


def blocks(n=20, frames=1024, seed=1):
    rng = np.random.default_rng(seed)
    return [rng.uniform(-0.9, 0.9, (frames, 2)).astype(np.float32) for _ in range(n)]


def as_int16(x):
    return np.round(np.clip(x, -1, 1) * 32767).astype(np.int16)


# ------------------------------------------------------------ the recorder
def test_the_file_holds_every_sample_fed_in_order(tmp_path):
    path = tmp_path / "s.wav"
    rec = Recorder(path, SR)
    fed = blocks()
    for b in fed:
        rec.feed(b)
    rec.stop()
    sr, data = wavfile.read(path)
    assert sr == SR and data.dtype == np.int16 and data.shape == (20 * 1024, 2)
    assert np.array_equal(data, as_int16(np.concatenate(fed)))
    assert rec.seconds == pytest.approx(20 * 1024 / SR)


def test_the_file_is_a_valid_wav_while_recording(tmp_path):
    """A crash leaves a valid file: the header is updated after every block the writer saves."""
    path = tmp_path / "s.wav"
    rec = Recorder(path, SR)
    fed = blocks(5)
    for b in fed:
        rec.feed(b)
    rec.drain()                                            # the writer has saved what was fed
    sr, data = wavfile.read(path)                          # read before stop: no finalising step needed
    assert sr == SR and np.array_equal(data, as_int16(np.concatenate(fed)))
    rec.stop()


def test_feeding_never_waits_for_the_disk_and_drops_nothing(tmp_path, monkeypatch):
    path = tmp_path / "s.wav"
    rec = Recorder(path, SR)
    real = rec._write_frames
    gate = threading.Event()

    def slow(data):
        gate.wait(5)                                       # the disk is stuck until we let it go
        real(data)

    monkeypatch.setattr(rec, "_write_frames", slow)
    fed = blocks(50)
    t0 = time.perf_counter()
    for b in fed:
        rec.feed(b)
    assert time.perf_counter() - t0 < 0.05                 # 50 blocks queued without waiting for the disk
    gate.set()
    rec.stop()
    assert np.array_equal(wavfile.read(path)[1], as_int16(np.concatenate(fed)))


def test_feed_keeps_its_own_copy(tmp_path):
    path = tmp_path / "s.wav"
    rec = Recorder(path, SR)
    b = np.full((256, 2), 0.5, dtype=np.float32)
    rec.feed(b)
    b[:] = 0.0                                              # the device buffer is reused for the next block
    rec.stop()
    assert np.all(wavfile.read(path)[1] == as_int16(np.full((256, 2), 0.5)))


@pytest.mark.parametrize("name, message", [("s.mp3", "must end in .wav"),
                                           ("missing/dir/s.wav", "no such folder")])
def test_bad_paths_are_refused(tmp_path, name, message):
    with pytest.raises(RecordError, match=message):
        Recorder(tmp_path / name, SR)


def test_an_existing_file_needs_force(tmp_path):
    path = tmp_path / "s.wav"
    path.write_bytes(b"keep me")
    with pytest.raises(RecordError, match="already exists"):
        Recorder(path, SR)
    assert path.read_bytes() == b"keep me"
    Recorder(path, SR, force=True).stop()
    assert wavfile.read(path)[1].shape == (0, 2)


# ------------------------------------------------------------ the player
def started_player():
    streams = []
    player = Player(Engine(Style(), seed=1, samples=False),
                    stream_factory=lambda **kw: streams.append(FakeStream(**kw)) or streams[-1], prebuffer=0.3)
    player.start()
    return player, streams[0]


def test_the_recording_equals_what_the_device_was_given(tmp_path):
    player, stream = started_player()
    try:
        given = [stream.pull(512) for _ in range(4)]          # before: not recorded
        player.record_start(tmp_path / "s.wav")
        given = [stream.pull(512) for _ in range(30)]
        player.set_volume(0.3)                                # volume changes are what the device got
        given += [stream.pull(512) for _ in range(10)]
        player.pause()
        given += [stream.pull(512) for _ in range(5)]          # pause: the silence the device got
        info = player.record_stop()
    finally:
        player.close()
    assert info is not None and info[0] == tmp_path / "s.wav"
    assert np.array_equal(wavfile.read(tmp_path / "s.wav")[1], as_int16(np.concatenate(given)))


def test_closing_the_player_finishes_the_recording(tmp_path):
    player, stream = started_player()
    player.record_start(tmp_path / "s.wav")
    for _ in range(8):
        stream.pull(512)
    player.close()
    assert wavfile.read(tmp_path / "s.wav")[1].shape == (8 * 512, 2)
    assert player.recording is None


def test_one_recording_at_a_time(tmp_path):
    player, _ = started_player()
    try:
        player.record_start(tmp_path / "a.wav")
        with pytest.raises(RecordError, match=r"already recording to .*a\.wav"):
            player.record_start(tmp_path / "b.wav")
        assert player.record_stop() is not None
        assert player.record_stop() is None                   # nothing to stop
    finally:
        player.close()


# ------------------------------------------------------------ the background player and ctl
def test_the_daemon_records_reports_and_stops(tmp_path):
    from tests.test_daemon import fake_player

    player = fake_player()
    path = str(tmp_path / "s.wav")
    assert daemon.handle(player, {"cmd": "record_start", "path": "relative.wav"}) == {
        "ok": False, "error": "the path must be absolute"}
    answer = daemon.handle(player, {"cmd": "record_start", "path": path})
    assert answer["ok"] and answer["state"]["recording"] == {"path": path, "seconds": 0.0}
    assert daemon.handle(player, {"cmd": "record_start", "path": path})["error"].startswith("already recording")
    stop = daemon.handle(player, {"cmd": "record_stop"})
    assert stop["ok"] and stop["recorded"] == {"path": path, "seconds": 0.0}
    assert daemon.handle(player, {"cmd": "record_stop"}) == {"ok": False, "error": "not recording"}
    assert daemon.state(player)["recording"] is None


class FakeClient:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def record_start(self, path, force=False):
        from gentle_stream.client import PlayerError
        if self.error:
            raise PlayerError(self.error)
        self.calls.append(("start", path, force))

    def record_stop(self):
        self.calls.append(("stop",))
        return None if self.error == "idle" else ("/music/s.wav", 75.4)

    def detach(self):
        pass


def test_ctl_record_start_sends_an_absolute_path(monkeypatch, capsys, tmp_path):
    from gentle_stream import client
    fake = FakeClient()
    monkeypatch.setattr(client, "connect", lambda: fake)
    monkeypatch.chdir(tmp_path)
    assert main(["ctl", "record", "start", "s.wav", "--force"]) == 0
    assert fake.calls == [("start", str(tmp_path / "s.wav"), True)]
    assert capsys.readouterr() == (f"Recording to {tmp_path / 's.wav'}\n", "")


def test_ctl_record_stop_reports_the_file(monkeypatch, capsys):
    from gentle_stream import client
    fake = FakeClient()
    monkeypatch.setattr(client, "connect", lambda: fake)
    assert main(["ctl", "record", "stop"]) == 0
    assert capsys.readouterr() == ("Saved 1:15 to /music/s.wav\n", "")


def test_ctl_record_stop_when_nothing_records(monkeypatch, capsys):
    from gentle_stream import client
    monkeypatch.setattr(client, "connect", lambda: FakeClient("idle"))
    assert main(["ctl", "record", "stop"]) == 1
    assert capsys.readouterr() == ("", "gentle-stream: not recording\n")


def test_ctl_record_reports_the_player_s_refusal(monkeypatch, capsys):
    from gentle_stream import client
    monkeypatch.setattr(client, "connect", lambda: FakeClient("/music/s.wav already exists (use --force)"))
    assert main(["ctl", "record", "start", "/music/s.wav"]) == 1
    assert capsys.readouterr() == ("", "gentle-stream: /music/s.wav already exists (use --force)\n")


@pytest.mark.parametrize("args, message", [(["ctl", "record"], "record requires start FILE or stop"),
                                           (["ctl", "record", "start"], "record requires start FILE or stop"),
                                           (["ctl", "record", "stop", "x.wav"], "record requires start FILE or stop"),
                                           (["ctl", "glide", "energy=1", "--force"], "--force is only for record")])
def test_ctl_record_usage_errors(capsys, args, message):
    with pytest.raises(SystemExit) as e:
        main(args)
    assert e.value.code == 2 and message in capsys.readouterr().err


assert recorder and Path   # modules under test
