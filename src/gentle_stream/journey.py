"""Journeys: a timeline of stages that moves the continuous style fields (`engine.GLIDE_FIELDS`) on its own.

A `Journey` is plain data. Each `Stage` names the values some fields reach by its end, interpolated linearly from
the previous stage's end values (the first stage starts from the style playing when the journey starts); a field a
stage does not name holds its value. `Journey.at` is pure: the engine evaluates it once per bar, at its rendered
seconds since the journey started, and applies the values in place. After the last stage, `end="sustain"` holds the
final values forever and `end="release"` hands the fields back to the music as they are.

A stage may also switch parts off and on (`layers`, e.g. {"drums": false}): each stage's switches hold until a later
stage changes them, every part starts on, and the engine applies a change on a 4-bar phrase boundary.

A stage that changes genre may ask for a gradual step (`transition`, a number of bars): both genres then play
together and crossfade over those bars instead of switching at once.

Drums can follow the journey too: `drums="energy"` maps the energy to a level (`drums_for_energy`), and a stage's
`drums` names one explicitly (held by later stages); the engine climbs or drops one level per 4-bar phrase.

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
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from itertools import accumulate
from pathlib import Path
from types import MappingProxyType

from .binaural import BEAT, CARRIER, DEFAULT_BEAT, DEFAULT_CARRIER, MAX_LEVEL
from .binaural import FIELDS as BINAURAL_FIELDS
from .engine import GLIDE_FIELDS
from .presets import PresetError, normalize_name
from .storage import write_json_atomic
from .style import DRUMS

ENDS = ("sustain", "release")
BINAURAL_RANGES = {"carrier": CARRIER, "beat": BEAT, "level": (0.0, MAX_LEVEL)}
LAYERS = ("chords", "bass", "drums", "lead", "counter")   # the parts a bar plan can hold (`BarPlan.layers`)
DRUM_ENERGY = ((0.25, "none"), (0.5, "soft"), (0.75, "lofi"))   # below each energy, that drum level; then busy
MAX_TRANSITION_BARS = 32
MAX_PHRASES = 12                  # spoken phrases a stage may have, each 1 to MAX_PHRASE characters
MAX_PHRASE = 80
PHRASE_EVERY = (10.0, 3600.0)     # seconds between a stage's phrases
DEFAULT_PHRASE_EVERY = 120.0
DEFAULT_RAMP = 120.0              # seconds an open stage's values take to reach their targets


def drums_for_energy(energy: float) -> str:
    """The drum level an energy calls for, from none (quiet) to busy (0.75 and above)."""
    return next((level for below, level in DRUM_ENERGY if energy < below), "busy")
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
    layers: Mapping[str, bool] = MappingProxyType({})     # parts switched on (True) or off (False) from this stage
    drums: str | None = None                              # a drum level from this stage on, None to keep the last
    transition: int | None = None                         # bars over which a genre step crossfades, None: at once
    phrases: tuple[str, ...] = ()                         # spoken during the stage, one per `phrase_every` seconds
    phrase_every: float = DEFAULT_PHRASE_EVERY
    ramp: float | None = None                             # an open stage (seconds infinite): its ramp's length

    @property
    def open(self) -> bool:
        """Whether the stage lasts until the listener moves on (PM-037)."""
        return self.ramp is not None

    @property
    def span(self) -> float:
        """The seconds its values take to reach their targets: the stage, or an open stage's ramp."""
        return self.ramp if self.ramp is not None else self.seconds

    def __post_init__(self) -> None:
        if self.ramp is not None:
            if not (math.isinf(self.seconds) and math.isfinite(self.ramp) and self.ramp > 0):
                raise ValueError(f"stage {self.name!r}: an open stage has infinite seconds and a ramp above 0")
        elif not math.isfinite(self.seconds) or self.seconds <= 0:
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
        unknown_layers = sorted(set(self.layers) - set(LAYERS))
        if unknown_layers:
            raise ValueError(f"stage {self.name!r}: unknown layer {unknown_layers[0]!r}: only {', '.join(LAYERS)}")
        object.__setattr__(self, "layers", MappingProxyType(dict(self.layers)))
        if self.drums is not None and self.drums not in DRUMS:
            raise ValueError(f"stage {self.name!r}: drums must be one of {', '.join(DRUMS)}")
        if self.transition is not None and not 1 <= self.transition <= MAX_TRANSITION_BARS:
            raise ValueError(f"stage {self.name!r}: a transition lasts 1 to {MAX_TRANSITION_BARS} bars")
        if len(self.phrases) > MAX_PHRASES or not all(1 <= len(p) <= MAX_PHRASE for p in self.phrases):
            raise ValueError(f"stage {self.name!r}: at most {MAX_PHRASES} phrases of 1 to {MAX_PHRASE} characters")
        if not PHRASE_EVERY[0] <= self.phrase_every <= PHRASE_EVERY[1]:
            raise ValueError(f"stage {self.name!r}: phrases come every {PHRASE_EVERY[0]:g} to {PHRASE_EVERY[1]:g} s")
        object.__setattr__(self, "phrases", tuple(self.phrases))

    def __hash__(self) -> int:
        return hash((self.name, self.seconds, self.genre, self.curve, frozenset(self.to.items()),
                     frozenset(self.binaural.items()), frozenset(self.layers.items()), self.drums, self.transition,
                     self.phrases, self.phrase_every, self.ramp))


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
    override: tuple[str, dict[str, float]] | None = None   # a mood's offsets on the journey's fields for this stage
    open: bool = False         # the stage lasts until the listener moves on (no time left)
    open_ahead: bool = False   # a later stage does: the journey has no end time yet

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
                       _binaural_values(data.get("binaural")), _override(data.get("override")),
                       data.get("open") is True, data.get("open_ahead") is True)
        except (KeyError, TypeError, ValueError):
            return None
        return snap


