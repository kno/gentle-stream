"""PM-045 T4: the broadcast pipeline. The audio callback feeds it and never waits; ffmpeg encodes without seeing the
URL or the key; failures are reported, never raised into the audio path."""
import itertools
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

from gentle_stream.broadcast import Broadcast
from gentle_stream.broadcast_view import BroadcastView, ViewText
from gentle_stream.streamconf import StreamKey
from tests.rtmp_fake import FakeIngest

KEY = "SENTINEL-KEY-t4-5e5e-kk"
SR = 44100
FAKE = str(Path(__file__).with_name("fake_encoder.py"))
TEXT = ViewText(title="♪ Test", details="lofi · A minor · 72 bpm")
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is needed for this check")


@pytest.fixture(scope="module")
def view():
    return BroadcastView()


def blocks(n: int, frames: int = 512, seed: int = 1) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    return [rng.uniform(-1, 1, (frames, 2)).astype(np.float32) for _ in range(n)]


def make(ingest, view, mode: str | None, out: Path | None = None) -> Broadcast:
    command = None if mode is None else [sys.executable, FAKE, mode, str(out or "/dev/null"), "{video_fd}"]
    return Broadcast(ingest.url, StreamKey(KEY), SR, view, lambda: TEXT, lambda: np.zeros(48),
                     encoder_command=command)


def wait_for(predicate, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_the_audio_sent_is_the_audio_fed_byte_for_byte(tmp_path, view):
    """S1: what the device plays (the fed blocks) is what the encoder receives, in order."""
    ingest, out = FakeIngest(), tmp_path / "pcm"
    broadcast = make(ingest, view, "copy", out)
    broadcast.start()
    fed = blocks(200)
    for block in fed:
        broadcast.feed(block)
        time.sleep(0.001)                       # paced like a callback, so nothing is dropped
    assert wait_for(lambda: broadcast._audio.empty())
    broadcast.stop()
    ingest.wait()
    assert broadcast.status()["dropped_frames"] == 0
    assert out.read_bytes() == np.concatenate(fed).tobytes()
    assert int(Path(str(out) + ".video").read_text()) % (1280 * 720 * 3) == 0      # whole frames only
    assert [kind for kind, _, _ in ingest.media][:2] == [9, 8]                     # the encoder's FLV reached it


def test_a_stalled_encoder_drops_broadcast_blocks_and_never_makes_the_callback_wait(view):
    """S1: the encoder reads nothing; feed() stays instant and counts what it drops."""
    ingest = FakeIngest()
    broadcast = make(ingest, view, "stall")
    broadcast.start()
    many = blocks(500)
    start = time.perf_counter()
    for block in many:
        broadcast.feed(block)
    took = time.perf_counter() - start
    status = broadcast.status()
    started = time.monotonic()
    broadcast.stop()
    assert took < 0.05, f"500 feeds took {took * 1000:.1f} ms"
    assert status["dropped_frames"] > 0 and status["running"]
    assert time.monotonic() - started < 6                     # a stuck encoder is killed, stop() returns


def test_a_failing_encoder_is_reported_without_the_key_and_feed_stays_harmless(view, monkeypatch):
    """S3 (and S2 for errors): the encoder exits 1 with the key in its stderr."""
    monkeypatch.setenv("FAKE_KEY", KEY)
    ingest = FakeIngest()
    broadcast = make(ingest, view, "fail")
    broadcast.start()
    assert wait_for(lambda: not broadcast.status()["running"])
    status = broadcast.status()
    assert status["error"] and "connection refused" in status["error"] and "<stream key>" in status["error"]
    assert KEY not in str(status)
    for block in blocks(50):
        broadcast.feed(block)                     # no exception, nothing queued
    assert broadcast._audio.empty()
    broadcast.stop()


def test_an_unreachable_ingest_is_reported_and_no_encoder_is_left_running(view):
    broadcast = Broadcast("rtmp://127.0.0.1:9/live2", StreamKey(KEY), SR, view, lambda: TEXT, lambda: np.zeros(48),
                          encoder_command=[sys.executable, FAKE, "stall", "/dev/null", "{video_fd}"])
    broadcast.start()
    status = broadcast.status()
    assert not status["running"] and "cannot reach 127.0.0.1:9" in str(status["error"])
    assert broadcast._process is None or broadcast._process.poll() is not None


def test_the_encoder_command_has_neither_the_url_nor_the_key(view):
    """S2: ffmpeg's arguments are visible to `ps`; only the publisher in this process holds the key."""
    ingest = FakeIngest()
    command = make(ingest, view, None).encoder_command
    assert command[0] == "ffmpeg" and "pipe:{video_fd}" in command and command[-1] == "pipe:1"
    assert not any(KEY in arg or "rtmp" in arg for arg in command)


def test_the_callers_file_descriptors_are_left_alone(view, tmp_path):
    """The video pipe goes to the encoder by its own number; nothing in this process is renumbered."""
    with open(tmp_path / "keep", "w") as keep:
        before = keep.fileno()
        ingest = FakeIngest()
        broadcast = make(ingest, view, "copy", tmp_path / "pcm")
        broadcast.start()
        broadcast.stop()
        keep.write("still mine")
        assert keep.fileno() == before
    assert (tmp_path / "keep").read_text() == "still mine"


def test_stop_is_idempotent_and_leaves_no_threads_or_processes(view, tmp_path):
    ingest = FakeIngest()
    broadcast = make(ingest, view, "copy", tmp_path / "pcm")
    broadcast.start()
    process = broadcast._process
    threads = [*broadcast._threads.values(), broadcast._publisher._reader_thread]   # this broadcast's own

    def ours() -> list[str]:
        return [t.name for t in threads if t is not None and t.is_alive()]

    broadcast.stop()
    broadcast.stop()
    ingest.wait()
    assert process is not None and process.poll() is not None
    assert wait_for(lambda: not ours(), 5), ours()
    assert not broadcast.status()["running"]


@needs_ffmpeg
def test_with_the_real_ffmpeg_the_ingest_receives_audio_and_video(view):
    """S1/S2 end to end: ~2 s of a sine through ffmpeg to the local ingest; the key is never in ffmpeg's arguments."""
    ingest = FakeIngest()
    broadcast = make(ingest, view, None)
    broadcast.start()
    assert broadcast.status()["running"], broadcast.status()
    pid = broadcast._process.pid if broadcast._process else 0
    args = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True,
                          check=False).stdout
    assert "ffmpeg" in args and KEY not in args
    t = np.arange(512) / SR
    for i in range(int(2.2 * SR / 512)):
        tone = 0.3 * np.sin(2 * np.pi * 440 * (t + i * 512 / SR)).astype(np.float32)
        broadcast.feed(np.stack([tone, tone], axis=1))
        time.sleep(512 / SR)
    broadcast.stop()
    ingest.wait()
    status = broadcast.status()
    assert status["error"] is None and status["target"] == ingest.url and KEY not in str(status)
    kinds = {kind for kind, _, _ in ingest.media}
    assert {8, 9} <= kinds, kinds


