"""Record the session (PM-036): every block the player gives the audio device, into a 16-bit stereo WAV.

The audio callback only queues a copy of each block (`Recorder.feed`): it never waits for the disk. A writer thread
saves the blocks in order and rewrites the two size fields of the WAV header after each one, so the file is a valid
WAV at every moment, even if the process dies; `stop` saves what is queued and closes the file. What is recorded is
what the device was given: the volume, and the silence while paused, included.
"""
from __future__ import annotations

import queue
import struct
import threading
from pathlib import Path

import numpy as np


class RecordError(Exception):
    """A recording that cannot start; the message is meant for the terminal."""


def _header(sr: int, frames: int) -> bytes:
    data = frames * 4
    fmt = struct.pack("<HHIIHH", 1, 2, sr, sr * 4, 4, 16)   # PCM, 2 channels, 16-bit
    return (b"RIFF" + struct.pack("<I", 36 + data) + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt
            + b"data" + struct.pack("<I", data))


class Recorder:
    """One WAV file being written from the audio the player plays."""

    def __init__(self, path: Path | str, sr: int, force: bool = False):
        path = Path(path)
        if path.suffix.lower() != ".wav":
            raise RecordError(f"{path} must end in .wav")
        if not path.parent.is_dir():
            raise RecordError(f"no such folder: {path.parent}")
        if path.exists() and not force:
            raise RecordError(f"{path} already exists (use --force)")
        try:
            self._file = open(path, "wb")   # noqa: SIM115  (closed by the writer thread)
            self._file.write(_header(sr, 0))
            self._file.flush()
        except OSError as e:
            raise RecordError(f"cannot write {path}: {e.strerror or e}") from e
        self.path, self.sr = path, sr
        self.frames = 0                                      # frames saved so far
        self._queue: queue.SimpleQueue[np.ndarray | threading.Event | None] = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._write, daemon=True, name="gentle-stream-recorder")
        self._thread.start()

    @property
    def seconds(self) -> float:
        return self.frames / self.sr

    def feed(self, block: np.ndarray) -> None:
        """Queue a copy of one (frames, 2) float block; returns at once (safe in the audio callback)."""
        self._queue.put(np.array(block, dtype=np.float32, copy=True))

    def _write_frames(self, data: bytes) -> None:
        self._file.write(data)

    def _write(self) -> None:
        while True:
            block = self._queue.get()
            if block is None:
                break
            if isinstance(block, threading.Event):   # `drain` waits for this marker
                block.set()
                continue
            pcm = np.round(np.clip(block, -1.0, 1.0) * 32767).astype("<i2")
            self._write_frames(pcm.tobytes())
            self.frames += len(block)
            end = self._file.tell()
            self._file.seek(0)
            self._file.write(_header(self.sr, self.frames))   # a valid file after every block
            self._file.seek(end)
            self._file.flush()
        self._file.close()

    def drain(self, timeout: float = 5.0) -> None:
        """Wait until every block queued so far is saved (`stop` does it too)."""
        marker = threading.Event()
        self._queue.put(marker)
        marker.wait(timeout)

    def stop(self) -> None:
        """Save what is queued and close the file."""
        self._queue.put(None)
        self._thread.join(timeout=30)