def _override(data) -> tuple[str, dict[str, float]] | None:
    """A snapshot's mood override, or None when absent or malformed (an older player reports none)."""
    try:
        name, offsets = data
        return str(name), {str(k): float(v) for k, v in dict(offsets).items()}
    except (TypeError, ValueError):
        return None


def _binaural_values(data) -> dict[str, float] | None:
    """The binaural values of a snapshot dict, or None when absent (an older player reports none)."""
    if not isinstance(data, Mapping):
        return None
    return {name: float(data[name]) for name in BINAURAL_FIELDS if name in data}


def _parse_transition(raw, number: int) -> int | None:
    """A stage's crossfade length in bars, or None for a step at once."""
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError(f'stage {number}: "transition" must be an object')
    bars = raw.get("bars")
    if isinstance(bars, bool) or not isinstance(bars, int) or not 1 <= bars <= MAX_TRANSITION_BARS:
        raise ValueError(f'stage {number}: "transition.bars" must be a whole number from 1 to {MAX_TRANSITION_BARS}')
    return bars


def _parse_phrases(raw, every, number: int) -> tuple[tuple[str, ...], float]:
    """A stage's spoken phrases (whitespace collapsed) and their interval; anything malformed rejects the journey."""
    if raw is None:
        if every is not None:
            raise ValueError(f'stage {number}: "phrase_every" needs "phrases"')
        return (), DEFAULT_PHRASE_EVERY
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw):
        raise ValueError(f'stage {number}: "phrases" must be a list of strings')
    phrases = tuple(" ".join(p.split()) for p in raw)
    if len(phrases) > MAX_PHRASES:
        raise ValueError(f'stage {number}: at most {MAX_PHRASES} phrases')
    if not all(1 <= len(p) <= MAX_PHRASE for p in phrases):
        raise ValueError(f'stage {number}: every phrase must have 1 to {MAX_PHRASE} characters')
    if every is None:
        return phrases, DEFAULT_PHRASE_EVERY
    lo, hi = PHRASE_EVERY
    if isinstance(every, bool) or not isinstance(every, (int, float)) or not lo <= every <= hi:
        raise ValueError(f'stage {number}: "phrase_every" must be a number from {lo:g} to {hi:g} seconds')
    return phrases, float(every)


