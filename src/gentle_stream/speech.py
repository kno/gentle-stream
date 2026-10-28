"""Spoken phrases over the music (`gentle-stream ctl say TEXT`, PM-031).

A system text-to-speech program renders the phrase to a temporary WAV: `say` on macOS, else `espeak-ng` (Linux).
The text is written to its standard input, never passed as an argument, so no phrase can look like an option.
`render` runs in the caller's thread (the background player's connection thread), never in the render thread: the
engine only receives finished clips (`Engine.queue_speech`) and plays each one from the next phrase boundary (every
four bars), mixed after the master chain like the binaural layer, with the music ducked `DUCK_DB` under it. Clips are
cached by text and level-normalised; a failing program raises `SpeechError` and leaves the music as it was.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable, Iterable
from functools import lru_cache
from pathlib import Path

import numpy as np

from .synth import SR
from .voicepacks import PackError, read_wav

log = logging.getLogger(__name__)

MAX_TEXT = 200          # characters a phrase may have
TIMEOUT = 30.0          # seconds the program may take
SPEECH_RMS = 0.08       # level of a clip (the music's bus peaks near 0.9)
SPEECH_PEAK = 0.35      # and its highest sample
DUCK_DB = 3.0           # how far the music dips under a clip
RAMP = 0.05             # seconds the dip takes to ramp in and out, linear: no click
NO_BACKEND = "no text-to-speech backend found (macOS has say; on Linux install espeak-ng)"


class SpeechError(Exception):
    """A phrase that cannot be spoken; the message is meant for the terminal."""


def backend() -> tuple[str, str] | None:
    """(name, path) of the text-to-speech program to use, or None."""
    for name in ("say", "espeak-ng"):
        path = shutil.which(name)
        if path:
            return name, path
    return None


def _command(name: str, path: str, out: Path) -> list[str]:
    if name == "say":
        return [path, "-o", str(out), "--data-format=LEI16@22050"]
    return [path, "-w", str(out), "--stdin"]


def normalise(x: np.ndarray) -> np.ndarray:
    """`x` at SPEECH_RMS, scaled down further when that would put a sample above SPEECH_PEAK."""
    rms = float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0
    peak = float(np.abs(x).max()) if len(x) else 0.0
    if rms <= 1e-9 or peak <= 1e-9:
        return np.zeros(len(x))
    return x * min(SPEECH_RMS / rms, SPEECH_PEAK / peak)


@lru_cache(maxsize=64)
def render(text: str, sr: int = SR) -> np.ndarray:
    """The phrase `text` spoken as a mono clip at `sr`, normalised; raises SpeechError (nothing is cached then)."""
    text = " ".join(text.split())
    if not 1 <= len(text) <= MAX_TEXT:
        raise SpeechError(f"a phrase must have between 1 and {MAX_TEXT} characters")
    found = backend()
    if found is None:
        raise SpeechError(NO_BACKEND)
    name, path = found
    with tempfile.TemporaryDirectory(prefix="gentle-stream-say-") as tmp:
        out = Path(tmp) / "phrase.wav"
        try:
            done = subprocess.run(_command(name, path, out), input=text, capture_output=True, text=True,
                                  timeout=TIMEOUT, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise SpeechError(f"text-to-speech failed: {e}") from e
        if done.returncode != 0 or not out.is_file():
            reason = done.stderr.strip().splitlines()[-1] if done.stderr.strip() else f"{name} exited {done.returncode}"
            raise SpeechError(f"text-to-speech failed: {reason}")
        try:
            x, file_sr = read_wav(out)
        except PackError as e:
            raise SpeechError(f"text-to-speech failed: {e}") from e
    if file_sr != sr and len(x):
        x = np.interp(np.arange(int(len(x) * sr / file_sr)) * file_sr / sr, np.arange(len(x)), x)
    clip = normalise(x)
    clip.flags.writeable = False
    return clip


def prerender(texts: Iterable[str], sr: int, deliver: Callable[[str, np.ndarray], None]) -> threading.Thread:
    """Render each of `texts` in a background thread and hand every clip to `deliver(text, clip)` as soon as it is
    ready (a journey's phrases, before their stage comes). The first failure is logged once and ends the thread:
    the journey plays on without its phrases."""
    texts = tuple(texts)

    def work() -> None:
        for text in texts:
            try:
                clip = render(text, sr)
            except SpeechError as e:
                log.warning("journey phrases will not be spoken: %s", e)
                return
            deliver(text, clip)

    thread = threading.Thread(target=work, daemon=True, name="gentle-stream-phrases")
    thread.start()
    return thread


def duck_envelope(length: int, sr: int = SR) -> np.ndarray:
    """The music's gain under a clip of `length` samples: down DUCK_DB over RAMP from the clip's first sample, held,
    then back to 1 over RAMP after its last one (`length` + RAMP samples in all)."""
    ramp = max(1, int(RAMP * sr))
    total = length + ramp
    t = np.arange(total)
    depth = 1 - 10 ** (-DUCK_DB / 20)
    return 1 - depth * np.minimum(np.clip(t / ramp, 0, 1), np.clip((total - 1 - t) / ramp, 0, 1))
