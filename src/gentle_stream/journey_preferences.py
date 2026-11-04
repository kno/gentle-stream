"""Local aggregate signals for journey recommendations; never stores prompts or listening history."""
from __future__ import annotations

import fcntl
import json
from pathlib import Path

from .genres import NAMES
from .journey import default_store_path
from .storage import write_json_atomic


class PreferenceError(Exception):
    """The local preference file cannot safely be read or written."""


class PreferenceStore:
    """Versioned, bounded genre scores; one explicit save outweighs a single stage skip."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path is not None else default_store_path().with_name("journey-preferences.json")

    def scores(self) -> dict[str, int]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeError, ValueError) as exc:
            raise PreferenceError(f"Cannot read preferences: {exc}") from exc
        scores = data.get("scores") if isinstance(data, dict) and data.get("version") == 1 else None
        if not isinstance(scores, dict) or any(k not in NAMES or type(v) is not int or not -100 <= v <= 100
                                               for k, v in scores.items()):
            raise PreferenceError("Cannot read preferences: unexpected format")
        return scores

    def _update(self, updates: dict[str, int] | None) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.with_suffix(".lock").open("a", encoding="utf-8") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                scores = self.scores()
                if updates is None:
                    scores = {}
                else:
                    for genre, delta in updates.items():
                        if genre in NAMES:
                            scores[genre] = max(-100, min(100, scores.get(genre, 0) + delta))
                write_json_atomic(self.path, {"version": 1, "scores": scores}, prefix=".preferences-")
        except OSError as exc:
            raise PreferenceError(f"Cannot write preferences: {exc}") from exc

    def saved(self, genres: list[str]) -> None:
        self._update(dict.fromkeys(genres, 4))

    def skipped(self, genre: str) -> None:
        self._update({genre: -1})

    def clear(self) -> None:
        self._update(None)
