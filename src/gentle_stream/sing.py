"""Sung phrases: a spoken phrase re-pitched so each syllable lands on a note of the melody.

WORLD (pyworld, the `sing` extra) splits the spoken voice into its pitch, its spectral envelope (the timbre: which
vowel, whose voice) and its aperiodicity (breath, consonants). Each voiced stretch is a syllable: it is moved to its
own note, stretched to most of the note's length (`LEGATO`), and given the note's pitch with an eased portamento from
the one before and, on long notes, vibrato; the unvoiced sound just before it (its consonant) is kept at its own
length and ends on the note's start. The timbre is never changed, so the voice stays the speaker's: only pitch and
timing move. A pitch held perfectly still sounds like a machine, so it never is: the speaker's own micro-intonation
(the syllable's pitch movement, without its overall slope) and a slow drift ride on every note, and the vibrato's rate
and depth differ from note to note and wobble within one. The randomness is seeded by the phrase and its notes: the
same phrase on the same notes is sung the same way.

`analyse` runs once per phrase and `sing` once per placement, both outside the render thread; the result is a mono clip
whose sample 0 is the origin of the notes' times, at a lead vocal's level (`SING_RMS`, the music ducked `SING_DUCK_DB`
under it by the engine).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from functools import lru_cache

import numpy as np

from . import speech
from .speech import SpeechError

INSTALL_HINT = "singing needs pyworld: pip install 'gentle-stream[sing]' (or uv sync --extra sing in a checkout)"
NOTHING_VOICED = "nothing in the phrase can be sung (no voiced sound)"
NO_NOTES = "no notes to sing"
FRAME = 0.005               # WORLD's frame period, seconds
VOICE_CENTER = 50           # the melody moves by octaves until its median is nearest D3: a male speaking voice
LEGATO = 0.92               # the share of a note a syllable lasts: a breath before the next one
PORTAMENTO = 0.09           # seconds a syllable slides from the previous note's pitch, along an eased curve
OWN_INTONATION = 0.6        # the share of the speaker's own pitch movement kept on a note
OWN_INTONATION_MAX = 20.0   # cents either way, at most (harvest's pitch is unsteady where a vowel starts and ends)
OWN_INTONATION_CORE = 0.7   # the middle share of a syllable its intonation is read from
DRIFT_CENTS = 8.0           # a slow random drift of the pitch, at most this far either way
DRIFT_STEP = 0.2            # seconds between its turning points
VIBRATO_RATE_SPREAD = 0.08  # each note's vibrato rate within this share of VIBRATO_HZ
VIBRATO_DEPTH_SPREAD = 0.25  # and its depth within this share of VIBRATO_DEPTH
VIBRATO_WOBBLE = 0.15       # both wobbling within a note by up to this share
WOBBLE_STEP = 0.15          # seconds between the wobble's turning points
VIBRATO_START = 0.25        # seconds into a note before vibrato begins
VIBRATO_RAMP = 0.3          # seconds it takes to reach its depth
VIBRATO_HZ = 5.5
VIBRATO_DEPTH = 0.3         # semitones either way
MIN_SYLLABLE = 0.03         # a voiced stretch shorter than this is not a syllable
PERIODIC = 0.5              # a frame is a vowel when its aperiodicity below PERIODIC_HZ is under this
PERIODIC_HZ = 1000.0
MIN_KEEP = 0.5              # a syllable gives up at most half its length to make room for the next consonant
SYLLABLE_GAP = 0.02         # voiced stretches closer than this are one syllable
MAX_CONSONANT = 0.2         # the longest unvoiced sound kept before (or after) a syllable
CONSONANT_LEVEL = 0.05      # a frame louder than this share of the loudest one is sound, not silence
GATE_RAMP = 0.005           # seconds of fade in and out of the silence between syllables
SING_RMS = 0.14             # a lead vocal: above a spoken phrase (speech.SPEECH_RMS)
SING_PEAK = 0.6
SING_DUCK_DB = 6.0          # how far the music dips under a sung phrase
ANALYSIS_SR = 16000         # the rate a phrase is analysed and sung at (Piper's carlfm speaks at 16 kHz)
BARS_AHEAD = 4              # the bars of melody a phrase may be sung over


@dataclass(frozen=True)
class Note:
    start: float            # seconds from the clip's origin
    length: float           # seconds
    midi: int


@dataclass(frozen=True)
class Voice:
    """WORLD's analysis of a spoken phrase, and where its syllables and sounds are (frame indices)."""
    sr: int
    f0: np.ndarray
    sp: np.ndarray
    ap: np.ndarray
    syllables: tuple[tuple[int, int], ...]
    loud: np.ndarray        # per frame: sound (True) or silence


