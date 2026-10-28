"""Bring your own voices: folders of note-named WAV recordings that the choir sings (`gentle-stream voices`).

A voice pack is a folder with a `pack.json` and one WAV file per recorded note, named by the note (`A3.wav`,
`C#4.wav`, `Bb2-soft.wav`: the note is the start of the name). The manifest must say how the recordings may be used:

    {"name": "My Choir", "license": "CC0-1.0", "source": "my own recordings", "attribution": "Me",
     "redistributable": true, "root_note_from_filename": true, "vowel": "a", "melody": false}

A pack can also be an SFZ instrument, `"sfz": "choir.sfz"` (the subset in `sfz.py`, WAV samples only, sustain
loops held as long as a note lasts), or a SoundFont: `"sf2": "voices.sf2"` (relative to the folder, or absolute) with an optional
`"bank"` and `"program"` (default 0), rendered by FluidSynth (the `samples` extra) instead of WAV files.

`license` is required (a pack without one is refused); `melody: true` lets the choir sing the vocal melody with it
(PM-025), a listening decision left to whoever adds the pack. Packs are registered by path in
`$XDG_CONFIG_HOME/gentle-stream/voices.json`, never copied, and the last one added is the choir's voice.

A note is sung by the nearest recording, resampled to pitch. Within the recorded range and up to `MAX_SHIFT`
semitones from a recording the shift is exact; a note outside the range is folded by octaves into it, and a note
further than `MAX_SHIFT` from any recording takes the smallest shift that keeps it in tune. Both are reported once,
because resampling moves the formants too ("chipmunk").
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from scipy.io import wavfile

from . import samples
from .storage import write_json_atomic
from .synth import SR

if TYPE_CHECKING:
    from .sfz import Region

log = logging.getLogger(__name__)

MAX_SHIFT = 4                      # semitones a recording is resampled without a report
ATTACK = 0.005                     # seconds: no click at the start of a recording
RELEASE = 0.4                      # seconds a note rings past its length (as the choir's other voices)
VERSION = 1
NOTE_VELOCITY = 80                 # MIDI velocity the choir asks SF2 and SFZ packs for
SF2_VELOCITY = NOTE_VELOCITY       # and the velocity of the reference note SF2 notes are level-matched by
SF2_NEEDS = ("FluidSynth is needed for SF2 voice packs (install the FluidSynth library and the samples extra: "
             "uv sync --extra samples)")
UNSUPPORTED = (".flac", ".ogg", ".mp3", ".aif", ".aiff", ".m4a", ".opus")
NOTE = re.compile(r"^([A-Ga-g])([#b]?)(-?\d+)")
PITCH_CLASS = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}


class PackError(ValueError):
    """A voice pack that cannot be used; the message is meant for the terminal."""


def note_number(name: str) -> int:
    """MIDI number of a note name at the start of `name` ("A4" is 69, "C#3" 49, "Bb2" 46); ValueError if none."""
    m = NOTE.match(name)
    if m is None:
        raise ValueError(f"not a note name: {name}")
    letter, accidental, octave = m.groups()
    return (int(octave) + 1) * 12 + PITCH_CLASS[letter.lower()] + {"#": 1, "b": -1, "": 0}[accidental]


@dataclass(frozen=True)
class Pack:
    name: str
    path: Path
    license: str
    source: str = ""
    attribution: str = ""
    redistributable: bool = False
    vowel: str | None = None
    melody: bool = False
    notes: dict[int, Path] = field(default_factory=dict)   # recorded MIDI note -> WAV file
    sf2: Path | None = None                                 # an SF2 pack: its SoundFont, bank and program
    bank: int = 0
    program: int = 0
    sfz: Path | None = None                                 # an SFZ pack: its instrument file and regions
    regions: tuple[Region, ...] = ()


def _whole(data: dict, key: str, hi: int, manifest: Path) -> int:
    value = data.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= hi:
        raise PackError(f'{manifest}: "{key}" must be a whole number from 0 to {hi}')
    return value


def load_pack(folder: Path | str) -> Pack:
    """The pack in `folder`, validated: a manifest with a license and at least one note-named WAV file."""
    folder = Path(folder).expanduser()
    if not folder.is_dir():
        raise PackError(f"{folder} is not a folder")
    manifest = folder / "pack.json"
    if not manifest.is_file():
        raise PackError(f"{folder} has no pack.json")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise PackError(f"cannot read {manifest}: {e}") from e
    if not isinstance(data, dict):
        raise PackError(f"{manifest} must be a JSON object")
    license_ = data.get("license")
    if not isinstance(license_, str) or not license_.strip():
        raise PackError(f'{manifest} has no "license": every voice pack must say how its recordings may be used')
    def text(key: str) -> str:
        return " ".join(str(data.get(key) or "").split())

    vowel = data.get("vowel")
    base = Pack(name=text("name")[:40] or folder.name, path=folder, license=license_.strip(), source=text("source"),
                attribution=text("attribution"), redistributable=data.get("redistributable") is True,
                vowel=vowel if isinstance(vowel, str) and vowel else None, melody=data.get("melody") is True)
    if "sfz" in data:
        from . import sfz as sfz_format
        path = Path(str(data["sfz"])).expanduser()
        path = path if path.is_absolute() else folder / path
        if path.suffix.lower() != ".sfz":
            raise PackError(f'{manifest}: "sfz" must be an .sfz file ({path.name})')
        if not path.is_file():
            raise PackError(f"{manifest}: no such SFZ file: {path}")
        return replace(base, sfz=path, regions=sfz_format.parse(path).regions)
    if "sf2" in data:
        sf2 = Path(str(data["sf2"])).expanduser()
        sf2 = sf2 if sf2.is_absolute() else folder / sf2
        if sf2.suffix.lower() != ".sf2":
            raise PackError(f'{manifest}: "sf2" must be an .sf2 file ({sf2.name})')
        if not sf2.is_file():
            raise PackError(f"{manifest}: no such SF2 file: {sf2}")
        bank, program = _whole(data, "bank", 16383, manifest), _whole(data, "program", 127, manifest)
        if samples.fluidsynth_module() is None:
            raise PackError(SF2_NEEDS)
        return replace(base, sf2=sf2, bank=bank, program=program)
    if data.get("root_note_from_filename", True) is not True:
        raise PackError(f'{manifest}: only "root_note_from_filename": true is supported (name each file by its note)')
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() in UNSUPPORTED:
            raise PackError(f"unsupported format: convert to WAV ({f.name})")
    notes = {}
    for f in sorted(folder.iterdir()):
        if f.suffix.lower() != ".wav":
            continue
        try:
            notes.setdefault(note_number(f.stem), f)
        except ValueError:
            continue
    if not notes:
        raise PackError(f"{folder} has no note-named WAV files (name them by their note, e.g. A3.wav)")
    return replace(base, notes=notes)


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """A WAV file as mono float in [-1, 1] and its sample rate: 8/16/24/32-bit integer or float, mono or more."""
    try:
        sr, data = wavfile.read(path)
    except (OSError, ValueError) as e:
        raise PackError(f"cannot read {path.name}: {e}") from e
    if data.dtype == np.uint8:
        x = (data.astype(float) - 128) / 128
    elif np.issubdtype(data.dtype, np.integer):
        x = data.astype(float) / float(-np.iinfo(data.dtype).min)
    else:
        x = data.astype(float)
    if x.ndim > 1:
        x = x.mean(axis=1)
    return x, int(sr)


class PackVoice:
    """A pack ready to sing: `note(midi, seconds)` for the choir, recordings loaded and level-matched lazily."""

    def __init__(self, pack: Pack, sr: int = SR):
        self.pack, self.sr = pack, sr
        self._recordings: dict[int, tuple[np.ndarray, int]] = {}
        self._cache: dict[tuple[int, float], np.ndarray] = {}
        self._reported: set[int] = set()
        self._level: float | None = None
        self._renderer: samples.Renderer | None = None   # an SF2 pack's FluidSynth, loaded on the first note
        self._samples: dict[Path, tuple[np.ndarray, int]] = {}   # an SFZ pack's WAV samples, read on first use
        self.low, self.high = (min(pack.notes), max(pack.notes)) if pack.notes else (0, 127)

    def _recording(self, root: int) -> tuple[np.ndarray, int]:
        if root not in self._recordings:
            self._recordings[root] = read_wav(self.pack.notes[root])
        return self._recordings[root]

    def source(self, midi: int) -> tuple[int, int]:
        """(recorded note, semitone shift) that sings `midi`: always the same pitch class, the shift as small as
        the recordings allow (reported once when the note leaves the range or the shift exceeds MAX_SHIFT)."""
        target = midi
        while target > self.high + MAX_SHIFT:
            target -= 12
        while target < self.low - MAX_SHIFT:
            target += 12
        root = min(self.pack.notes, key=lambda r: (abs(target - r), r))
        shift = target - root
        if abs(shift) > MAX_SHIFT:           # a gap or a single recording: try the octaves around for a smaller shift
            target, root = min(((t, r) for t in (target - 12, target, target + 12) for r in self.pack.notes),
                               key=lambda tr: (abs(tr[0] - tr[1]), abs(tr[0] - midi), tr[1]))
            shift = target - root
        if midi not in self._reported and (target != midi or abs(shift) > MAX_SHIFT):
            self._reported.add(midi)
            if target != midi:
                log.warning('voice pack "%s": note %d is outside its recorded range (%d-%d); it sings %d instead',
                            self.pack.name, midi, self.low, self.high, target)
            else:
                log.warning('voice pack "%s": note %d is %d semitones from its nearest recording (%d); '
                            "it may sound unnatural", self.pack.name, midi, abs(shift), root)
        return root, shift

    def _render_sf2(self, midi: int, seconds: float) -> np.ndarray:
        assert self.pack.sf2 is not None
        if self._renderer is None:
            self._renderer = samples.load_renderer(self.pack.sf2, self.sr)
            if self._renderer is None:
                raise PackError(SF2_NEEDS)
        from .vocals import reference_rms
        p = samples.Program(self.pack.program, self.pack.bank, velocity=(SF2_VELOCITY, SF2_VELOCITY), tail=RELEASE,
                            rms=reference_rms(self.sr))
        x = self._renderer.note(0, p.bank, p.program, midi, SF2_VELOCITY, seconds, RELEASE)
        return samples._finish(x, self.sr) * samples._program_level(self._renderer, self.sr, p)

    def _sample(self, path: Path) -> tuple[np.ndarray, int]:
        if path not in self._samples:
            self._samples[path] = read_wav(path)
        return self._samples[path]

    def _region(self, midi: int):
        """The SFZ region that sings `midi` at NOTE_VELOCITY, or the zone nearest it (reported once)."""
        from .sfz import select
        region = select(self.pack.regions, midi, NOTE_VELOCITY)
        if region is not None:
            return region
        if midi not in self._reported:
            self._reported.add(midi)
            log.warning('voice pack "%s": no region plays note %d at velocity %d; the nearest one sings it',
                        self.pack.name, midi, NOTE_VELOCITY)
        return min(self.pack.regions, key=lambda r: max(r.lokey - midi, midi - r.hikey, 0))

    def _render_sfz(self, midi: int, seconds: float) -> np.ndarray:
        region = self._region(midi)
        x, file_sr = self._sample(region.sample)
        release = region.ampeg_release if region.ampeg_release is not None else RELEASE
        release = max(release, ATTACK)
        rate = 2 ** ((midi - region.pitch_keycenter + region.tune / 100) / 12) * file_sr / self.sr
        n = int((seconds + release) * self.sr)
        p = np.arange(n) * rate
        ran_out = False
        if region.loops and region.loop_end is not None:
            end = min(region.loop_end, len(x) - 1)
            start = min(region.loop_start, end - 1)
            span = end - start + 1
            p = np.where(p > end, start + np.mod(p - start, span), p)
            i0 = np.floor(p).astype(int)
            i1 = np.where(i0 >= end, start, i0 + 1)       # across the join, interpolate loop end -> loop start
        else:
            p = p[p <= len(x) - 1]
            ran_out = len(p) < n
            i0 = np.floor(p).astype(int)
            i1 = np.minimum(i0 + 1, len(x) - 1)
        frac = p - i0
        y = x[i0] * (1 - frac) + x[i1] * frac
        t = np.arange(len(y)) / self.sr
        env = np.clip(t / max(region.ampeg_attack, ATTACK), 0, 1) * np.clip(1 - (t - seconds) / release, 0, 1)
        k = min(len(y), int(0.01 * self.sr))
        if ran_out and k:                                   # a sample without a loop ends: fade to silence
            env[len(y) - k:] *= np.linspace(1, 0, k)
        return y * env * 10 ** (region.volume / 20) * self.level

    def _render(self, midi: int, seconds: float) -> np.ndarray:
        if self.pack.sf2 is not None:
            return self._render_sf2(midi, seconds)
        if self.pack.sfz is not None:
            return self._render_sfz(midi, seconds)
        root, shift = self.source(midi)
        x, file_sr = self._recording(root)
        rate = 2 ** (shift / 12) * file_sr / self.sr        # recording samples per output sample
        n = int((seconds + RELEASE) * self.sr)
        positions = np.arange(n) * rate
        positions = positions[positions <= len(x) - 1]
        y = np.interp(positions, np.arange(len(x)), x)
        t = np.arange(len(y)) / self.sr
        env = np.clip(t / ATTACK, 0, 1) * np.clip(1 - (t - seconds) / RELEASE, 0, 1)
        k = min(len(y), int(0.01 * self.sr))                 # a recording shorter than the note fades at its end
        if k:
            env[len(y) - k:] *= np.linspace(1, 0, k)
        return y * env * self.level

    @property
    def level(self) -> float:
        """Gain that gives the recording nearest middle C the RMS of the built-in choir's reference note."""
        if self._level is None:
            from .vocals import reference_rms
            if self.pack.sfz is not None:                    # the region nearest middle C, before its volume
                x, file_sr = self._sample(self._region(60).sample)
            else:
                root = min(self.pack.notes, key=lambda r: (abs(60 - r), r))
                x, file_sr = self._recording(root)
            head = x[: int(0.5 * file_sr)]
            rms = float(np.sqrt(np.mean(np.square(head)))) if len(head) else 0.0
            self._level = reference_rms(self.sr) / rms if rms > 1e-9 else 1.0
        return self._level

    def note(self, midi: int, seconds: float) -> np.ndarray:
        """`midi` sung for `seconds` (quarter-second buckets) plus a release, level-matched by RMS (not peak-limited:
        a recorded choir peaks higher than the built-in voice at the same loudness, as the soundfont's notes do)."""
        seconds = max(0.25, round(seconds * 4) / 4)
        key = (int(midi), seconds)
        if key not in self._cache:
            self._cache[key] = self._render(int(midi), seconds)
            if len(self._cache) > 512:
                self._cache.pop(next(iter(self._cache)))
        return self._cache[key]


