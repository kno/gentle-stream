"""Spoken phrases over the music (`gentle-stream ctl say TEXT`, PM-031).

A text-to-speech program renders the phrase to a temporary WAV: Piper with a voice `setup-speech` installed
(`speechsetup`), else `say` on macOS, else `espeak-ng` (Linux); while broadcasting only Piper or espeak-ng, whose
voices may be broadcast (`use_only`). The text is written to the program's standard input, never passed as an
argument, so no phrase can look like an option. Piper loads its model in seconds and then speaks a phrase in a
fraction of one, so one Piper process per model and rate stays open (`_Piper`): a line of text on its standard input,
one WAV in its private folder, announced on its standard error once written.
`render` runs in the caller's thread (the background player's connection thread), never in the render thread: the
engine only receives finished clips (`Engine.queue_speech`) and plays each one from the next bar (a journey's phrases
from the next phrase boundary, every four bars), mixed after the master chain like the binaural layer, with the
music ducked `DUCK_DB` under it. Clips are cached by text and level-normalised; a failing program raises
`SpeechError` and leaves the music as it was.

A phrase can ask for a system voice (`voices` lists them; an unknown one falls back to the default voice with a
warning, `resolve_voice`), a rate in words per minute, and an effect: `dry`, `radio` (the telephone band, slightly
saturated) or `space` (the procedural room impulse the master chain's reverb uses, here as a send on the voice).
"""
from __future__ import annotations

import atexit
import contextlib
import logging
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
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
BROADCAST_SAFE = ("piper", "espeak-ng")    # the programs whose voices may be broadcast
BROADCAST_NEEDS = ("while broadcasting, phrases are spoken with Piper (gentle-stream setup-speech) or espeak-ng "
                   "(macOS voices are licensed for personal use only), and neither is installed")
PIPER_WPM = 175         # the rate Piper's length scale 1.0 stands for (say's and espeak-ng's default too)
PIPER_WROTE = re.compile(r"Wrote (.+\.wav)\s*$")   # Piper 1.8's log line once a phrase's WAV is complete
MAX_PIPERS = 3          # open Piper processes (one per model and rate); the least recently used one is closed
PIPER_STOP = 5.0        # seconds a closing Piper may take to exit before it is killed


class SpeechError(Exception):
    """A phrase that cannot be spoken; the message is meant for the terminal."""


_ONLY: tuple[str, ...] | None = None   # while broadcasting: the programs whose voices may be broadcast


def use_only(names: tuple[str, ...] | None) -> None:
    """Speak only with the first of `names` found (a broadcast: macOS voices are licensed for personal use,
    BROADCAST_SAFE's may be broadcast), or with the usual choice again for None; phrases rendered before are
    forgotten."""
    global _ONLY
    _ONLY = names
    clear_cache()


def _which(name: str) -> str | None:
    """The program's path; Piper's only with a voice installed for it."""
    if name == "piper":
        from . import speechsetup

        return speechsetup.program() if speechsetup.installed() else None
    return shutil.which(name)


def can_broadcast() -> bool:
    """Whether a program whose voices may be broadcast (BROADCAST_SAFE) is there to speak phrases."""
    return any(_which(name) for name in BROADCAST_SAFE)


def backend() -> tuple[str, str] | None:
    """(name, path) of the text-to-speech program to use, or None."""
    for name in _ONLY if _ONLY else ("piper", "say", "espeak-ng"):
        path = _which(name)
        if path:
            return name, path
    return None


def _piper_model(voice: str | None) -> Path:
    """The installed Piper model for `voice` (a name `voices` lists), or the first one."""
    from . import speechsetup

    models = speechsetup.installed()
    return models.get(voice or "", next(iter(models.values())))


def _piper_command(path: str, voice: str | None, rate: int | None) -> tuple[str, ...]:
    """Piper's command line for a model and a rate, without its output folder: also the key of its open process."""
    cmd = [path, "-m", str(_piper_model(voice))]
    cmd += ["--length-scale", str(round(PIPER_WPM / rate, 3))] if rate is not None else []
    return tuple(cmd)