def available() -> bool:
    try:
        import pyworld  # noqa: F401
    except ImportError:
        return False
    return True


def _pyworld():
    try:
        import pyworld
    except ImportError as e:
        raise SpeechError(INSTALL_HINT) from e
    return pyworld


def analyse(x: np.ndarray, sr: int) -> Voice:
    """The phrase `x` (mono, at `sr`) as WORLD sees it; raises SpeechError without pyworld."""
    pw = _pyworld()
    x = np.ascontiguousarray(x, dtype=np.float64)
    f0, t = pw.harvest(x, sr, f0_floor=60, f0_ceil=500, frame_period=FRAME * 1000)
    sp = pw.cheaptrick(x, f0, t, sr)
    ap = pw.d4c(x, f0, t, sr)
    hop = sr * FRAME
    rms = np.array([np.sqrt(np.mean(np.square(x[max(0, int((i - 0.5) * hop)):int((i + 0.5) * hop) + 1])))
                    for i in range(len(f0))])
    loud = rms > CONSONANT_LEVEL * (rms.max() if len(rms) else 1.0)
    low = max(2, int(PERIODIC_HZ / (sr / 2) * (ap.shape[1] - 1)))
    periodic = (f0 > 0) & (ap[:, 1:low].mean(axis=1) < PERIODIC)   # harvest also calls a consonant's noise voiced
    return Voice(sr, f0, sp, ap, _syllables(periodic), loud)


def _syllables(periodic: np.ndarray) -> tuple[tuple[int, int], ...]:
    gap, shortest = round(SYLLABLE_GAP / FRAME), round(MIN_SYLLABLE / FRAME)
    runs: list[tuple[int, int]] = []
    i = 0
    while i < len(periodic):
        if periodic[i]:
            j = i
            while j < len(periodic) and periodic[j]:
                j += 1
            if runs and i - runs[-1][1] <= gap:
                runs[-1] = (runs[-1][0], j)
            else:
                runs.append((i, j))
            i = j
        else:
            i += 1
    return tuple(r for r in runs if r[1] - r[0] >= shortest)


def transpose(notes: Sequence[Note]) -> tuple[Note, ...]:
    """`notes` moved by whole octaves so their median pitch is nearest VOICE_CENTER."""
    if not notes:
        return tuple(notes)
    shift = 12 * round((VOICE_CENTER - float(np.median([n.midi for n in notes]))) / 12)
    return tuple(replace(n, midi=n.midi + shift) for n in notes)


@lru_cache(maxsize=32)
def voice_for(text: str, voice: str | None, rate: int | None) -> Voice:
    """The phrase spoken by the text-to-speech program in use, analysed (the slow part, done once per phrase)."""
    if not available():
        raise SpeechError(INSTALL_HINT)
    return analyse(np.asarray(speech._speak(text, ANALYSIS_SR, voice, rate), dtype=float), ANALYSIS_SR)


def sung_clip(voice: Voice, notes: Sequence[Note], sr: int, effect: str = "dry") -> np.ndarray:
    """The phrase sung on `notes` at `sr` through `effect`, at a lead vocal's level; sample 0 is the notes' origin."""
    y = sing(voice, notes)
    if voice.sr != sr and len(y):
        y = np.interp(np.arange(int(len(y) * sr / voice.sr)) * voice.sr / sr, np.arange(len(y)), y)
    clip = _level(speech._effect(y, effect, sr))
    clip.flags.writeable = False
    return clip


