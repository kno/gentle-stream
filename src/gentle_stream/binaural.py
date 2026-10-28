"""An optional binaural layer: a quiet sine on each ear, the left one `beat/2` below the carrier and the right one
`beat/2` above it, offered only as a listening texture (no effect on the listener is claimed).

The engine adds it after the master chain, so no reverb, wow, tone filter or compressor touches it; the master never
exceeds 0.9 and the layer at most `MAX_LEVEL`, so their sum stays below 1.0. Two phase accumulators persist across
bars and settings, so a bar boundary or a new setting never jumps; turning the layer on starts both sines at zero.

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


class BinauralLayer:
    """Renders the layer bar by bar; render thread only."""

    def __init__(self, sr: int):
        self.sr = sr
        self.setting: Binaural | None = None
        self._phase = np.zeros(2)   # radians at the start of the next bar, left and right

    def set(self, setting: Binaural | None) -> None:
        """Use `setting` from the next bar; None turns the layer off, and turning it on again starts at zero."""
        if setting is None:
            self._phase = np.zeros(2)
        self.setting = setting

    def render(self, n: int) -> np.ndarray:
        """The next `n` samples of the layer, shape (n, 2); call only while a setting is active."""
        assert self.setting is not None
        step = 2 * math.pi * np.asarray(self.setting.frequencies) / self.sr
        phase = self._phase + np.arange(n)[:, None] * step
        self._phase = (self._phase + n * step) % (2 * math.pi)
        return np.sin(phase) * self.setting.level
