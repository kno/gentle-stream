"""Journeys: a timeline of stages that moves the continuous style fields (`engine.GLIDE_FIELDS`) on its own.

A `Journey` is plain data. Each `Stage` names the values some fields reach by its end, interpolated linearly from
the previous stage's end values (the first stage starts from the style playing when the journey starts); a field a
stage does not name holds its value. `Journey.at` is pure: the engine evaluates it once per bar, at its rendered
seconds since the journey started, and applies the values in place. After the last stage, `end="sustain"` holds the
final values forever and `end="release"` hands the fields back to the music as they are.

A stage may also move the binaural layer (`binaural.Binaural`): its `binaural` block names the carrier, beat or
level reached by its end, interpolated the same way, from the layer playing when the journey starts (silent when
it is off). A journey that names any of them owns the layer while it runs; one that names none leaves it alone.

`Journey.snapshot` describes one bar's place in the journey (`JourneySnapshot`): the engine makes one per rendered
bar and it travels with that bar's audio, so the progress shown is the progress heard.

The built-in journeys (`BUILTIN`) stay in the genre that is playing; genre steps come later.
"""
from __future__ import annotations

import json
import math
import os
from bisect import bisect_right
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from itertools import accumulate
from pathlib import Path
from types import MappingProxyType

from .binaural import BEAT, CARRIER, DEFAULT_BEAT, DEFAULT_CARRIER, MAX_LEVEL
from .binaural import FIELDS as BINAURAL_FIELDS
from .engine import GLIDE_FIELDS
from .presets import PresetError, normalize_name
from .storage import write_json_atomic

ENDS = ("sustain", "release")
BINAURAL_RANGES = {"carrier": CARRIER, "beat": BEAT, "level": (0.0, MAX_LEVEL)}
CURVES = ("linear", "ease-in", "ease-out", "ease-in-out", "exp", "step")


def _genre_names() -> set[str]:
    from . import genres
    return set(genres.NAMES)


def shape(curve: str, progress: float) -> float:
    """Curve shape from 0 to 1. Unknown curves fall back to linear."""
    if progress <= 0:
        return 0.0
    if progress >= 1:
        return 1.0
    if curve == "ease-in":
        return progress ** 2
    if curve == "ease-out":
        return 1 - (1 - progress) ** 2
    if curve == "ease-in-out":
        return 0.5 * (2 * progress) ** 2 if progress < 0.5 else 1 - 0.5 * (2 * (1 - progress)) ** 2
    if curve == "exp":
        return progress
    if curve == "step":
        return 0.0
    return progress



@dataclass(frozen=True)
class Stage:
    name: str
    seconds: float
    to: Mapping[str, float]   # the immutable values each named field reaches at the end of the stage
    genre: str | None = None
    curve: str = "linear"
    binaural: Mapping[str, float] = MappingProxyType({})   # the binaural values reached by the end of the stage

    def __post_init__(self) -> None:
        if not math.isfinite(self.seconds) or self.seconds <= 0:
            raise ValueError(f"stage {self.name!r}: seconds must be above 0")
        if self.genre is not None and self.genre not in _genre_names():
            raise ValueError(f"stage {self.name!r}: unknown genre {self.genre!r}")
        if self.curve not in CURVES:
            raise ValueError(f"stage {self.name!r}: unknown curve {self.curve!r}")
        unknown = sorted(set(self.to) - set(GLIDE_FIELDS))
        if unknown:
            raise ValueError(f"stage {self.name!r}: cannot move {', '.join(map(repr, unknown))}: only "
                             f"{', '.join(GLIDE_FIELDS)}")
        if not all(math.isfinite(value) for value in self.to.values()):
            raise ValueError(f"stage {self.name!r}: every value must be a finite number")
        object.__setattr__(self, "to", MappingProxyType(dict(self.to)))
        for name, value in self.binaural.items():
            if name not in BINAURAL_RANGES:
                raise ValueError(f"stage {self.name!r}: binaural has no {name!r}: only {', '.join(BINAURAL_FIELDS)}")
            lo, hi = BINAURAL_RANGES[name]
            if not lo <= value <= hi:
                raise ValueError(f"stage {self.name!r}: binaural {name} must be between {lo:g} and {hi:g}")
        object.__setattr__(self, "binaural", MappingProxyType(dict(self.binaural)))

    def __hash__(self) -> int:
        return hash((self.name, self.seconds, self.genre, self.curve, frozenset(self.to.items()),
                     frozenset(self.binaural.items())))


