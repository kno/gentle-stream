"""An optional binaural layer: a quiet sine on each ear, the left one `beat/2` below the carrier and the right one
`beat/2` above it, offered only as a listening texture (no effect on the listener is claimed).

The engine adds it after the master chain, so no reverb, wow, tone filter or compressor touches it; the master never
exceeds 0.9 and the layer at most `MAX_LEVEL`, so their sum stays below 1.0. Two phase accumulators persist across
bars and settings. A new setting glides sample by sample: the frequencies, not the phases, are interpolated, so the
tones never jump. Turning the layer on fades it in from silence over `FADE_SECONDS`; turning it off fades it out.

`Player.next` crossfades the pending audio with a new bar rendered up to a second later on the timeline, so for the
80 ms crossfade two copies of the layer with different phases overlap: a brief, smooth dip in its level, no click.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

CARRIER = (40.0, 1000.0)   # Hz
BEAT = (0.5, 40.0)         # Hz, the difference between the two ears
MAX_LEVEL = 0.08           # linear amplitude of each sine
DEFAULT_CARRIER, DEFAULT_BEAT, DEFAULT_LEVEL = 200.0, 6.0, 0.05
FADE_SECONDS = 2.0         # fade in when turned on, fade out when turned off
MAX_GLIDE_SECONDS = 3600.0
FIELDS = ("carrier", "beat", "level")


def _checked(name: str, value, low: float, high: float, unit: str = "") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    if not low <= value <= high:   # also rejects NaN
        raise ValueError(f"{name} must be between {low:g} and {high:g}{unit}")
    return float(value)


@dataclass(frozen=True)
class Binaural:
    """One binaural setting; out-of-range or non-numeric values raise ValueError."""
    carrier: float = DEFAULT_CARRIER
    beat: float = DEFAULT_BEAT
    level: float = DEFAULT_LEVEL

    def __post_init__(self) -> None:
        object.__setattr__(self, "carrier", _checked("carrier", self.carrier, *CARRIER, " Hz"))
        object.__setattr__(self, "beat", _checked("beat", self.beat, *BEAT, " Hz"))
        object.__setattr__(self, "level", _checked("level", self.level, 0.0, MAX_LEVEL))

    @property
    def frequencies(self) -> tuple[float, float]:
        """(left, right) in Hz."""
        return self.carrier - self.beat / 2, self.carrier + self.beat / 2

    def to_dict(self) -> dict[str, float]:
        return {"carrier": self.carrier, "beat": self.beat, "level": self.level}

    @classmethod
    def from_dict(cls, data) -> Binaural:
        """A setting from `to_dict` output; missing values take the defaults."""
        return cls(data.get("carrier", DEFAULT_CARRIER), data.get("beat", DEFAULT_BEAT),
                   data.get("level", DEFAULT_LEVEL))


def glide_seconds(seconds) -> float:
    """`seconds` as a glide duration, or ValueError outside 0-3600."""
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 <= seconds <= MAX_GLIDE_SECONDS:
        raise ValueError(f"seconds must be between 0 and {MAX_GLIDE_SECONDS:g}")
    return float(seconds)


@dataclass
class _Ramp:
    """A value moving linearly from `source` to `target` over `length` samples, `done` of them rendered."""
    source: float
    target: float
    length: int = 0
    done: int = 0

    @property
    def value(self) -> float:
        """Where it is now."""
        if self.done >= self.length:
            return self.target
        return self.source + (self.target - self.source) * self.done / self.length

    def to(self, target: float, length: int) -> None:
        """Glide from where it is to `target` over `length` samples (0: at once)."""
        self.source, self.target, self.length, self.done = self.value, target, length, 0

    def render(self, n: int) -> np.ndarray:
        """Its value at each of the next `n` samples."""
        if self.done >= self.length:
            values = np.full(n, self.target)
        else:
            k = np.minimum(self.done + np.arange(n), self.length)
            values = self.source + (self.target - self.source) * k / self.length
        self.done += n
        return values


class BinauralLayer:
    """Renders the layer bar by bar; render thread only. `setting` is where it is heading (None once turned off,
    while it still fades out); `active` is whether it still makes sound."""

    def __init__(self, sr: int):
        self.sr = sr
        self.setting: Binaural | None = None
        self.active = False
        self._phase = np.zeros(2)   # radians at the start of the next bar, left and right
        self._ramps = {name: _Ramp(0.0, 0.0) for name in FIELDS}

    def set(self, setting: Binaural | None, seconds: float = 0.0) -> None:
        """Head for `setting` from the next sample, gliding over `seconds`; None fades out and then stops. A silent
        layer starts at the new frequencies and fades in; a layer still fading out comes back from its level."""
        fade = round(FADE_SECONDS * self.sr)
        glide = round(seconds * self.sr)
        ramps = self._ramps
        if setting is None:
            if self.active:
                ramps["level"].to(0.0, fade)
        elif not self.active:
            self._phase = np.zeros(2)
            ramps["carrier"].to(setting.carrier, 0)
            ramps["beat"].to(setting.beat, 0)
            ramps["level"].to(0.0, 0)
            ramps["level"].to(setting.level, fade)
            self.active = True
        else:
            ramps["carrier"].to(setting.carrier, glide)
            ramps["beat"].to(setting.beat, glide)
            ramps["level"].to(setting.level, glide if self.setting is not None else max(glide, fade))
        self.setting = setting

    def render(self, n: int) -> np.ndarray:
        """The next `n` samples of the layer, shape (n, 2); call only while `active`."""
        assert self.active
        carrier, beat, level = (self._ramps[name].render(n) for name in FIELDS)
        hz = np.stack([carrier - beat / 2, carrier + beat / 2], 1)
        step = 2 * math.pi * hz / self.sr
        phase = self._phase + np.cumsum(step, axis=0) - step   # each sample at the phase before its own step
        self._phase = (phase[-1] + step[-1]) % (2 * math.pi)
        out = np.sin(phase) * level[:, None]
        if self.setting is None and self._ramps["level"].value == 0.0:   # faded out
            self.active = False
        return out
