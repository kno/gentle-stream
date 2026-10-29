"""Spoken phrases over the music (`gentle-stream ctl say TEXT`, PM-031).

A system text-to-speech program renders the phrase to a temporary WAV: `say` on macOS, else `espeak-ng` (Linux).
The text is written to its standard input, never passed as an argument, so no phrase can look like an option.
`render` runs in the caller's thread (the background player's connection thread), never in the render thread: the
engine only receives finished clips (`Engine.queue_speech`) and plays each one from the next phrase boundary (every
four bars), mixed after the master chain like the binaural layer, with the music ducked `DUCK_DB` under it. Clips are
cached by text and level-normalised; a failing program raises `SpeechError` and leaves the music as it was.

A phrase can ask for a system voice (`voices` lists them; an unknown one falls back to the default voice with a
warning, `resolve_voice`), a rate in words per minute, and an effect: `dry`, `radio` (the telephone band, slightly
saturated) or `space` (the procedural room impulse the master chain's reverb uses, here as a send on the voice).
"""
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import tempfile
import threading
import warnings
from collections.abc import Callable, Iterable
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.io.wavfile import WavFileWarning

from .mastering import procedural_ir
from .synth import SR, bp
from .voicepacks import PackError, read_wav

log = logging.getLogger(__name__)

MAX_TEXT = 200          # characters a phrase may have
TIMEOUT = 30.0          # seconds the program may take
SPEECH_RMS = 0.08       # level of a clip (the music's bus peaks near 0.9)
SPEECH_PEAK = 0.35      # and its highest sample
DUCK_DB = 3.0           # how far the music dips under a clip
RAMP = 0.05             # seconds the dip takes to ramp in and out, linear: no click
RATES = (80, 400)       # words per minute a phrase may ask for
EFFECTS = ("dry", "radio", "space")
SPACE = 0.7             # room size of the `space` effect (as `Style.space`) and its send level
SPACE_SEND = 0.6
IR_SEED = 7
NO_BACKEND = "no text-to-speech backend found (macOS has say; on Linux install espeak-ng)"
BROADCAST_NEEDS = ("while broadcasting, phrases are spoken with {name} (macOS voices are licensed for personal use "
                   "only), and {name} is not installed")


class SpeechError(Exception):
    """A phrase that cannot be spoken; the message is meant for the terminal."""


_ONLY: str | None = None   # while broadcasting: the one program whose voices may be broadcast


def use_only(name: str | None) -> None:
    """Speak only with `name` (a broadcast: macOS voices are licensed for personal use, espeak-ng's may be
    broadcast), or with the usual choice again for None; phrases rendered before are forgotten."""
    global _ONLY
    _ONLY = name
    clear_cache()


def backend() -> tuple[str, str] | None:
    """(name, path) of the text-to-speech program to use, or None."""
    for name in (_ONLY,) if _ONLY else ("say", "espeak-ng"):
        path = shutil.which(name)
        if path:
            return name, path
    return None


def _command(name: str, path: str, out: Path, voice: str | None = None, rate: int | None = None) -> list[str]:
    """The program's command line: each option its own argument, the text never on it (it goes to stdin)."""
    if name == "say":
        cmd = [path, "-o", str(out), "--data-format=LEI16@22050"]
        cmd += ["-v", voice] if voice else []
        cmd += ["-r", str(rate)] if rate is not None else []
        return cmd
    cmd = [path, "-w", str(out)]
    cmd += ["-v", voice] if voice else []
    cmd += ["-s", str(rate)] if rate is not None else []
    return [*cmd, "--stdin"]


def voices() -> list[tuple[str, str]]:
    """The system voices as (name, language) for `say`, (language, name) for `espeak-ng` (whose `-v` takes the
    language code); raises SpeechError without a program."""
    found = backend()
    if found is None:
        raise SpeechError(NO_BACKEND)
    name, path = found
    args = [path, "-v", "?"] if name == "say" else [path, "--voices"]
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise SpeechError(f"cannot list voices: {e}") from e
    out = []
    for line in done.stdout.splitlines():
        if name == "say":
            m = re.match(r"^(.+?)\s{2,}(\S+)\s+#", line)
            if m:
                out.append((m.group(1).strip(), m.group(2)))
        else:
            parts = line.split()
            if len(parts) >= 4 and parts[0].isdigit():
                out.append((parts[1], parts[3]))
    return out