def _slow_noise(rng: np.random.Generator, n: int, step: int) -> np.ndarray:
    """`n` frames of slow random motion in [-1, 1]: a random point every `step` frames, cosine-interpolated."""
    points = rng.uniform(-1, 1, n // step + 2)
    x = np.arange(n) / step
    i = x.astype(int)
    w = (1 - np.cos(np.pi * (x - i))) / 2
    return points[i] * (1 - w) + points[i + 1] * w


def _own_intonation(voice: Voice, a: int, b: int, n: int) -> np.ndarray:
    """The syllable's own pitch movement in cents, read from its middle (OWN_INTONATION_CORE), median-smoothed,
    without its overall slope, scaled by OWN_INTONATION, kept within OWN_INTONATION_MAX and stretched to `n` frames."""
    from scipy.ndimage import median_filter

    trim = round((b - a) * (1 - OWN_INTONATION_CORE) / 2)
    src = voice.f0[a + trim:b - trim]
    if len(src) < 5 or np.any(src <= 0):
        return np.zeros(n)
    cents = median_filter(1200 * np.log2(src / np.median(src)), size=5, mode="nearest")   # zero padding would bend the ends
    x = np.arange(len(cents))
    cents = cents - np.polyval(np.polyfit(x, cents, 1), x)
    cents = np.clip(OWN_INTONATION * cents, -OWN_INTONATION_MAX, OWN_INTONATION_MAX)
    return np.interp(np.linspace(0, len(cents) - 1, n), x, cents)


def _vibrato(rng: np.random.Generator, n: int) -> np.ndarray:
    """`n` frames of one note's vibrato in semitones: none for VIBRATO_START, then growing over VIBRATO_RAMP to its
    depth; its rate and depth drawn for this note (VIBRATO_RATE_SPREAD, VIBRATO_DEPTH_SPREAD), both wobbling within
    it (VIBRATO_WOBBLE)."""
    fps = 1 / FRAME
    rate = VIBRATO_HZ * (1 + VIBRATO_RATE_SPREAD * rng.uniform(-1, 1))
    depth = VIBRATO_DEPTH * (1 + VIBRATO_DEPTH_SPREAD * rng.uniform(-1, 1))
    wobble = VIBRATO_WOBBLE * _slow_noise(rng, n, round(WOBBLE_STEP * fps))
    t = np.arange(n) / fps
    phase = np.cumsum(2 * np.pi * rate * (1 + 0.5 * wobble) / fps)
    grow = np.clip((t - VIBRATO_START) / VIBRATO_RAMP, 0, 1)          # 0 until VIBRATO_START
    return grow * depth * (1 + wobble) * np.sin(phase)


def _hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _consonant(voice: Voice, first: int, end: int) -> range:
    """The sound just before frame `end` (after `first`): the trailing run of loud frames, at most MAX_CONSONANT."""
    start = end
    while start > first and voice.loud[start - 1] and end - start < MAX_CONSONANT / FRAME:
        start -= 1
    return range(start, end)


def sing(voice: Voice, notes: Sequence[Note], vibrato: bool = True) -> np.ndarray:
    """The phrase sung on `notes` (in order; a note too early for its syllable's consonant is skipped, syllables
    past the last note follow it on its pitch): a mono clip at `voice.sr` whose sample 0 is the notes' origin."""
    pw = _pyworld()
    if not voice.syllables:
        raise SpeechError(NOTHING_VOICED)
    pending = sorted(notes, key=lambda n: n.start)
    if not pending:
        raise SpeechError(NO_NOTES)
    fps = 1 / FRAME
    rng = np.random.default_rng([len(voice.syllables), len(pending), *(n.midi for n in pending),
                                 *(round(1000 * n.start) for n in pending)])
    frames: list[tuple[float | None, float]] = []      # (source frame, or None for silence; f0, 0 unvoiced)
    prev_end, prev_hz, last = 0, None, None
    prev_start = 0                                     # where the previous syllable's vowel begins in `frames`
    for a, b in voice.syllables:
        consonant = _consonant(voice, prev_end, a)
        earliest = prev_start + round((len(frames) - prev_start) * MIN_KEEP) if prev_hz is not None else 0
        while pending and round(pending[0].start * fps) < earliest + len(consonant):
            pending.pop(0)                             # too early: no room for its consonant
        if pending:
            last = pending.pop(0)
            start = round(last.start * fps)
        elif last is not None:
            start = len(frames) + len(consonant)       # past the last note: right after, on its pitch
        else:
            raise SpeechError(NO_NOTES)
        target = _hz(last.midi)
        del frames[max(earliest, start - len(consonant)):]   # the previous vowel's tail makes room, if it must
        frames += [(None, 0.0)] * (start - len(consonant) - len(frames))
        frames += [(float(k), 0.0) for k in consonant]
        prev_start = len(frames)
        n = max(4, round(last.length * LEGATO * fps))
        cents = _own_intonation(voice, a, b, n) + DRIFT_CENTS * _slow_noise(rng, n, round(DRIFT_STEP * fps))
        if vibrato:
            cents = cents + 100 * _vibrato(rng, n)
        for j in range(n):
            t = j / fps
            f = target
            if prev_hz is not None and t < PORTAMENTO:
                f = prev_hz * (target / prev_hz) ** ((1 - np.cos(np.pi * t / PORTAMENTO)) / 2)
            frames.append((a + (b - a - 1) * j / max(1, n - 1), f * 2 ** (cents[j] / 1200)))
        prev_end, prev_hz = b, target
    tail = range(prev_end, prev_end)
    while tail.stop < len(voice.f0) and voice.loud[tail.stop] and voice.f0[tail.stop] <= 0 \
            and len(tail) < MAX_CONSONANT / FRAME:
        tail = range(prev_end, tail.stop + 1)          # a final consonant ("s") after the last syllable
    frames += [(float(k), 0.0) for k in tail]
    return _level(_synthesize(pw, voice, frames))


def _row(m: np.ndarray, k: float) -> np.ndarray:
    i = int(k)
    j = min(i + 1, len(m) - 1)
    return m[i] * (1 - (k - i)) + m[j] * (k - i)


def _synthesize(pw, voice: Voice, frames: list[tuple[float | None, float]]) -> np.ndarray:
    quiet_sp = voice.sp.min(axis=0)
    f0 = np.array([f for _, f in frames])
    sp = np.stack([quiet_sp if k is None else _row(voice.sp, k) for k, _ in frames])
    ap = np.stack([np.ones(voice.ap.shape[1]) if k is None else _row(voice.ap, k) for k, _ in frames])
    y = pw.synthesize(np.ascontiguousarray(f0), np.ascontiguousarray(sp), np.ascontiguousarray(ap), voice.sr,
                      FRAME * 1000)
    gate = np.array([0.0 if k is None else 1.0 for k, _ in frames])
    t = np.arange(len(y)) / voice.sr
    centres = (np.arange(len(frames)) + 0.5) * FRAME                 # frame i spans [i, i + 1) frames of time
    mask = np.interp(t, centres, gate)
    ramp = max(1, round(GATE_RAMP * voice.sr))
    mask = np.convolve(np.round(mask), np.ones(ramp) / ramp, mode="same")
    return y * mask


def _level(y: np.ndarray) -> np.ndarray:
    """At SING_RMS over what sounds, scaled down further when a sample would pass SING_PEAK."""
    sounding = y[np.abs(y) > 0]
    rms = float(np.sqrt(np.mean(np.square(sounding)))) if len(sounding) else 0.0
    peak = float(np.abs(y).max()) if len(y) else 0.0
    if rms <= 1e-9 or peak <= 1e-9:
        return np.zeros(len(y))
    return y * min(SING_RMS / rms, SING_PEAK / peak)