@dataclass(frozen=True)
class JourneySnapshot:
    """Where one bar is in a journey. `stage` counts from 1; `progress` (0..1) is through that stage; `bpm` is the
    bar's tempo and `target_bpm` the tempo at the end of its stage (the bar's own when the journey leaves tempo
    alone); `seconds_left` is to the end of the journey, None once a sustaining journey holds its final values."""
    name: str
    title: str
    stage: int
    stages: int
    stage_name: str
    progress: float
    bpm: float
    target_bpm: float
    seconds_left: float | None
    binaural: dict[str, float] | None = None   # the binaural values at the bar's start, when the journey moves them

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data) -> JourneySnapshot | None:
        """The snapshot in `data` (a player's state), or None when it is missing or malformed."""
        try:
            snap = cls(str(data["name"]), str(data["title"]), int(data["stage"]), int(data["stages"]),
                       str(data["stage_name"]), float(data["progress"]), float(data["bpm"]),
                       float(data["target_bpm"]),
                       None if data["seconds_left"] is None else float(data["seconds_left"]),
                       _binaural_values(data.get("binaural")))
        except (KeyError, TypeError, ValueError):
            return None
        return snap


def _binaural_values(data) -> dict[str, float] | None:
    """The binaural values of a snapshot dict, or None when absent (an older player reports none)."""
    if not isinstance(data, Mapping):
        return None
    return {name: float(data[name]) for name in BINAURAL_FIELDS if name in data}


def _parse_binaural(raw, number: int, warnings: list[str]) -> dict[str, float]:
    """A stage's binaural block, clamped into range (one warning per clamped value); unknown keys are ignored."""
    if not isinstance(raw, Mapping):
        raise ValueError(f'stage {number}: "binaural" must be an object')
    out = {}
    for name in BINAURAL_FIELDS:
        if name not in raw:
            continue
        value = raw[name]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f'stage {number}: "binaural.{name}" must be a number')
        lo, hi = BINAURAL_RANGES[name]
        result = min(hi, max(lo, float(value)))
        if result != value:
            warnings.append(f'stage {number}: "binaural.{name}" clamped from {value!r} to {result!r}')
        out[name] = result
    return out


