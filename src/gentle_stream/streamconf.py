"""Where a live broadcast goes (PM-045): the ingest URL and the stream key, kept apart.

The URL (`rtmps://a.rtmps.youtube.com/live2`) is not a secret and lives in `$XDG_CONFIG_HOME/gentle-stream/stream.json`.
The key is: it lets anyone stream to the channel. It is read only from stdin (`gentle-stream stream key set`), never
from the command line where `ps` shows it, and kept in `stream.key` next to it, created with mode 0600 and refused, as
ssh refuses keys, when others can read it; or in the environment variable GENTLE_STREAM_KEY, which wins. It travels as
a StreamKey, whose text never shows the value, so a log line or an error message cannot carry it by accident.
"""
from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from .storage import write_json_atomic

KEY_ENV = "GENTLE_STREAM_KEY"
MAX_KEY = 256
EXAMPLE_URL = "rtmps://a.rtmps.youtube.com/live2"
BAD_URL = (f"the ingest URL must be rtmp:// or rtmps:// with a host and no credentials, query or fragment, "
           f"e.g. {EXAMPLE_URL}")


class StreamConfigError(Exception):
    """Something about the URL or the key is missing or unsafe; the message never holds the key."""


class StreamKey:
    """The stream key: `reveal()` gives the value to the one place that sends it; any other text shows a mask."""

    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "StreamKey(<hidden>)"

    __str__ = __repr__   # f-strings and % formatting go through str(): masked too


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "gentle-stream"


def key_path() -> Path:
    return config_dir() / "stream.key"


def url_path() -> Path:
    return config_dir() / "stream.json"


# ---------------------------------------------------------------- the key
def check_key(text: str) -> str:
    """The key in `text` (surrounding whitespace dropped), or StreamConfigError."""
    key = text.strip()
    if not key:
        raise StreamConfigError("no stream key read from stdin")
    if len(key) > MAX_KEY or any(c.isspace() or not c.isprintable() for c in key):
        raise StreamConfigError(f"a stream key is one line of printable characters without spaces, at most {MAX_KEY}")
    return key


def save_key(text: str) -> Path:
    """Write the key to `stream.key` with mode 0600, atomically (a same-directory temporary file, also 0600)."""
    key = check_key(text)
    path = key_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".stream-key-", suffix=".tmp")   # created 0600
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(key)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


def clear_key() -> Path | None:
    """Remove the saved key; its path, or None when there was none."""
    path = key_path()
    try:
        path.unlink()
    except FileNotFoundError:
        return None
    return path


def _unsafe(path: Path) -> str | None:
    """Why the key file must not be used, or None."""
    info = path.stat()
    if info.st_uid != os.getuid():
        return f"{path} is not yours; remove it and run `gentle-stream stream key set`"
    if stat.S_IMODE(info.st_mode) & 0o077:
        return f"{path} can be read by others; run: chmod 600 {path}"
    return None


def load_key() -> StreamKey:
    """The key from GENTLE_STREAM_KEY or `stream.key`; StreamConfigError when there is none or the file is unsafe."""
    if (env := os.environ.get(KEY_ENV)) is not None:
        try:
            return StreamKey(check_key(env))
        except StreamConfigError:
            raise StreamConfigError(f"{KEY_ENV} does not hold a valid stream key") from None
    path = key_path()
    if not path.is_file():
        raise StreamConfigError(f"no stream key: run `gentle-stream stream key set` and paste it, or set {KEY_ENV}")
    if (why := _unsafe(path)) is not None:
        raise StreamConfigError(why)
    try:
        return StreamKey(check_key(path.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, StreamConfigError):
        raise StreamConfigError(f"{path} does not hold a valid stream key; run `gentle-stream stream key set`") \
            from None


# ---------------------------------------------------------------- the URL
def check_url(url: str) -> str:
    try:
        parts = urlsplit(url.strip())
        ok = (parts.scheme in ("rtmp", "rtmps") and bool(parts.hostname) and parts.username is None
              and parts.password is None and not parts.query and not parts.fragment
              and parts.path.strip("/") != "" and not url.strip().endswith("?") and "#" not in url)
        _ = parts.port   # raises ValueError on a bad port
    except ValueError:
        ok = False
    if not ok:
        raise StreamConfigError(BAD_URL)
    return url.strip()


def save_url(url: str) -> str:
    url = check_url(url)
    write_json_atomic(url_path(), {"version": 1, "url": url}, prefix=".stream-")
    return url


def load_url() -> str | None:
    import json

    try:
        data = json.loads(url_path().read_text(encoding="utf-8"))
        return check_url(data["url"])
    except (OSError, ValueError, KeyError, TypeError, StreamConfigError):
        return None


# ---------------------------------------------------------------- the CLI
def show_lines() -> list[str]:
    """What `gentle-stream stream show` prints: the URL and whether a key is set, never the key."""
    url = load_url()
    lines = [f"ingest URL: {url}" if url else "ingest URL: not set (gentle-stream stream url URL)"]
    path = key_path()
    if os.environ.get(KEY_ENV) is not None:
        lines.append(f"stream key: set (environment variable {KEY_ENV})")
    elif not path.is_file():
        lines.append("stream key: not set (gentle-stream stream key set, from stdin)")
    elif (why := _unsafe(path)) is not None:
        lines.append(f"stream key: {why}")
    else:
        lines.append(f"stream key: set (in {path})")
    return lines


def read_key_from_stdin() -> str:
    """The pasted key: without echo when stdin is a terminal, else all of stdin."""
    import sys

    if sys.stdin.isatty():
        import getpass

        return getpass.getpass("Stream key (not shown): ")
    return sys.stdin.read()


def stream_command(action: str, key_action: str | None = None, url: str | None = None) -> int:
    """`gentle-stream stream key set|clear | url URL | show`."""
    import sys

    try:
        if action == "key" and key_action == "set":
            print(f"Stream key saved in {save_key(read_key_from_stdin())} (readable only by you)")
        elif action == "key":
            removed = clear_key()
            print(f"Stream key removed from {removed}" if removed else "No stream key saved")
        elif action == "url":
            print(f"Ingest URL saved: {save_url(url or '')}")
        else:
            for line in show_lines():
                print(line)
    except StreamConfigError as e:
        print(f"gentle-stream: {e}", file=sys.stderr)
        return 1
    return 0
