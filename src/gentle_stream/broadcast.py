"""A live broadcast (PM-045): what plays, and a picture of it, encoded by ffmpeg and published over RTMP(S).

The audio callback hands each block to `feed()`, which only copies it into a bounded queue and never waits: when the
encoder or the network falls behind, broadcast blocks are dropped and counted, local audio is never touched. Threads
do the rest: one writes the PCM to ffmpeg's stdin, one draws a frame every 100 ms and another writes it to ffmpeg's
video pipe (passed by its own descriptor number, `pipe:N`), one publishes ffmpeg's FLV output with rtmp.Publisher,
and one keeps ffmpeg's last stderr lines and notices when it exits. ffmpeg's arguments hold no URL and no key; any
text that could (stderr, errors) is masked. A failure stops the broadcast and is kept for `status()`.
"""
from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from typing import IO, Any, TypedDict

import numpy as np

from .broadcast_view import FPS, HEIGHT, WIDTH, BroadcastView, ViewText
from .rtmp import Publisher, PublishError
from .streamconf import StreamKey

VIDEO_RATE = "2500k"   # constant, as YouTube asks of 720p at 30 fps
AUDIO_QUEUE = 64        # blocks: about 0.75 s at 512 frames
VIDEO_QUEUE = 4         # frames
HIDDEN = "<stream key>"


class BroadcastError(Exception):
    """A broadcast that cannot start (no URL or key, no Pillow, phrases without espeak-ng, the ingest refused it);
    the message is meant for the terminal and never holds the key."""


class BroadcastStatus(TypedDict):
    target: str
    seconds: float
    dropped_frames: int
    error: str | None
    running: bool


def encoder_command(sr: int) -> list[str]:
    """ffmpeg reading float32 stereo PCM on stdin and RGB24 frames on `pipe:{video_fd}`, writing H.264 + AAC as FLV
    to stdout: no network, no URL, no key."""
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "f32le", "-ar", str(sr), "-ac", "2", "-i", "pipe:0",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "pipe:{video_fd}",
            "-map", "1:v", "-map", "0:a",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency", "-pix_fmt", "yuv420p", "-g", str(2 * FPS),
            "-b:v", VIDEO_RATE, "-maxrate", VIDEO_RATE, "-bufsize", "5000k", "-x264-params", "nal-hrd=cbr",
            "-c:a", "aac", "-b:a", "160k", "-f", "flv", "pipe:1"]