@dataclass(frozen=True)
class Journey:
    name: str
    stages: tuple[Stage, ...]
    end: str = "sustain"
    description: str = ""
    title: str = ""   # how it is shown; the name with a capital initial by default ("warm-up" -> "Warm-up")
    _ends: tuple[float, ...] = field(init=False, repr=False, compare=False)   # cumulative stage end times

    def __post_init__(self) -> None:
        if not self.stages:
            raise ValueError(f"journey {self.name!r} has no stages")
        if self.end not in ENDS:
            raise ValueError(f"journey {self.name!r}: end must be one of {', '.join(ENDS)}")
        object.__setattr__(self, "_ends", tuple(accumulate(s.seconds for s in self.stages)))
        if not self.title:
            object.__setattr__(self, "title", self.name[:1].upper() + self.name[1:])

    @classmethod
    def from_dict(cls, data, warnings=None, *, name: str | None = None) -> Journey:
        """Parse and normalize a version-one journey object.

        ``warnings`` is an optional list receiving one message per clamped value.
        Unknown keys are deliberately ignored.
        """
        if not isinstance(data, Mapping):
            raise ValueError("journey must be a JSON object")
        version = data.get("version")
        if isinstance(version, bool) or version != 1:
            raise ValueError('"version" must be 1')
        raw_stages = data.get("stages")
        if not isinstance(raw_stages, list):
            raise ValueError('"stages" must be an array')
        if not raw_stages:
            raise ValueError('"stages" must not be empty')
        if len(raw_stages) > 24:
            raise ValueError('"stages" must contain at most 24 stages')
        warnings = warnings if warnings is not None else []
        stages = []
        total = 0.0
        for number, raw in enumerate(raw_stages, 1):
            if not isinstance(raw, Mapping):
                raise ValueError(f"stage {number} must be an object")
            seconds = raw.get("seconds")
            if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 10 <= seconds <= 14400:
                raise ValueError(f'stage {number}: "seconds" must be a number between 10 and 14400')
            total += float(seconds)
            stage_name = raw.get("name", f"Stage {number}")
            if not isinstance(stage_name, str):
                raise ValueError(f"stage {number}: \"name\" must be a string")
            to = raw.get("to", {})
            if not isinstance(to, Mapping):
                raise ValueError(f"stage {number}: \"to\" must be an object")
            normalized = {}
            for key, value in to.items():
                if key not in GLIDE_FIELDS:
                    continue
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise ValueError(f'stage {number}: "to.{key}" must be a number')
                lo, hi = GLIDE_FIELDS[key]
                result = round(min(hi, max(lo, float(value))), 1) if key == "bpm" else min(hi, max(lo, float(value)))
                if result != value:
                    warnings.append(f'stage {number}: "to.{key}" clamped from {value!r} to {result!r}')
                normalized[key] = result
            genre = raw.get("genre")
            if genre is not None and (not isinstance(genre, str) or genre not in _genre_names()):
                raise ValueError(f"stage {number}: unknown genre {genre!r}")
            curve = raw.get("curve", "linear")
            if not isinstance(curve, str) or curve not in CURVES:
                if isinstance(curve, str):
                    warnings.append(f'stage {number}: unknown curve {curve!r}; using linear')
                    curve = "linear"
                else:
                    raise ValueError(f'stage {number}: "curve" must be a string')
            stages.append(Stage(stage_name, float(seconds), normalized, genre, curve,
                                _parse_binaural(raw.get("binaural", {}), number, warnings)))
        if total > 12 * 60 * 60:
            raise ValueError('combined stage duration must be at most 43200 seconds')
        journey_name = data.get("name", name)
        if journey_name is None:
            raise ValueError('"name" is required')
        if not isinstance(journey_name, str) or not journey_name:
            raise ValueError('"name" must be a non-empty string')
        end = data.get("end", "sustain")
        if not isinstance(end, str) or end not in ENDS:
            raise ValueError(f'"end" must be one of {", ".join(ENDS)}')
        for key in ("title", "description"):
            if key in data and not isinstance(data[key], str):
                raise ValueError(f'"{key}" must be a string')
        return cls(journey_name, tuple(stages), end=end, description=data.get("description", ""),
                   title=data.get("title", ""))

    def to_dict(self) -> dict:
        stages_list = []
        for s in self.stages:
            stage_dict = {"name": s.name, "seconds": s.seconds, "to": dict(s.to)}
            if s.genre is not None:
                stage_dict["genre"] = s.genre
            if s.curve != "linear":
                stage_dict["curve"] = s.curve
            if s.binaural:
                stage_dict["binaural"] = dict(s.binaural)
            stages_list.append(stage_dict)
        return {"version": 1, "name": self.name, "title": self.title, "description": self.description,
                "end": self.end, "stages": stages_list}

    @property
    def seconds(self) -> float:
        """The length of every stage together."""
        return self._ends[-1]

    @property
    def fields(self) -> tuple[str, ...]:
        """The fields the journey owns: every field a stage names, in GLIDE_FIELDS order."""
        named = {name for stage in self.stages for name in stage.to}
        return tuple(name for name in GLIDE_FIELDS if name in named)

    @property
    def owns_binaural(self) -> bool:
        """Whether any stage moves the binaural layer (then the journey drives it while it runs)."""
        return any(stage.binaural for stage in self.stages)

    def at(self, t: float, start: Mapping[str, float]) -> tuple[int, float, dict[str, float]]:
        """(stage index, progress through it 0..1, value of every owned field) at `t` seconds into the journey,
        starting from the `start` value of each owned field. Exact at stage boundaries; past the end, the last
        stage at progress 1."""
        return self._interpolate(t, {name: float(start[name]) for name in self.fields}, "to")

    def binaural_at(self, t: float, start: Mapping[str, float]) -> dict[str, float]:
        """The carrier, beat and level at `t` seconds into the journey, from `start` (all three), like `at`."""
        return self._interpolate(t, {name: float(start[name]) for name in BINAURAL_FIELDS}, "binaural")[2]

    def _interpolate(self, t: float, values: dict[str, float], targets: str) -> tuple[int, float, dict[str, float]]:
        """`at` over the stages' `targets` mapping ("to" or "binaural"), starting from `values`."""
        t = max(0.0, float(t))
        index = min(bisect_right(self._ends, t), len(self.stages) - 1)
        begin = self._ends[index - 1] if index else 0.0
        stage = self.stages[index]
        progress = min(1.0, (t - begin) / stage.seconds)
        for previous in self.stages[:index]:
            values.update(getattr(previous, targets))
        for name, target in getattr(stage, targets).items():
            shaped = shape(stage.curve, progress)
            values[name] = (1 - shaped) * values[name] + shaped * target
        return index, progress, values

    def binaural_start(self, playing: Mapping[str, float] | None) -> dict[str, float]:
        """Where the binaural values start: the layer `playing` (its to_dict), or, when it is off, silence at the
        first carrier and beat a stage names (the defaults otherwise)."""
        if playing is not None:
            return {name: float(playing[name]) for name in BINAURAL_FIELDS}
        named = [stage.binaural for stage in self.stages]
        carrier = next((b["carrier"] for b in named if "carrier" in b), DEFAULT_CARRIER)
        beat = next((b["beat"] for b in named if "beat" in b), DEFAULT_BEAT)
        return {"carrier": carrier, "beat": beat, "level": 0.0}

    def snapshot(self, t: float, start: Mapping[str, float], bpm: float,
                 binaural_start: Mapping[str, float] | None = None) -> JourneySnapshot:
        """The snapshot of a bar starting `t` seconds into the journey and playing at `bpm`; `binaural_start` is
        where its binaural values started, for a journey that owns the layer."""
        index, progress, _ = self.at(t, start)
        target = bpm
        if "bpm" in self.fields:   # the stage's end tempo, clamped and rounded as the engine applies it
            lo, hi = GLIDE_FIELDS["bpm"]
            target = round(min(hi, max(lo, self.at(self._ends[index], start)[2]["bpm"])), 1)
        t = max(0.0, float(t))
        left = None if self.end == "sustain" and t >= self.seconds else max(0.0, self.seconds - t)
        binaural = self.binaural_at(t, binaural_start) if self.owns_binaural and binaural_start else None
        return JourneySnapshot(self.name, self.title, index + 1, len(self.stages), self.stages[index].name,
                               progress, float(bpm), target, left, binaural)


