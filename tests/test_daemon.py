"""The background player: a `gentle-stream daemon` process that owns the audio, controlled over a private socket.

Every test runs its daemons in a short private runtime dir under /tmp (AF_UNIX paths are limited to ~104 bytes) with
a fake audio stream, and stops or kills them afterwards. The user's real runtime dir is never touched.
"""
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from gentle_stream import main
from gentle_stream.engine import Engine
from gentle_stream.player import Player
from gentle_stream.style import Style
from tests.test_player import FakeStream

REPO = str(Path(__file__).resolve().parents[1])


class FakeAudio:
    """sounddevice.OutputStream stand-in for the daemon process: a thread pulls the callback 4x faster than real
    time, so "now playing" advances like on a real device, only quicker."""

    SPEED = 4

    def __init__(self, callback, samplerate, blocksize, **kw):
        self.callback, self.sr, self.blocksize = callback, samplerate, blocksize
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        out = np.zeros((self.blocksize, 2), dtype=np.float32)
        while not self._stop.wait(self.blocksize / self.sr / self.SPEED):
            self.callback(out, self.blocksize, None, None)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def close(self):
        if self._thread.is_alive():
            self._thread.join(timeout=2)


def no_device(**kw):
    import sounddevice as sd

    raise sd.PortAudioError("Error querying device -1")


def wait_for(cond, timeout=10.0):
    t0 = time.monotonic()
    while not cond():
        if time.monotonic() - t0 > timeout:
            raise AssertionError("condition not reached")
        time.sleep(0.02)


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def daemon_pids(run):
    lock = run / "player.lock"
    text = lock.read_text().strip() if lock.exists() else ""
    return [int(text)] if text.isdigit() else []