def _parse_drums(raw, number: int) -> str | None:
    """A stage's drum level, or None when it names none."""
    if raw is not None and raw not in DRUMS:
        raise ValueError(f'stage {number}: "drums" must be one of {", ".join(DRUMS)}')
    return raw


def _parse_layers(raw, number: int) -> dict[str, bool]:
    """A stage's part switches; an unknown part or a value that is not true or false rejects the journey."""
    if not isinstance(raw, Mapping):
        raise ValueError(f'stage {number}: "layers" must be an object')
    for name, on in raw.items():
        if name not in LAYERS:
            raise ValueError(f'stage {number}: unknown layer "{name}" (choose from {", ".join(LAYERS)})')
        if not isinstance(on, bool):
            raise ValueError(f'stage {number}: "layers.{name}" must be true or false')
    return dict(raw)


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
    drums: str | None = None   # "energy": the drum level follows the energy (stages naming one win)
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
            ramp = None
            if seconds == "open":   # PM-037: lasts until skipped or edited; its values ramp over "ramp" seconds
                ramp = raw.get("ramp", DEFAULT_RAMP)
                if isinstance(ramp, bool) or not isinstance(ramp, (int, float)) or not 10 <= ramp <= 14400:
                    raise ValueError(f'stage {number}: "ramp" must be a number between 10 and 14400')
                seconds, ramp = math.inf, float(ramp)
            else:
                if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) \
                        or not 10 <= seconds <= 14400:
                    raise ValueError(f'stage {number}: "seconds" must be a number between 10 and 14400')
                if "ramp" in raw:
                    raise ValueError(f'stage {number}: "ramp" is only for "seconds": "open"')
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
                                _parse_binaural(raw.get("binaural", {}), number, warnings),
                                _parse_layers(raw.get("layers", {}), number), _parse_drums(raw.get("drums"), number),
                                _parse_transition(raw.get("transition"), number),
                                *_parse_phrases(raw.get("phrases"), raw.get("phrase_every"), number), ramp))
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
        drums = data.get("drums")
        if drums is not None and drums != "energy":
            raise ValueError('"drums" must be "energy"')
        return cls(journey_name, tuple(stages), end=end, description=data.get("description", ""),
                   title=data.get("title", ""), drums=drums)

    def to_dict(self) -> dict:
        stages_list = []
        for s in self.stages:
            stage_dict = {"name": s.name, "seconds": "open" if s.open else s.seconds, "to": dict(s.to)}
            if s.ramp is not None:
                stage_dict["ramp"] = s.ramp
            if s.genre is not None:
                stage_dict["genre"] = s.genre
            if s.curve != "linear":
                stage_dict["curve"] = s.curve
            if s.binaural:
                stage_dict["binaural"] = dict(s.binaural)
            if s.layers:
                stage_dict["layers"] = dict(s.layers)
            if s.drums is not None:
                stage_dict["drums"] = s.drums
            if s.transition is not None:
                stage_dict["transition"] = {"bars": s.transition}
            if s.phrases:
                stage_dict["phrases"] = list(s.phrases)
                stage_dict["phrase_every"] = s.phrase_every
            stages_list.append(stage_dict)
        data = {"version": 1, "name": self.name, "title": self.title, "description": self.description,
                "end": self.end, "stages": stages_list}
        if self.drums is not None:
            data["drums"] = self.drums
        return data

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
    def drives_drums(self) -> bool:
        """Whether the journey moves the drum level (by energy or by a stage naming one)."""
        return self.drums == "energy" or any(stage.drums is not None for stage in self.stages)

    def drums_at(self, t: float, energy: float) -> str | None:
        """The drum level the journey asks for at `t` seconds with the music at `energy`: the last level a stage up
        to the one playing names, else the energy's (`drums="energy"`), else None (it leaves drums alone)."""
        t = max(0.0, float(t))
        index = min(bisect_right(self._ends, t), len(self.stages) - 1)
        named = [stage.drums for stage in self.stages[: index + 1] if stage.drums is not None]
        if named:
            return named[-1]
        return drums_for_energy(energy) if self.drums == "energy" else None

    @property
    def phrases(self) -> tuple[str, ...]:
        """Every phrase the journey can speak, once each, in order of first appearance."""
        return tuple(dict.fromkeys(p for stage in self.stages for p in stage.phrases))

    def stage_index(self, t: float) -> int:
        """The index of the stage playing at `t` seconds (the last one past the end)."""
        return min(bisect_right(self._ends, max(0.0, float(t))), len(self.stages) - 1)

    def masked_layers(self, t: float) -> frozenset[str]:
        """The parts switched off at `t` seconds into the journey: every stage's switches up to the one playing."""
        t = max(0.0, float(t))
        index = min(bisect_right(self._ends, t), len(self.stages) - 1)
        switches: dict[str, bool] = {}
        for stage in self.stages[: index + 1]:
            switches.update(stage.layers)
        return frozenset(name for name, on in switches.items() if not on)

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
        progress = min(1.0, (t - begin) / stage.span)
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
            stage_end = (self._ends[index - 1] if index else 0.0) + self.stages[index].span   # the ramp's end, if open
            target = round(min(hi, max(lo, self.at(stage_end, start)[2]["bpm"])), 1)
        t = max(0.0, float(t))
        is_open = self.stages[index].open
        ahead = not is_open and not math.isfinite(self.seconds)
        if is_open or ahead:
            left = None
        else:
            left = None if self.end == "sustain" and t >= self.seconds else max(0.0, self.seconds - t)
        binaural = self.binaural_at(t, binaural_start) if self.owns_binaural and binaural_start else None
        return JourneySnapshot(self.name, self.title, index + 1, len(self.stages), self.stages[index].name,
                               progress, float(bpm), target, left, binaural, None, is_open, ahead)

    def closed(self, index: int, seconds: float) -> Journey:
        """This journey with open stage `index` closed after `seconds` (`journey skip` on an open stage)."""
        stages = list(self.stages)
        stages[index] = replace(stages[index], seconds=max(seconds, 1e-3), ramp=None)
        return replace(self, stages=tuple(stages))