# ---------------------------------------------------------------- the registry
def default_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "gentle-stream" / "voices.json"


class VoiceStore:
    """Registered packs (name and folder) and the active one, in `voices.json`, written atomically."""

    def __init__(self, path: Path | None = None):
        self.path = path or default_path()

    def _read(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": VERSION, "active": None, "packs": []}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise PackError(f"cannot read {self.path}: {e}") from e
        packs = [p for p in data.get("packs", []) if isinstance(p, dict) and "name" in p and "path" in p]
        return {"version": VERSION, "active": data.get("active"), "packs": packs}

    def add(self, folder: Path | str) -> tuple[Pack, bool]:
        """Register the pack in `folder` (validated first) and make it active; True when it replaced one."""
        pack = load_pack(folder)
        data = self._read()
        key = pack.name.casefold()
        replaced = any(p["name"].casefold() == key for p in data["packs"])
        data["packs"] = [p for p in data["packs"] if p["name"].casefold() != key]
        data["packs"].append({"name": pack.name, "path": str(pack.path)})
        data["active"] = pack.name
        write_json_atomic(self.path, data, prefix=".voices-")
        return pack, replaced

    def remove(self, name: str) -> str | None:
        """Unregister the pack called `name` (any case); its stored name, or None when there is none."""
        data = self._read()
        found = next((p for p in data["packs"] if p["name"].casefold() == name.casefold()), None)
        if found is None:
            return None
        data["packs"] = [p for p in data["packs"] if p is not found]
        if (data["active"] or "").casefold() == found["name"].casefold():
            data["active"] = None
        write_json_atomic(self.path, data, prefix=".voices-")
        return found["name"]

    def entries(self) -> list[tuple[str, Path, bool, Pack | PackError]]:
        """(name, folder, active, pack or the error that keeps it from loading) for every registered pack."""
        data = self._read()
        out = []
        for p in data["packs"]:
            try:
                loaded: Pack | PackError = load_pack(p["path"])
            except PackError as e:
                loaded = e
            out.append((p["name"], Path(p["path"]), p["name"] == data["active"], loaded))
        return out

    def active(self) -> Pack | None:
        """The active pack; raises PackError when it is registered but no longer loads."""
        data = self._read()
        entry = next((p for p in data["packs"] if p["name"] == data["active"]), None)
        return load_pack(entry["path"]) if entry is not None else None


def active_voice(sr: int = SR) -> PackVoice | None:
    """The active pack ready to sing, or None (no pack, or one that no longer loads: reported, the built-in
    choir sings instead)."""
    try:
        pack = VoiceStore().active()
    except PackError as e:
        log.warning("the active voice pack is unavailable (%s); the built-in choir sings instead", e)
        return None
    return PackVoice(pack, sr) if pack is not None else None


def added_message(pack: Pack, replaced: bool) -> str:
    """What `voices add` (and the TUI's voices dialog) says after registering `pack`."""
    return f'{"Replaced" if replaced else "Added"} voice pack "{pack.name}" ({pack.license}); the choir now sings it'


def list_lines(entries: list[tuple[str, Path, bool, Pack | PackError]]) -> list[str]:
    """The lines of `voices list` for `VoiceStore.entries()`, the active pack marked with *; shared with the TUI."""
    if not entries:
        return ["No voice packs. Add one with: gentle-stream voices add FOLDER"]
    lines = []
    for name, folder, active, loaded in entries:
        mark = "*" if active else " "
        if isinstance(loaded, PackError):
            lines.append(f"{mark} {name} · unavailable: {loaded}")
            continue
        parts = [f"license: {loaded.license}"]
        if loaded.attribution:
            parts.append(f"by {loaded.attribution}")
        if loaded.source:
            parts.append(f"source: {loaded.source}")
        if loaded.sfz is not None:
            parts.append(f"{loaded.sfz.name} ({len(loaded.regions)} regions)")
        if loaded.sf2 is not None:
            bank = f"bank {loaded.bank} " if loaded.bank else ""
            parts.append(f"{loaded.sf2.name} {bank}program {loaded.program}")
        lines.append(f"{mark} {loaded.name} · {' · '.join(parts)} · {folder}")
    return lines


def voices_command(action: str, target: str | None = None) -> int:
    """`gentle-stream voices add FOLDER | list | remove NAME`."""
    import sys

    store = VoiceStore()
    try:
        if action == "add":
            print(added_message(*store.add(str(target))))
            return 0
        if action == "remove":
            removed = store.remove(str(target))
            if removed is None:
                print(f'gentle-stream: no voice pack called "{target}"', file=sys.stderr)
                return 1
            print(f'Removed voice pack "{removed}"')
            return 0
        entries = store.entries()
    except PackError as e:
        print(f"gentle-stream: {e}", file=sys.stderr)
        return 1
    for line in list_lines(entries):
        print(line)
    return 0
