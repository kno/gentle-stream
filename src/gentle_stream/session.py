"""Where the music was, so a stop and a start come back to it (S11): the style that played, the journey at the same
moment, the volume, the binaural layer, mute and live. Saved atomically in `$XDG_CONFIG_HOME/gentle-stream/session.json`
on stop and every few seconds while playing (a crash resumes too); `gentle-stream --fresh` forgets it."""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

from .storage import write_json_atomic

VERSION = 1
SAVE_EVERY = 10.0      # seconds between saves while playing
log = logging.getLogger(__name__)


def path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "gentle-stream" / "session.json"


def save(snapshot: dict) -> None:
    write_json_atomic(path(), snapshot, prefix=".session-")


def load() -> dict | None:
    """The saved session, or None (none saved, unreadable, or from another version)."""
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("version") == VERSION and isinstance(data.get("style"), dict) \
        else None


def clear() -> None:
    path().unlink(missing_ok=True)


class Autosave:
    """Saves `player.session()` every `every` seconds until `stop()`, which saves once more."""

    def __init__(self, player, every: float = SAVE_EVERY):
        self.player, self.every = player, every
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="gentle-stream-session", daemon=True)
        self._thread.start()

    def _save(self) -> None:
        try:
            save(self.player.session())
        except Exception as e:  # noqa: BLE001  (a full disk must not stop the music)
            log.warning("cannot save the session: %s", e)

    def _run(self) -> None:
        while not self._stop.wait(self.every):
            self._save()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(2)
        self._save()


def autosave(player, every: float = SAVE_EVERY) -> Autosave:
    return Autosave(player, every)