def map_position(old: Journey, t: float, new: Journey) -> float:
    """Where `t` seconds into `old` falls in `new` (PM-034): as far into the stage of the same name (any case) as it
    was, kept inside that stage when it is shorter now; without that stage, the same time, at most `new`'s end."""
    t = max(0.0, float(t))
    index = old.stage_index(t)
    name = old.stages[index].name.casefold()
    into = t - (old._ends[index - 1] if index else 0.0)
    for j, stage in enumerate(new.stages):
        if stage.name.casefold() == name:
            start = new._ends[j - 1] if j else 0.0
            return start + min(into, stage.seconds * 0.999)
    return min(t, new.seconds)


def _number(value: float) -> str:
    return f"{value:g}"


def _length(stage: Stage) -> str:
    return f"open (ramp {_number(stage.ramp)} s)" if stage.ramp is not None else f"{_number(stage.seconds)} s"


def stage_diff(old: Journey, new: Journey) -> list[str]:
    """One line per stage: `=` kept, `~` changed (what changed), `+` added, `-` removed, matched by name (any case),
    in the new order with removed stages last."""
    by_name = {stage.name.casefold(): stage for stage in old.stages}
    lines = []
    for stage in new.stages:
        before = by_name.pop(stage.name.casefold(), None)
        if before is None:
            extra = f", genre {stage.genre}" if stage.genre else ""
            lines.append(f"  + {stage.name}: {_length(stage)}{extra}")
            continue
        changes = []
        if (before.seconds, before.ramp) != (stage.seconds, stage.ramp):
            changes.append(f"{_length(before)} -> {_length(stage)}")
        for key in sorted(set(before.to) | set(stage.to)):
            a, b = before.to.get(key), stage.to.get(key)
            if a != b:
                changes.append(f"to.{key} {'(unset)' if a is None else _number(a)} -> "
                               f"{'(unset)' if b is None else _number(b)}")
        if before.genre != stage.genre:
            changes.append(f"genre {before.genre or '(kept)'} -> {stage.genre or '(kept)'}")
        if before.curve != stage.curve:
            changes.append(f"curve {before.curve} -> {stage.curve}")
        other = [name for name in ("binaural", "layers", "drums", "transition")
                 if getattr(before, name) != getattr(stage, name)]
        if (before.phrases, before.phrase_every) != (stage.phrases, stage.phrase_every):
            other.append("phrases")
        if other:
            changes.append(f"{', '.join(other)} changed")
        if changes:
            lines.append(f"  ~ {stage.name}: {'; '.join(changes)}")
        else:
            lines.append(f"  = {stage.name}: {_length(stage)}")
    lines += [f"  - {stage.name}: {_length(stage)}" for stage in by_name.values()]
    return lines