class _Piper:
    """One Piper process kept open with its model loaded. `speak` writes a line of text to its stdin and waits for
    the log line naming the finished WAV; callers hold `lock`, so phrases never interleave."""

    def __init__(self, cmd: tuple[str, ...]):
        self.folder = Path(tempfile.mkdtemp(prefix="gentle-stream-piper-"))
        self.lock = threading.Lock()
        self.lines: queue.Queue[str | None] = queue.Queue()
        try:
            self.proc = subprocess.Popen([*cmd, "-d", str(self.folder)], stdin=subprocess.PIPE,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, bufsize=1)
        except OSError as e:
            shutil.rmtree(self.folder, ignore_errors=True)
            raise SpeechError(f"text-to-speech failed: {e}") from e
        threading.Thread(target=self._read, daemon=True, name="gentle-stream-piper-log").start()

    def _read(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.lines.put(line)
        self.lines.put(None)                      # Piper exited

    def alive(self) -> bool:
        return self.proc.poll() is None

    def speak(self, text: str) -> Path:
        """The WAV of `text` (one line); raises SpeechError when Piper exits or takes more than TIMEOUT."""
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.write(text + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError):
            pass                                  # it exited: its exit code is in the log's end, below
        deadline, last = time.monotonic() + TIMEOUT, ""
        while True:
            try:
                line = self.lines.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                raise SpeechError(f"text-to-speech failed: piper took more than {TIMEOUT:g} s") from None
            if line is None:
                reason = f"piper exited {self.proc.wait()}" + (f": {last}" if last else "")
                raise SpeechError(f"text-to-speech failed: {reason}")
            if found := PIPER_WROTE.search(line):
                return Path(found.group(1))
            last = line.strip() or last

    def close(self) -> None:
        if self.proc.stdin is not None:
            with contextlib.suppress(OSError):
                self.proc.stdin.close()               # Piper ends at the end of its input
        try:
            self.proc.wait(PIPER_STOP)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        shutil.rmtree(self.folder, ignore_errors=True)


_PIPERS: dict[tuple[str, ...], _Piper] = {}
_PIPERS_LOCK = threading.Lock()


def _open_piper(cmd: tuple[str, ...]) -> _Piper:
    """The open Piper for `cmd`, started when there is none (or it exited)."""
    with _PIPERS_LOCK:
        piper = _PIPERS.pop(cmd, None)
        if piper is None or not piper.alive():
            if piper is not None:
                piper.close()
            piper = _Piper(cmd)
        _PIPERS[cmd] = piper                      # the most recently used last
        while len(_PIPERS) > MAX_PIPERS:
            _PIPERS.pop(next(iter(_PIPERS))).close()
        return piper


def _piper_speak(path: str, text: str, voice: str | None, rate: int | None) -> tuple[np.ndarray, int]:
    cmd = _piper_command(path, voice, rate)
    piper = _open_piper(cmd)
    with piper.lock:
        try:
            wav = piper.speak(text)
        except SpeechError:
            with _PIPERS_LOCK:
                if _PIPERS.get(cmd) is piper:
                    del _PIPERS[cmd]
            piper.close()                         # a Piper that failed is never used again
            raise
    try:
        return read_clip(wav)
    except PackError as e:
        raise SpeechError(f"text-to-speech failed: {e}") from e
    finally:
        wav.unlink(missing_ok=True)


def warm_up() -> None:
    """Start Piper with its default voice before the first phrase, when Piper is the program in use (the player
    does this as it starts: loading the model is what takes time)."""
    found = backend()
    if found is not None and found[0] == "piper":
        try:
            _open_piper(_piper_command(found[1], None, None))
        except SpeechError as e:
            log.warning("cannot start Piper: %s", e)


def close_piper() -> None:
    """End every open Piper (at exit, and in tests)."""
    with _PIPERS_LOCK:
        pipers = list(_PIPERS.values())
        _PIPERS.clear()
    for piper in pipers:
        piper.close()


atexit.register(close_piper)


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
    """The voices as (name, language) for Piper and `say`, (language, name) for `espeak-ng` (whose `-v` takes the
    language code); raises SpeechError without a program."""
    found = backend()
    if found is None:
        raise SpeechError(NO_BACKEND)
    name, path = found
    if name == "piper":
        from . import speechsetup

        return [(key, speechsetup.CATALOG[key].language) for key in speechsetup.installed()]
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


def checked(text: str, rate: int | None, effect: str) -> str:
    """`text` with its whitespace collapsed; SpeechError for a phrase, rate or effect out of bounds."""
    text = " ".join(text.split())
    if not 1 <= len(text) <= MAX_TEXT:
        raise SpeechError(f"a phrase must have between 1 and {MAX_TEXT} characters")
    if effect not in EFFECTS:
        raise SpeechError(f"effect must be one of {', '.join(EFFECTS)}")
    if rate is not None and not RATES[0] <= rate <= RATES[1]:
        raise SpeechError(f"rate must be {RATES[0]} to {RATES[1]} words per minute")
    return text


@lru_cache(maxsize=64)
def render(text: str, sr: int = SR, voice: str | None = None, rate: int | None = None,
           effect: str = "dry") -> np.ndarray:
    """The phrase `text` spoken as a mono clip at `sr` in `voice` at `rate` words per minute (the program's defaults
    when None) through `effect`, normalised; raises SpeechError (nothing is cached then). Pass a voice through
    `resolve_voice` first: an unknown one makes the program fail."""
    text = checked(text, rate, effect)
    clip = normalise(_effect(_speak(text, sr, voice, rate), effect, sr))
    clip.flags.writeable = False
    return clip


@lru_cache(maxsize=64)
def _speak(text: str, sr: int, voice: str | None, rate: int | None) -> np.ndarray:
    """The program's output for the phrase, at `sr`, before any effect or normalisation."""
    found = backend()
    if found is None:
        raise SpeechError(BROADCAST_NEEDS if _ONLY else NO_BACKEND)
    name, path = found
    if name == "piper":
        x, file_sr = _piper_speak(path, text, voice, rate)
        return _at_rate(x, file_sr, sr)
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
    return _at_rate(x, file_sr, sr)


def _at_rate(x: np.ndarray, file_sr: int, sr: int) -> np.ndarray:
    if file_sr != sr and len(x):
        x = np.interp(np.arange(int(len(x) * sr / file_sr)) * file_sr / sr, np.arange(len(x)), x)
    x.flags.writeable = False
    return x


def clear_cache() -> None:
    """Forget every rendered phrase, spoken or analysed for singing (tests, after installing another voice, and when a
    broadcast starts or stops: what was rendered with one program is never reused with another)."""
    from . import sing

    render.cache_clear()
    _speak.cache_clear()
    sing.voice_for.cache_clear()


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


def duck_envelope(length: int, sr: int = SR, db: float = DUCK_DB) -> np.ndarray:
    """The music's gain under a clip of `length` samples: down `db` over RAMP from the clip's first sample, held,
    then back to 1 over RAMP after its last one (`length` + RAMP samples in all)."""
    ramp = max(1, int(RAMP * sr))
    total = length + ramp
    t = np.arange(total)
    depth = 1 - 10 ** (-db / 20)
    return 1 - depth * np.minimum(np.clip(t / ramp, 0, 1), np.clip((total - 1 - t) / ramp, 0, 1))
