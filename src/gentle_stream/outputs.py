"""The audio outputs the player can play on (S8), and the one chosen, remembered in
`$XDG_CONFIG_HOME/gentle-stream/output.json` for the next start. None means the system default."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .storage import write_json_atomic


class OutputError(ValueError):
    """An output that does not exist; the message is meant for the terminal."""


@dataclass(frozen=True)
class Output:
    index: int          # the device number PortAudio knows it by
    name: str
    channels: int       # output channels it offers (headphones in hands-free mode: 1)
    default: bool       # the system default output


def _query() -> tuple[list[dict], int | None]:
    """PortAudio's devices and the default output's index (testing seam); nothing without PortAudio."""
    try:
        import sounddevice as sd

        devices = [dict(d) for d in sd.query_devices()]
        default = sd.default.device[1]
    except Exception:  # noqa: BLE001  (no PortAudio, no devices: no outputs, the player plays silently)
        return [], None
    return devices, (default if isinstance(default, int) and default >= 0 else None)


def available() -> list[Output]:
    devices, default = _query()
    return [Output(i, str(d["name"]), int(d["max_output_channels"]), i == default)
            for i, d in enumerate(devices) if int(d.get("max_output_channels", 0)) > 0]


def default() -> Output | None:
    return next((o for o in available() if o.default), None)


def find(name: str) -> Output | None:
    """The output called `name` (exactly, else ignoring case)."""
    found = available()
    return next((o for o in found if o.name == name), None) or \
        next((o for o in found if o.name.casefold() == name.casefold()), None)


def unknown(name: str) -> OutputError:
    return OutputError(f'no audio output called "{name}" (see gentle-stream ctl output)')


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "gentle-stream" / "output.json"


def saved() -> str | None:
    try:
        name = json.loads(config_path().read_text(encoding="utf-8")).get("name")
    except (OSError, ValueError, AttributeError):
        return None
    return name if isinstance(name, str) and name else None


def save(name: str | None) -> None:
    """Remember `name` for the next start (None: follow the system default)."""
    if name is None:
        config_path().unlink(missing_ok=True)
    else:
        write_json_atomic(config_path(), {"version": 1, "name": name}, prefix=".output-")