BUILTIN: dict[str, Journey] = {j.name: j for j in (
    Journey("ambient-to-synthwave", (
        Stage("Dawn", 180, {"bpm": 60.0, "energy": 0.15, "brightness": 0.3, "space": 0.8, "lead_density": 0.2},
              genre="ambient", curve="ease-out", binaural={"carrier": 200.0, "beat": 6.0, "level": 0.05},
              layers={"drums": False, "lead": False, "counter": False}),
        Stage("Drift", 180, {"bpm": 68.0, "energy": 0.25, "brightness": 0.38, "lead_density": 0.4},
              curve="ease-in-out", layers={"lead": True}),
        Stage("Chillout", 240, {"bpm": 84.0, "energy": 0.45, "brightness": 0.5, "space": 0.55, "lead_density": 0.55},
              genre="lofi", transition=8, layers={"drums": True}),
        Stage("Lift", 180, {"bpm": 98.0, "energy": 0.62, "brightness": 0.6, "lead_density": 0.7},
              curve="ease-in-out", binaural={"level": 0.0}),
        Stage("Synthwave", 240, {"bpm": 112.0, "energy": 0.8, "brightness": 0.7, "space": 0.45, "lead_density": 0.8},
              genre="synthwave", transition=8, layers={"counter": True}),
        Stage("Peak", 180, {"bpm": 118.0, "energy": 0.95, "brightness": 0.78, "lead_density": 0.9}, curve="ease-out"),
    ), drums="energy", description="20 minutes from a still ambient dawn through lo-fi chillout to a synthwave peak at "
                                   "118 bpm, then sustains: parts enter stage by stage, the drums build with the "
                                   "energy, genres crossfade, and a 6 Hz binaural texture fades out before the lift"),
    Journey("warm-up", (
        Stage("Settle", 60, {"bpm": 60.0, "energy": 0.2, "brightness": 0.35, "lead_density": 0.3}),
        Stage("Wake", 180, {"bpm": 72.0, "energy": 0.45, "brightness": 0.5}),
        Stage("Rise", 240, {"bpm": 88.0, "energy": 0.7, "brightness": 0.65, "lead_density": 0.55}),
        Stage("Glow", 120, {"bpm": 100.0, "energy": 0.9, "brightness": 0.75, "lead_density": 0.7}),
    ), description="60 to 100 bpm and energy 0.2 to 0.9 over 10 minutes, then holds; the drums build with it",
       drums="energy"),
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
    return replace(journey, name=name, title=name)
