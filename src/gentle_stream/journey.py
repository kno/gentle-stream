"""Journeys: a timeline of stages that moves the continuous style fields (`engine.GLIDE_FIELDS`) on its own.

A `Journey` is plain data. Each `Stage` names the values some fields reach by its end, interpolated linearly from
the previous stage's end values (the first stage starts from the style playing when the journey starts); a field a
stage does not name holds its value. `Journey.at` is pure: the engine evaluates it once per bar, at its rendered
seconds since the journey started, and applies the values in place. After the last stage, `end="sustain"` holds the
final values forever and `end="release"` hands the fields back to the music as they are.

The built-in journeys (`BUILTIN`) stay in the genre that is playing; genre steps come later.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import accumulate

from .engine import GLIDE_FIELDS

ENDS = ("sustain", "release")


@dataclass(frozen=True)
class Stage:
    name: str
    seconds: float
    to: dict[str, float]   # the value each named field reaches at the end of the stage

    def __post_init__(self) -> None:
        if not math.isfinite(self.seconds) or self.seconds <= 0:
            raise ValueError(f"stage {self.name!r}: seconds must be above 0")
        unknown = sorted(set(self.to) - set(GLIDE_FIELDS))
        if unknown:
            raise ValueError(f"stage {self.name!r}: cannot move {', '.join(map(repr, unknown))}: only "
                             f"{', '.join(GLIDE_FIELDS)}")
        if not all(math.isfinite(value) for value in self.to.values()):
            raise ValueError(f"stage {self.name!r}: every value must be a finite number")


@dataclass(frozen=True)
class Journey:
    name: str
    stages: tuple[Stage, ...]
    end: str = "sustain"
    description: str = ""
    _ends: tuple[float, ...] = field(init=False, repr=False, compare=False)   # cumulative stage end times

    def __post_init__(self) -> None:
        if not self.stages:
            raise ValueError(f"journey {self.name!r} has no stages")
        if self.end not in ENDS:
            raise ValueError(f"journey {self.name!r}: end must be one of {', '.join(ENDS)}")
        object.__setattr__(self, "_ends", tuple(accumulate(s.seconds for s in self.stages)))

    @property
    def seconds(self) -> float:
        """The length of every stage together."""
        return self._ends[-1]

    @property
    def fields(self) -> tuple[str, ...]:
        """The fields the journey owns: every field a stage names, in GLIDE_FIELDS order."""
        named = {name for stage in self.stages for name in stage.to}
        return tuple(name for name in GLIDE_FIELDS if name in named)

    def at(self, t: float, start: Mapping[str, float]) -> tuple[int, float, dict[str, float]]:
        """(stage index, progress through it 0..1, value of every owned field) at `t` seconds into the journey,
        starting from the `start` value of each owned field. Exact at stage boundaries; past the end, the last
        stage at progress 1."""
        t = max(0.0, float(t))
        index = min(bisect_right(self._ends, t), len(self.stages) - 1)
        begin = self._ends[index - 1] if index else 0.0
        stage = self.stages[index]
        progress = min(1.0, (t - begin) / stage.seconds)
        values = {name: float(start[name]) for name in self.fields}
        for previous in self.stages[:index]:
            values.update(previous.to)
        for name, target in stage.to.items():   # (1 - p) a + p b: exactly a at p = 0 and exactly b at p = 1
            values[name] = (1 - progress) * values[name] + progress * target
        return index, progress, values


BUILTIN: dict[str, Journey] = {j.name: j for j in (
    Journey("warm-up", (
        Stage("Settle", 60, {"bpm": 60.0, "energy": 0.2, "brightness": 0.35, "lead_density": 0.3}),
        Stage("Wake", 180, {"bpm": 72.0, "energy": 0.45, "brightness": 0.5}),
        Stage("Rise", 240, {"bpm": 88.0, "energy": 0.7, "brightness": 0.65, "lead_density": 0.55}),
        Stage("Glow", 120, {"bpm": 100.0, "energy": 0.9, "brightness": 0.75, "lead_density": 0.7}),
    ), description="60 to 100 bpm and energy 0.2 to 0.9 over 10 minutes, then holds"),
    Journey("wind-down", (
        Stage("Ease", 120, {"bpm": 84.0, "energy": 0.5, "brightness": 0.5}),
        Stage("Soften", 240, {"bpm": 68.0, "energy": 0.3, "brightness": 0.35, "space": 0.6}),
        Stage("Drift", 240, {"bpm": 58.0, "energy": 0.15, "brightness": 0.25, "space": 0.75, "lead_density": 0.2}),
    ), end="release", description="down to 58 bpm and energy 0.15 over 10 minutes, then lets go"),
)}


def unknown_journey(name: str) -> str:
    return f'no journey called "{name}" (choose from {", ".join(BUILTIN)})'