class Broadcast:
    """One broadcast to `url`: `start()`, `feed()` from the audio callback, `status()`, `stop()`."""

    def __init__(self, url: str, key: StreamKey, sr: int, view: BroadcastView, text: Callable[[], ViewText],
                 levels: Callable[[], np.ndarray], encoder_command: list[str] | None = None,
                 publisher_factory: Callable[..., Any] = Publisher):
        self.url, self.key, self.sr = url, key, sr
        self.view, self.text, self.levels = view, text, levels
        self.encoder_command = encoder_command or globals()["encoder_command"](sr)
        self.publisher_factory = publisher_factory
        self._audio: queue.Queue[bytes | None] = queue.Queue(AUDIO_QUEUE)
        self._video: queue.Queue[bytes | None] = queue.Queue(VIDEO_QUEUE)
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        self._process: subprocess.Popen[bytes] | None = None
        self._publisher: Any = None
        self._video_fd: int | None = None
        self._threads: dict[str, threading.Thread] = {}
        self._running = False
        self._error: str | None = None
        self._dropped = 0
        self._started: float | None = None
        self._ended: float | None = None
        self._stderr: deque[str] = deque(maxlen=8)

    # -------------------------------------------------------- starting
    def start(self) -> None:
        """Start the encoder, connect to the ingest and start the threads; a failure is kept in `status()`."""
        with self._lock:
            if self._running:
                return
        self._stopping.clear()
        self._error, self._dropped, self._ended = None, 0, None
        self._started = time.monotonic()
        read_fd, write_fd = os.pipe()
        command = [arg.replace("{video_fd}", str(read_fd)) for arg in self.encoder_command]
        try:
            self._process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE, pass_fds=(read_fd,))
        except OSError as e:
            os.close(write_fd)
            self._fail(f"cannot start the encoder ({command[0]}): {e.strerror or e}")
            return
        finally:
            os.close(read_fd)            # the encoder has its own copy
        self._video_fd = write_fd
        try:
            publisher = self.publisher_factory(self.url, self.key)
            publisher.open()
        except PublishError as e:
            self._fail(str(e))
            self._shutdown()
            return
        self._publisher = publisher
        with self._lock:
            self._running = True
        for name, target in (("audio", self._write_audio), ("draw", self._draw_video),
                             ("video", self._write_video), ("publish", self._publish), ("encoder", self._watch)):
            self._threads[name] = threading.Thread(target=target, name=f"broadcast-{name}", daemon=True)
            self._threads[name].start()

    # -------------------------------------------------------- the audio callback's side
    def feed(self, block: np.ndarray) -> None:
        """Called from the audio callback: copy the block for the encoder, or drop it; never waits, never raises."""
        if not self._running:
            return
        try:
            self._audio.put_nowait(np.ascontiguousarray(block, dtype=np.float32).tobytes())
        except queue.Full:
            self._dropped += 1

    # -------------------------------------------------------- the threads
    def _fail(self, message: str) -> None:
        """Keep the first error (masked) and stop broadcasting; failures while stopping are not errors."""
        with self._lock:
            if self._error is None and not self._stopping.is_set():
                self._error = message.replace(self.key.reveal(), HIDDEN)
            self._running = False
            self._ended = self._ended or time.monotonic()
        self._stopping.set()

    def _drain(self, q: queue.Queue[bytes | None], write: Callable[[bytes], Any], what: str) -> None:
        while not self._stopping.is_set():
            try:
                data = q.get(timeout=0.1)
            except queue.Empty:
                continue
            if data is None:
                return
            try:
                write(data)
            except (OSError, ValueError):
                if not self._encoder_ended():
                    self._fail(f"the encoder stopped reading its {what}")
                return

    def _write_audio(self) -> None:
        stdin = self._process.stdin if self._process else None
        if stdin is not None:
            self._drain(self._audio, lambda data: (stdin.write(data), stdin.flush()), "audio")

    def _write_video(self) -> None:
        fd = self._video_fd
        if fd is not None:
            self._drain(self._video, lambda data: _write_all(fd, data), "video")

    def _draw_video(self) -> None:
        """FPS frames a second by the clock: frame n is due at n / FPS from the start, and a picture drawn late is
        sent again for every frame time it missed. The encoder stamps frames by their count, so fewer frames than
        the clock asks for would put the video behind the audio, and ffmpeg would stop reading the audio to wait."""
        start, sent = time.monotonic(), 0
        while not self._stopping.is_set():
            due = int((time.monotonic() - start) * FPS) + 1
            if sent >= due:
                self._stopping.wait(max(0.0, start + sent / FPS - time.monotonic()))
                continue
            try:
                frame = self.view.frame(self.text(), self.levels())
            except Exception as e:  # noqa: BLE001  (any drawing failure ends the broadcast, reported)
                self._fail(f"cannot draw the picture: {e}")
                return
            due = max(due, int((time.monotonic() - start) * FPS) + 1)
            while sent < due:
                try:
                    self._video.put_nowait(frame)
                except queue.Full:
                    self._dropped += 1
                sent += 1

    def _publish(self) -> None:
        stdout = self._process.stdout if self._process else None
        if stdout is None:
            return
        try:
            self._publisher.publish_from(stdout)
        except PublishError as e:
            if not self._encoder_ended():
                self._fail(str(e))

    def _encoder_ended(self) -> bool:
        """Whether the encoder has exited (waiting a moment for it): a broken pipe or stream it causes is reported
        by `_watch`, with the encoder's own message, rather than as the pipe's error."""
        process = self._process
        if process is None:
            return True
        with suppress(subprocess.TimeoutExpired):
            process.wait(2)
        return process.poll() is not None

    def _watch(self) -> None:
        """Keep ffmpeg's last stderr lines; an exit while broadcasting is a failure."""
        process = self._process
        if process is None or process.stderr is None:
            return
        for raw in iter(process.stderr.readline, b""):
            self._stderr.append(raw.decode(errors="replace").strip().replace(self.key.reveal(), HIDDEN))
        code = process.wait()
        if not self._stopping.is_set():
            last = " · ".join(line for line in self._stderr if line) or "no message"
            self._fail(f"the encoder exited (code {code}): {last}")

    # -------------------------------------------------------- stopping
    def stop(self) -> None:
        """End the broadcast: drain nothing more, let ffmpeg finish its stream, close the publish. Idempotent."""
        with self._lock:
            self._running = False
            self._ended = self._ended or (time.monotonic() if self._started is not None else None)
        self._stopping.set()
        self._shutdown()

    def _shutdown(self) -> None:
        self._stopping.set()
        process = self._process
        for q in (self._audio, self._video):
            with suppress(queue.Full):
                q.put_nowait(None)
        writers = [self._threads.get(name) for name in ("audio", "video", "draw")]
        for thread in writers:
            if thread is not None:
                thread.join(1.0)
        if process is not None and any(t is not None and t.is_alive() for t in writers):
            process.kill()               # a stuck encoder: its pipes are full and nobody reads them
            for thread in writers:
                if thread is not None:
                    thread.join(2.0)
        if process is not None and process.stdin is not None:
            with suppress(OSError, ValueError):
                process.stdin.close()
        if self._video_fd is not None:
            with suppress(OSError):
                os.close(self._video_fd)
            self._video_fd = None
        if process is not None:
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for name in ("publish", "encoder"):
            if (thread := self._threads.get(name)) is not None:
                thread.join(5.0)
        if self._publisher is not None:
            self._publisher.close()
        for stream in (process.stdout, process.stderr) if process is not None else ():
            if stream is not None:
                with suppress(OSError):
                    stream.close()
        self._threads, self._process, self._publisher = {}, None, None

    # -------------------------------------------------------- status
    def status(self) -> BroadcastStatus:
        """Where it goes (never the key), how long it has run, what was dropped, the last error, whether it runs."""
        start = self._started
        seconds = 0.0 if start is None else (self._ended or time.monotonic()) - start
        return {"target": self.url, "seconds": max(0.0, seconds), "dropped_frames": self._dropped,
                "error": self._error, "running": self._running}


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        view = view[os.write(fd, view):]


__all__ = ["IO", "Broadcast", "BroadcastError", "BroadcastStatus", "encoder_command"]