@pytest.fixture
def runtime(monkeypatch):
    """A private runtime dir for the daemons of one test; any daemon left behind is stopped, then killed."""
    root = Path(tempfile.mkdtemp(prefix="gs-", dir="/tmp"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(root))
    monkeypatch.setenv("XDG_CACHE_HOME", str(root / "cache"))     # no soundfont: fast procedural instruments
    monkeypatch.setenv("PYTHONPATH", REPO)                          # the daemon imports FakeAudio from here
    monkeypatch.setenv("GENTLE_STREAM_AUDIO_FACTORY", "tests.test_daemon:FakeAudio")
    run = root / "gentle-stream"
    try:
        yield run
    finally:
        from gentle_stream import client

        pids = daemon_pids(run)
        try:
            client.connect().close()
        except (client.NoPlayer, client.PlayerError):
            pass
        finally:
            for pid in pids:
                if alive(pid):
                    os.kill(pid, signal.SIGKILL)
            shutil.rmtree(root, ignore_errors=True)


def run_ctl(capsys, *args):
    code = main(["ctl", *args])
    out, err = capsys.readouterr()
    return code, out, err


def fake_player():
    """A `Player` with a fake stream, never started: enough for `daemon.handle` without real audio or threads."""
    streams = []
    engine = Engine(Style(bpm=72, energy=0.2), seed=1, samples=False)
    return Player(engine, stream_factory=lambda **kw: streams.append(FakeStream(**kw)) or streams[-1])


# ------------------------------------------------------------ lifecycle
def test_the_first_client_starts_the_player_and_the_next_one_attaches(runtime):
    from gentle_stream import client

    first = client.ensure()
    pid = first.pid
    assert alive(pid) and pid != os.getpid()
    second = client.ensure()                       # a second TUI attaches to the same music
    assert second.pid == pid
    second.set_volume(0.3)
    first.spectrum(16)                             # polling refreshes the cached state
    assert first.volume == pytest.approx(0.3)
    second.detach()
    first.detach()
    assert client.connect().pid == pid             # detaching leaves it running


def test_the_runtime_dir_and_the_authkey_are_private(runtime):
    from gentle_stream import client

    client.ensure().detach()
    assert stat.S_IMODE(runtime.stat().st_mode) == 0o700
    assert stat.S_IMODE((runtime / "authkey").stat().st_mode) == 0o600
    assert stat.S_ISSOCK((runtime / "player.sock").stat().st_mode)


def test_a_wrong_authkey_is_refused(runtime):
    from multiprocessing import AuthenticationError
    from multiprocessing.connection import Client

    from gentle_stream import client

    client.ensure().detach()
    with pytest.raises((AuthenticationError, EOFError, OSError)):
        Client(str(runtime / "player.sock"), family="AF_UNIX", authkey=b"not the key")
    assert client.connect().playing                # the player survives the attempt


def test_only_one_player_runs_per_user(runtime):
    from gentle_stream import client

    pid = client.ensure().pid
    second = subprocess.run([sys.executable, "-m", "gentle_stream", "daemon"], timeout=30,
                            capture_output=True, text=True)
    assert second.returncode == 0
    assert client.connect().pid == pid             # the running player kept its socket


def test_a_crashed_player_is_detected_and_replaced(runtime, capsys):
    from gentle_stream import client

    pid = client.ensure().pid
    os.kill(pid, signal.SIGKILL)                   # leaves the socket file behind
    wait_for(lambda: not alive(pid))
    assert (runtime / "player.sock").exists()
    assert run_ctl(capsys, "status") == (0, '{"running": false}\n', "")
    fresh = client.ensure()
    assert fresh.pid != pid and fresh.playing


def test_a_stale_socket_file_is_replaced(runtime):
    from gentle_stream import client

    runtime.mkdir(mode=0o700, parents=True)
    s = socket.socket(socket.AF_UNIX)
    s.bind(str(runtime / "player.sock"))           # bound and closed: nobody listens
    s.close()
    with pytest.raises(client.NoPlayer):
        client.connect()
    assert client.ensure().playing


def test_stop_ends_the_player_process(runtime):
    from gentle_stream import client

    player = client.ensure()
    pid = player.pid
    player.close()                                 # what `q` does
    wait_for(lambda: not alive(pid))
    assert not (runtime / "player.sock").exists()
    with pytest.raises(client.NoPlayer):
        client.connect()


def test_sigterm_ends_the_player_cleanly(runtime):
    from gentle_stream import client

    pid = client.ensure().pid
    os.kill(pid, signal.SIGTERM)
    wait_for(lambda: not alive(pid))
    assert not (runtime / "player.sock").exists()


def test_an_audio_device_error_is_reported_to_the_client_and_no_player_stays(runtime, monkeypatch):
    from gentle_stream import client

    monkeypatch.setenv("GENTLE_STREAM_AUDIO_FACTORY", "tests.test_daemon:no_device")
    with pytest.raises(client.AudioError) as error:
        client.ensure()
    assert str(error.value) == "Error querying device -1"
    assert not (runtime / "player.sock").exists()
    with pytest.raises(client.NoPlayer):
        client.connect()


# ------------------------------------------------------------ tempo glide (handle(), unit-level)
def test_handle_tempo_applies_a_valid_glide():
    from gentle_stream import daemon

    player = fake_player()
    answer = daemon.handle(player, {"cmd": "tempo", "bpm": 110, "seconds": 30})
    assert answer["ok"] is True
    assert player.engine.target_bpm == 110.0


@pytest.mark.parametrize("request_", [
    {"cmd": "tempo", "bpm": "fast", "seconds": 30},
    {"cmd": "tempo", "bpm": float("nan"), "seconds": 30},
    {"cmd": "tempo", "bpm": float("inf"), "seconds": 30},
    {"cmd": "tempo", "seconds": 30},
    {"cmd": "tempo", "bpm": 110},
    {"cmd": "tempo", "bpm": 110, "seconds": -1},
    {"cmd": "tempo", "bpm": 110, "seconds": 3601},
    {"cmd": "tempo", "bpm": 110, "seconds": "a while"},
], ids=["bpm-string", "bpm-nan", "bpm-inf", "missing-bpm", "missing-seconds", "seconds-negative",
        "seconds-too-large", "seconds-string"])
def test_handle_tempo_rejects_bad_requests_and_leaves_the_style_unchanged(request_):
    from gentle_stream import daemon

    player = fake_player()
    before = player.engine.style.bpm
    answer = daemon.handle(player, request_)
    assert answer["ok"] is False and answer["error"].startswith("bad request: ")
    assert player.engine.style.bpm == before and player.engine.target_bpm is None


def test_handle_glide_queues_one_glide_per_field():
    from gentle_stream import daemon

    player = fake_player()
    answer = daemon.handle(player, {"cmd": "glide", "fields": {"energy": 0.9, "brightness": 0.8}, "seconds": 120})
    assert answer["ok"] is True
    assert player.engine.targets == {"energy": 0.9, "brightness": 0.8}


@pytest.mark.parametrize("request_", [
    {"cmd": "glide", "fields": {"energy": 0.9, "genre": "jazz"}, "seconds": 30},
    {"cmd": "glide", "fields": {"energy": 0.9, "colour": 0.5}, "seconds": 30},
    {"cmd": "glide", "fields": {"energy": 0.9, "brightness": "bright"}, "seconds": 30},
    {"cmd": "glide", "fields": {"energy": 0.9, "space": float("nan")}, "seconds": 30},
    {"cmd": "glide", "fields": {"energy": 0.9, "vinyl": True}, "seconds": 30},
    {"cmd": "glide", "fields": {}, "seconds": 30},
    {"cmd": "glide", "fields": ["energy"], "seconds": 30},
    {"cmd": "glide", "fields": {"energy": 0.9}},
    {"cmd": "glide", "fields": {"energy": 0.9}, "seconds": 3601},
    {"cmd": "glide", "seconds": 30},
], ids=["discrete-field", "unknown-field", "string-value", "nan-value", "bool-value", "no-fields",
        "fields-not-object", "missing-seconds", "seconds-too-large", "missing-fields"])
def test_handle_glide_rejects_bad_requests_atomically(request_):
    from gentle_stream import daemon

    player = fake_player()
    answer = daemon.handle(player, request_)
    assert answer["ok"] is False and answer["error"].startswith("bad request: ")
    assert player.engine.targets == {}            # the valid energy field was not applied either
    player.engine.render_bar()
    assert player.engine.style.energy == 0.2


def test_handle_glide_names_the_rejected_field():
    from gentle_stream import daemon

    answer = daemon.handle(fake_player(), {"cmd": "glide", "fields": {"genre": 1}, "seconds": 1})
    assert "genre" in answer["error"]


# ------------------------------------------------------------ controls and state
def test_controls_reach_the_player(runtime):
    from gentle_stream import client

    player = client.ensure()
    player.toggle()
    assert not player.playing
    player.play()
    assert player.playing
    player.pause()
    assert not player.playing
    player.set_volume(0.42)
    assert player.volume == pytest.approx(0.42)
    player.play()                                  # paused, nothing is pulled and "now" stands still
    piece = player.now.piece
    player.next()
    wait_for(lambda: player.spectrum(8) is not None and player.now.piece > piece)


def test_polling_returns_the_audible_style_and_the_spectrum(runtime):
    from gentle_stream import client

    player = client.ensure()
    wanted = Style(name="Second Wind", mood="rain on a tin roof", genre="jazz", bpm=110)
    player.set_style(wanted)
    wait_for(lambda: player.spectrum(8) is not None and player.style == wanted)     # rendered first
    wait_for(lambda: player.spectrum(8) is not None and player.now.style == wanted, timeout=20)
    bands = player.spectrum(24)
    assert bands.shape == (24,) and np.all((bands >= 0) & (bands <= 1)) and bands.max() > 0
    assert player.level > 0 and player.backend == "procedural"
    assert player.elapsed_seconds >= 0 and player.cycle_remaining_seconds > 0


def test_a_state_round_trip_is_fast(runtime):
    from gentle_stream import client

    player = client.ensure()
    player.spectrum(64)
    t0 = time.perf_counter()
    for _ in range(50):
        player.spectrum(64)
    assert (time.perf_counter() - t0) / 50 < 0.02   # well under one 15 fps frame


def test_a_stopped_player_makes_polling_fail_and_controls_harmless(runtime):
    from gentle_stream import client

    watcher = client.ensure()
    client.connect().close()                        # stopped from somewhere else
    watcher.toggle()                                # no exception from a key press
    with pytest.raises(ConnectionError):
        watcher.spectrum(8)
    watcher.close()                                 # quitting afterwards is harmless too


# ------------------------------------------------------------ ctl
@pytest.mark.parametrize("action", ["play", "pause", "toggle", "next", "stop"])
def test_ctl_without_a_player_says_nothing_is_playing(runtime, capsys, action):
    assert run_ctl(capsys, action) == (1, "", "gentle-stream: nothing is playing\n")


def test_ctl_status_without_a_player(runtime, capsys):
    assert run_ctl(capsys, "status") == (0, '{"running": false}\n', "")
    assert not runtime.exists() or not (runtime / "player.sock").exists()   # status never starts a player


def test_ctl_controls_a_running_player(runtime, capsys):
    from gentle_stream import client

    player = client.ensure()
    player.set_style(Style(name="Café Night", mood="late café", genre="jazz"))
    wait_for(lambda: player.spectrum(8) is not None and player.now.style.name == "Café Night", timeout=20)
    code, out, err = run_ctl(capsys, "status")
    assert (code, err) == (0, "") and out.endswith("\n") and out.count("\n") == 1
    assert json.loads(out) == {"running": True, "playing": True, "name": "Café Night", "genre": "jazz",
                               "mood": "late café", "bpm": player.bpm, "target_bpm": player.target_bpm,
                               "journey": None}
    assert list(json.loads(out)) == ["running", "playing", "name", "genre", "mood", "bpm", "target_bpm", "journey"]
    assert run_ctl(capsys, "pause") == (0, "", "")
    assert json.loads(run_ctl(capsys, "status")[1])["playing"] is False
    assert run_ctl(capsys, "toggle") == (0, "", "")
    assert json.loads(run_ctl(capsys, "status")[1])["playing"] is True
    assert run_ctl(capsys, "next") == (0, "", "")
    assert run_ctl(capsys, "play") == (0, "", "")
    pid = player.pid
    assert run_ctl(capsys, "stop") == (0, "", "")
    assert not alive(pid) or wait_for(lambda: not alive(pid)) is None
    assert run_ctl(capsys, "status") == (0, '{"running": false}\n', "")


def test_the_client_attaches_to_a_player_older_than_the_timing_and_tempo_keys():
    """A background player started before an upgrade keeps running: its state lacks elapsed_seconds,
    cycle_remaining_seconds, start_seconds, bpm and target_bpm, and the new client must still attach to it."""
    from gentle_stream.client import PlayerClient

    old_state = {"pid": 1, "playing": True, "volume": 0.8, "level": 0.0, "backend": "procedural",
                 "now": {"style": Style(bpm=80).to_dict(), "piece": 1, "bar": 3}, "style": Style(bpm=80).to_dict()}

    class OldConnection:
        def send_bytes(self, data):
            pass

        def recv_bytes(self):
            return json.dumps({"ok": True, "state": old_state}).encode()

        def close(self):
            pass

    player = PlayerClient(OldConnection())
    assert player.now.bar == 3 and player.bpm == 80.0 and player.target_bpm is None
    assert player.now.journey is None
    assert player.elapsed_seconds == 0.0 and player.cycle_remaining_seconds == 0.0


# ------------------------------------------------------------ journeys (handle(), unit-level)
def test_handle_journey_start_runs_a_built_in_journey_from_the_next_bar():
    from gentle_stream import daemon
    from gentle_stream.journey import BUILTIN

    player = fake_player()
    answer = daemon.handle(player, {"cmd": "journey_start", "name": "warm-up"})
    assert answer["ok"] is True and "state" in answer
    player.engine.render_bar()
    assert player.engine.journey is BUILTIN["warm-up"]
    answer = daemon.handle(player, {"cmd": "journey_stop"})
    assert answer["ok"] is True
    player.engine.render_bar()
    assert player.engine.journey is None


def test_handle_journey_stop_without_a_journey_is_fine():
    from gentle_stream import daemon

    player = fake_player()
    assert daemon.handle(player, {"cmd": "journey_stop"})["ok"] is True
    player.engine.render_bar()
    assert player.engine.journey is None


def test_handle_journey_start_refuses_an_unknown_name_and_lists_the_built_ins():
    from gentle_stream import daemon
    from gentle_stream.journey import BUILTIN

    player = fake_player()
    answer = daemon.handle(player, {"cmd": "journey_start", "name": "nope"})
    assert answer == {"ok": False, "error": f'no journey called "nope" (choose from {", ".join(BUILTIN)})'}
    player.engine.render_bar()
    assert player.engine.journey is None


@pytest.mark.parametrize("request_", [
    {"cmd": "journey_start"},
    {"cmd": "journey_start", "name": 3},
    {"cmd": "journey_start", "name": None},
], ids=["missing-name", "number-name", "null-name"])
def test_handle_journey_start_rejects_bad_requests(request_):
    from gentle_stream import daemon

    player = fake_player()
    answer = daemon.handle(player, request_)
    assert answer["ok"] is False and answer["error"].startswith("bad request: ")
    player.engine.render_bar()
    assert player.engine.journey is None


# ------------------------------------------------------------ journey progress in the state
def test_state_reports_no_journey_as_null_after_the_existing_keys():
    from gentle_stream import daemon

    state = daemon.state(fake_player())
    assert state["journey"] is None
    assert list(state)[-3:] == ["bpm", "target_bpm", "journey"]


def test_state_reports_the_journey_snapshot_of_the_audible_bar():
    from gentle_stream import daemon
    from gentle_stream.journey import JourneySnapshot
    from gentle_stream.player import NowPlaying

    player = fake_player()
    snap = JourneySnapshot("warm-up", "Warm-up", 2, 4, "Wake", 0.5, 66.0, 72.0, 450.0)
    player.now = NowPlaying(player.now.style, 1, 7, 20.0, snap)
    state = json.loads(json.dumps(daemon.state(player)))
    assert state["journey"] == snap.to_dict()


def test_the_client_reads_the_journey_snapshot_from_the_state():
    from gentle_stream import daemon
    from gentle_stream.client import PlayerClient
    from gentle_stream.journey import JourneySnapshot
    from gentle_stream.player import NowPlaying

    player = fake_player()
    snap = JourneySnapshot("warm-up", "Warm-up", 4, 4, "Glow", 1.0, 100.0, 100.0, None)
    player.now = NowPlaying(player.now.style, 1, 7, 20.0, snap)

    class Connection:
        def send_bytes(self, data):
            pass

        def recv_bytes(self):
            return json.dumps(daemon.handle(player, {"cmd": "state"})).encode()

        def close(self):
            pass

    assert PlayerClient(Connection()).now.journey == snap


def test_handle_glide_refuses_a_field_driven_by_the_journey_with_a_plain_error():
    from gentle_stream import daemon

    player = fake_player()
    daemon.handle(player, {"cmd": "journey_start", "name": "warm-up"})
    driven = ('is driven by the journey "warm-up"; stop it first (gentle-stream journey stop)')
    assert daemon.handle(player, {"cmd": "tempo", "bpm": 110, "seconds": 30}) == {"ok": False,
                                                                                  "error": f"bpm {driven}"}
    answer = daemon.handle(player, {"cmd": "glide", "fields": {"space": 0.9, "energy": 0.9}, "seconds": 30})
    assert answer == {"ok": False, "error": f"energy {driven}"}
    assert player.engine.targets == {}
    assert daemon.handle(player, {"cmd": "glide", "fields": {"space": 0.9}, "seconds": 30})["ok"] is True
