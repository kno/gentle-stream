"""The SFZ subset voice packs read (PM-029): enough of the format for free vocal libraries, WAV samples only.

Headers `<control>`, `<global>`, `<group>` and `<region>`; a region takes its group's opcodes, the group its global
ones, and the region's own win. Supported opcodes: `sample`, `lokey`, `hikey`, `key` (sets lokey, hikey and
pitch_keycenter), `pitch_keycenter`, `lovel`, `hivel`, `tune` (cents), `volume` (dB), `ampeg_attack`,
`ampeg_release` (seconds), `loop_mode` (`no_loop`, `one_shot`, `loop_continuous`, `loop_sustain`), `loop_start`,
`loop_end` (samples), `default_path` in `<control>`, and `#define $NAME value`. Keys are MIDI numbers or note names
with middle C at `c4`. `//` and `/* */` comments are skipped. Anything else is ignored and reported once per file.

A region loops between `loop_start` and `loop_end` when its loop mode is `loop_continuous` or `loop_sustain`, or
when it gives loop points and no mode. Everything here only parses and selects; `voicepacks.PackVoice` plays it.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .voicepacks import PackError

log = logging.getLogger(__name__)

HEADERS = ("control", "global", "group", "region")
KEYS = ("lokey", "hikey", "pitch_keycenter")
INTS = ("lovel", "hivel", "loop_start", "loop_end")
FLOATS = ("tune", "volume", "ampeg_attack", "ampeg_release")
LOOP_MODES = ("no_loop", "one_shot", "loop_continuous", "loop_sustain")
SUPPORTED = {"sample", "key", "loop_mode", "default_path", *KEYS, *INTS, *FLOATS}
OPCODE = re.compile(r"(?:(?<=\s)|^)([A-Za-z_][A-Za-z0-9_]*)=")
NOTE = re.compile(r"^([a-gA-G])([#b]?)(-?\d+)$")
PITCH_CLASS = {"c": 0, "d": 2, "e": 4, "f": 5, "g": 7, "a": 9, "b": 11}


def key(value: str) -> int:
    """A MIDI key from an SFZ value: a number, or a note name with middle C at c4 ("c#4" 61, "db4" 61)."""
    value = value.strip()
    if re.fullmatch(r"-?\d+", value):
        number = int(value)
    else:
        m = NOTE.match(value)
        if m is None:
            raise ValueError(value)
        letter, accidental, octave = m.groups()
        number = (int(octave) + 1) * 12 + PITCH_CLASS[letter.lower()] + {"#": 1, "b": -1, "": 0}[accidental]
    if not 0 <= number <= 127:
        raise ValueError(value)
    return number


@dataclass(frozen=True)
class Region:
    sample: Path
    lokey: int = 0
    hikey: int = 127
    pitch_keycenter: int = 60
    lovel: int = 1
    hivel: int = 127
    tune: float = 0.0
    volume: float = 0.0
    ampeg_attack: float = 0.0
    ampeg_release: float | None = None
    loop_mode: str | None = None
    loop_start: int = 0
    loop_end: int | None = None

    @property
    def loops(self) -> bool:
        """Whether a held note repeats `loop_start`..`loop_end` (inclusive) until it is released."""
        if self.loop_end is None or self.loop_end <= self.loop_start:
            return False
        return self.loop_mode in (None, "loop_continuous", "loop_sustain")

    def plays(self, key: int, vel: int) -> bool:
        return self.lokey <= key <= self.hikey and self.lovel <= vel <= self.hivel


@dataclass(frozen=True)
class Instrument:
    path: Path
    regions: tuple[Region, ...] = field(default_factory=tuple)

    def region(self, key: int, vel: int) -> Region | None:
        return select(self.regions, key, vel)


def select(regions: tuple[Region, ...], key: int, vel: int) -> Region | None:
    """The first region that plays `key` at velocity `vel`, in file order (as SFZ players pick a single layer)."""
    return next((r for r in regions if r.plays(key, vel)), None)


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.DOTALL)   # keep line numbers
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.split("\n"))


def _value(name: str, raw: str, where: str):
    try:
        if name in KEYS or name == "key":
            return key(raw)
        if name in INTS:
            number = int(raw)
            if number < 0 or (name in ("lovel", "hivel") and not 1 <= number <= 127):
                raise ValueError(raw)
            return number
        if name in FLOATS:
            number = float(raw)
            if name.startswith("ampeg") and number < 0:
                raise ValueError(raw)
            return number
        if name == "loop_mode":
            if raw not in LOOP_MODES:
                raise ValueError(raw)
            return raw
    except ValueError:
        raise PackError(f"{where}: {name}={raw} is not valid") from None
    return raw


def parse(path: Path | str) -> Instrument:
    """The instrument in the SFZ file at `path`: every region with its inherited opcodes and its WAV sample."""
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        raise PackError(f"cannot read {path}: {e}") from e
    defines: dict[str, str] = {}
    sections: dict[str, dict] = {"control": {}, "global": {}, "group": {}}
    regions: list[tuple[dict, int]] = []
    current: dict | None = None
    unsupported: set[str] = set()
    for number, line in enumerate(_strip_comments(text).split("\n"), start=1):
        where = f"{path}: line {number}"
        stripped = line.strip()
        if stripped.startswith("#define"):
            parts = stripped.split(None, 2)
            if len(parts) == 3 and parts[1].startswith("$"):
                defines[parts[1]] = parts[2].strip()
            continue
        if stripped.startswith("#"):
            unsupported.add(stripped.split()[0])
            continue
        for name in sorted(defines, key=len, reverse=True):   # $LONGER before $LONG
            line = line.replace(name, defines[name])
        for chunk in re.split(r"(<[A-Za-z_]+>)", line):
            header = re.fullmatch(r"<([A-Za-z_]+)>", chunk)
            if header:
                name = header.group(1).lower()
                if name == "region":
                    current = dict(sections["global"], **sections["group"])
                    regions.append((current, number))
                elif name in sections:
                    if name == "group":
                        sections["group"] = {}
                    current = sections[name]
                else:
                    unsupported.add(f"<{name}>")
                    current = {}
                continue
            matches = list(OPCODE.finditer(chunk))
            for i, m in enumerate(matches):
                end = matches[i + 1].start() if i + 1 < len(matches) else len(chunk)
                name, raw = m.group(1), chunk[m.end():end].strip()
                if name not in SUPPORTED:
                    unsupported.add(name)
                    continue
                if current is None:
                    current = sections["global"]
                value = _value(name, raw, where)
                if name == "key":
                    current.update(lokey=value, hikey=value, pitch_keycenter=value)
                else:
                    current[name] = value
    if unsupported:
        log.warning("%s: unsupported opcodes ignored: %s", path, ", ".join(sorted(unsupported)))
    if not regions:
        raise PackError(f"{path} has no <region>")
    default_path = str(sections["control"].get("default_path", "")).replace("\\", "/")
    out = []
    for opcodes, number in regions:
        sample = opcodes.pop("sample", None)
        opcodes.pop("default_path", None)
        if not sample:
            raise PackError(f"{path}: line {number}: a <region> needs a sample")
        file = path.parent / default_path / str(sample).replace("\\", "/")
        if file.suffix.lower() != ".wav":
            raise PackError(f"unsupported format: convert to WAV ({file.name})")
        if not file.is_file():
            raise PackError(f"{path}: line {number}: no such sample: {file}")
        out.append(Region(sample=file, **opcodes))
    return Instrument(path, tuple(out))