def test_the_video_is_30_fps_at_a_constant_2500k_with_a_keyframe_every_2_s(view):
    """S6: what YouTube asks of a 720p stream (its health badge said "bad" at 10 fps and a variable rate)."""
    command = make(FakeIngest(), view, None).encoder_command
    pairs = dict(itertools.pairwise(command))
    assert pairs["-r"] == "30" and pairs["-g"] == "60"
    assert pairs["-b:v"] == pairs["-maxrate"] == "2500k" and pairs["-bufsize"] == "5000k"


class SlowView(BroadcastView):
    """Draws like BroadcastView but takes 20 ms a frame, as a loaded machine might."""

    def frame(self, text, levels):
        time.sleep(0.02)
        return super().frame(text, levels)


def test_the_video_keeps_30_frames_a_second_by_the_clock_even_when_drawing_is_slow(tmp_path):
    """The first live tests said "bad": frames were counted, not clocked, so a late frame put the video behind the
    audio, ffmpeg stopped reading the audio and broadcast blocks were dropped. Frames are now due by the clock; a late
    one repeats the last picture, so the encoder always gets 30 a second."""
    ingest, out = FakeIngest(), tmp_path / "pcm"
    broadcast = Broadcast(ingest.url, StreamKey(KEY), SR, SlowView(), lambda: TEXT, lambda: np.zeros(48),
                          encoder_command=[sys.executable, FAKE, "copy", str(out), "{video_fd}"])
    broadcast.start()
    started = time.monotonic()
    time.sleep(2.0)
    broadcast.stop()
    elapsed = time.monotonic() - started
    frames = int(Path(str(out) + ".video").read_text()) // (1280 * 720 * 3)
    assert frames >= 0.95 * 30 * elapsed - 2, (frames, elapsed)
    assert frames <= 30 * elapsed + 2
    assert broadcast.status()["dropped_frames"] == 0