BUILTIN: dict[str, Journey] = {j.name: j for j in (
    Journey("ambient-to-synthwave", (
        Stage("Ambient", 60, {"bpm": 60.0}, genre="ambient",
              binaural={"carrier": 200.0, "beat": 6.0, "level": 0.05}),
        Stage("Chillout", 180, {"bpm": 88.0}, genre="lofi"),
        Stage("Synthwave", 240, {"bpm": 118.0}, genre="synthwave", binaural={"level": 0.0}),
    ), description="ambient at 60 bpm through lo-fi chillout to synthwave at 118 bpm, then sustains; a 6 Hz "
                   "binaural texture fades in with the ambient stage and out during the synthwave one"),
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


class JourneyStoreError(Exception):
    """A journey cannot be saved or deleted; the message is meant for the person."""


STORE_VERSION = 1


def default_store_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "gentle-stream" / "journeys.json"


def _store_key(name: str) -> str:
    return " ".join(str(name).split()).casefold()


@dataclass(frozen=True)
class _Saved:
    journey: Journey   # named and titled after the saved name
    saved_at: str      # ISO 8601, UTC


class JourneyStore:
    """Saved journeys in `journeys.json`, next to `presets.json`, with the same guarantees as `PresetStore`.

    Names follow the preset rules (trimmed, at most NAME_MAX characters, matched ignoring case) and cannot be a
    built-in journey's. Every call reads the file. It is rewritten atomically; a corrupt file is never overwritten;
    invalid entries are skipped. `error` describes the problem found by the last read, or is None.
    """

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else default_store_path()
        self.error: str | None = None

    def _load(self) -> tuple[dict[str, _Saved], bool]:
        """Saved journeys by lowercase name, and whether the file is readable (False: leave it untouched)."""
        self.error = None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}, True
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            self.error = f"Cannot read {self.path}: {e}"
            return {}, False
        entries = data.get("journeys") if isinstance(data, dict) and data.get("version") == STORE_VERSION else None
        if not isinstance(entries, list):
            self.error = f"Cannot read {self.path}: unexpected format"
            return {}, False
        saved, skipped = {}, 0
        for entry in entries:
            if (item := self._parse(entry)) is None:
                skipped += 1
            else:
                saved[_store_key(item.journey.name)] = item
        if skipped:
            self.error = f"Skipped {skipped} invalid saved journey(s) in {self.path}"
        return saved, True

    @staticmethod
    def _parse(entry) -> _Saved | None:
        if not isinstance(entry, dict):
            return None
        try:
            name = normalize_name(entry.get("name", ""))
            journey = Journey.from_dict(entry.get("journey"))
        except (PresetError, ValueError):
            return None
        saved_at = entry.get("saved_at")
        return _Saved(_renamed(journey, name), saved_at if isinstance(saved_at, str) else "")

    def _writable(self) -> dict[str, _Saved]:
        saved, ok = self._load()
        if not ok:
            raise JourneyStoreError(f"{self.error}; fix or move the file to save journeys again.")
        return saved

    def _write(self, saved: dict[str, _Saved]) -> None:
        data = {"version": STORE_VERSION, "journeys": [
            {"name": item.journey.name, "journey": item.journey.to_dict(), "saved_at": item.saved_at}
            for item in sorted(saved.values(), key=lambda item: _store_key(item.journey.name))
        ]}
        try:
            write_json_atomic(self.path, data, prefix=".journeys-")
        except OSError as e:
            raise JourneyStoreError(f"Cannot write {self.path}: {e}") from e

    def list(self) -> list[tuple[str, Journey]]:
        """(name, journey) of every saved journey, sorted by name ignoring case."""
        saved = sorted(self._load()[0].values(), key=lambda item: _store_key(item.journey.name))
        return [(item.journey.name, item.journey) for item in saved]

    def get(self, name: str) -> Journey | None:
        item = self._load()[0].get(_store_key(name))
        return item.journey if item is not None else None

    def save(self, name: str, journey: Journey) -> tuple[str, bool]:
        """Save `journey` under `name`; returns the stored name and whether it replaced a saved journey."""
        try:
            name = normalize_name(name)
        except PresetError as e:
            raise JourneyStoreError(str(e)) from None
        if _store_key(name) in {_store_key(n) for n in BUILTIN}:
            raise JourneyStoreError(f'"{name}" is a built-in journey; choose another name.')
        saved = self._writable()
        replaced = saved.pop(_store_key(name), None) is not None
        saved[_store_key(name)] = _Saved(_renamed(journey, name),
                                         datetime.now(UTC).isoformat(timespec="seconds"))
        self._write(saved)
        return name, replaced

    def delete(self, name: str) -> bool:
        """Remove the saved journey called `name` (ignoring case); False if there was none."""
        saved = self._writable()
        if saved.pop(_store_key(name), None) is None:
            return False
        self._write(saved)
        return True


def _renamed(journey: Journey, name: str) -> Journey:
    """`journey` named and titled after its saved name, so it shows as the person called it."""
    return Journey(name, journey.stages, journey.end, journey.description, name)