def resolve_voice(voice: str | None) -> tuple[str | None, str | None]:
    """(the system's name for `voice`, None), matched without case, or (None, a warning) for an unknown one: the
    phrase is then spoken in the default voice."""
    if not voice:
        return None, None
    try:
        known = voices()
    except SpeechError:
        known = []
    for first, second in known:
        if voice.casefold() in (first.casefold(), second.casefold()):
            return first, None
    return None, f'unknown voice "{voice}"; using the default voice (see gentle-stream ctl say --list-voices)'


def read_clip(path: Path) -> tuple[np.ndarray, int]:
    """The program's WAV as mono float and its rate, without scipy's warning about chunks it skips (`say` adds one
    to every file; it would fill the player's log)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", WavFileWarning)
        return read_wav(path)


def normalise(x: np.ndarray) -> np.ndarray:
    """`x` at SPEECH_RMS, scaled down further when that would put a sample above SPEECH_PEAK."""
    rms = float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0
    peak = float(np.abs(x).max()) if len(x) else 0.0
    if rms <= 1e-9 or peak <= 1e-9:
        return np.zeros(len(x))
    return x * min(SPEECH_RMS / rms, SPEECH_PEAK / peak)


def _effect(x: np.ndarray, effect: str, sr: int) -> np.ndarray:
    if effect == "radio":
        band = np.asarray(bp(np.asarray(bp(x, 300, 3400, sr)), 300, 3400, sr))
        peak = float(np.abs(band).max()) or 1.0
        return np.tanh(2 * band / peak) / np.tanh(2)
    if effect == "space":
        from scipy.signal import fftconvolve
        ir = procedural_ir(SPACE, sr, IR_SEED)[:, 0]   # one channel: the voice stays centred
        wet = fftconvolve(x, ir)
        return np.r_[x, np.zeros(len(wet) - len(x))] + SPACE_SEND * wet
    return x


@lru_cache(maxsize=64)
def render(text: str, sr: int = SR, voice: str | None = None, rate: int | None = None,
           effect: str = "dry") -> np.ndarray:
    """The phrase `text` spoken as a mono clip at `sr` in `voice` at `rate` words per minute (the program's defaults
    when None) through `effect`, normalised; raises SpeechError (nothing is cached then). Pass a voice through
    `resolve_voice` first: an unknown one makes the program fail."""
    text = " ".join(text.split())
    if not 1 <= len(text) <= MAX_TEXT:
        raise SpeechError(f"a phrase must have between 1 and {MAX_TEXT} characters")
    if effect not in EFFECTS:
        raise SpeechError(f"effect must be one of {', '.join(EFFECTS)}")
    if rate is not None and not RATES[0] <= rate <= RATES[1]:
        raise SpeechError(f"rate must be {RATES[0]} to {RATES[1]} words per minute")
    clip = normalise(_effect(_speak(text, sr, voice, rate), effect, sr))
    clip.flags.writeable = False
    return clip


@lru_cache(maxsize=64)
def _speak(text: str, sr: int, voice: str | None, rate: int | None) -> np.ndarray:
    """The program's output for the phrase, at `sr`, before any effect or normalisation."""
    found = backend()
    if found is None:
        raise SpeechError(BROADCAST_NEEDS.format(name=_ONLY) if _ONLY else NO_BACKEND)
    name, path = found
    with tempfile.TemporaryDirectory(prefix="gentle-stream-say-") as tmp:
        out = Path(tmp) / "phrase.wav"
        try:
            done = subprocess.run(_command(name, path, out, voice, rate), input=text, capture_output=True, text=True,
                                  timeout=TIMEOUT, check=False)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise SpeechError(f"text-to-speech failed: {e}") from e
        if done.returncode != 0 or not out.is_file():
            reason = done.stderr.strip().splitlines()[-1] if done.stderr.strip() else f"{name} exited {done.returncode}"
            raise SpeechError(f"text-to-speech failed: {reason}")
        try:
            x, file_sr = read_clip(out)
        except PackError as e:
            raise SpeechError(f"text-to-speech failed: {e}") from e
    if file_sr != sr and len(x):
        x = np.interp(np.arange(int(len(x) * sr / file_sr)) * file_sr / sr, np.arange(len(x)), x)
    x.flags.writeable = False
    return x


def clear_cache() -> None:
    """Forget every rendered phrase (tests, or after installing another voice)."""
    render.cache_clear()
    _speak.cache_clear()


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
