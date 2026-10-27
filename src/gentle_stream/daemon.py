"""The background player: one process per user that owns Engine + Player + the audio output, so the music keeps
playing after the TUI leaves.

It is started automatically (`gentle-stream daemon`, spawned by `client.ensure`) and never by hand. It listens on a
Unix domain socket in a private runtime dir (`$XDG_RUNTIME_DIR/gentle-stream`, default
`$XDG_CACHE_HOME/gentle-stream/run`, mode 0700) through `multiprocessing.connection`, authenticated with a random
key kept in a 0600 file. Messages are JSON (never pickle), one request and one response per call:

    {"cmd": "state", "bands": 48}   -> {"ok": true, "state": {...}}   (spectrum included when bands > 0; "journey"
                                     is the audible bar's journey progress, journey.JourneySnapshot.to_dict(), or
                                     null without a journey)
    {"cmd": "play" | "pause" | "toggle" | "next"}
    {"cmd": "set_volume", "volume": 0.5}
    {"cmd": "set_style", "style": {...Style.to_dict()...}}
    {"cmd": "glide", "fields": {"energy": 0.9, "brightness": 0.8}, "seconds": 120}
                                     (continuous fields only, see engine.GLIDE_FIELDS; one bad field rejects all)
    {"cmd": "tempo", "bpm": 110, "seconds": 60}   (a bpm glide)
    {"cmd": "journey_start", "name": "warm-up"}   (a built-in journey, see journey.BUILTIN, from the next bar; it
                                     replaces a running one; an unknown name answers {"ok": false, "error":
                                     "no journey called ..."} listing the built-ins)
    {"cmd": "journey_last"}          -> {"ok": true, "journey": {...} | null} (last started journey)
    {"cmd": "journey_stop"}          (leaves the music as it is; fine when no journey runs)
    {"cmd": "stop"}                  -> {"ok": true}, then the process exits and every connection sees EOF
    anything else                    -> {"ok": false, "error": "..."}

A `flock` on `player.lock` (which holds the pid) keeps one player per user; the lock holder replaces a socket left
by a crashed player. Startup is reported to the spawner as one JSON line on `--ready-fd`: `{"ready": true}`,
`{"running": true}` (another player holds the lock) or `{"error": "...", "audio": bool}`.
"""
from __future__ import annotations

import argparse
import fcntl
import importlib
import json
import math
import os
import secrets
import signal
import stat
import sys
import threading
from dataclasses import dataclass
from multiprocessing.connection import Listener
from pathlib import Path

AUDIO_FACTORY_ENV = "GENTLE_STREAM_AUDIO_FACTORY"   # testing seam: "module:attr" replaces sounddevice.OutputStream
MAX_BANDS = 512


class RuntimeDirError(Exception):
    """The runtime dir is not private to this user."""


@dataclass(frozen=True)
class Paths:
    dir: Path

    @property
    def sock(self) -> Path:
        return self.dir / "player.sock"

    @property
    def key(self) -> Path:
        return self.dir / "authkey"

    @property
    def lock(self) -> Path:
        return self.dir / "player.lock"

    @property
    def log(self) -> Path:
        return self.dir / "player.log"


def runtime_dir() -> Path:
    if base := os.environ.get("XDG_RUNTIME_DIR"):
        return Path(base) / "gentle-stream"
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "gentle-stream" / "run"


def check_private(path: Path) -> None:
    """Refuse a runtime dir owned by someone else; tighten one that is group or world accessible."""
    st = path.lstat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        raise RuntimeDirError(f"{path} is not a directory owned by this user")
    if stat.S_IMODE(st.st_mode) != 0o700:
        os.chmod(path, 0o700)


def prepare() -> Paths:
    """The runtime dir, created private if missing."""
    path = runtime_dir()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    check_private(path)
    return Paths(path)


def authkey(paths: Paths) -> bytes:
    """The shared key, created once (0600, never replaced while it exists)."""
    try:
        fd = os.open(paths.key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return paths.key.read_bytes()
    key = secrets.token_bytes(32)
    with os.fdopen(fd, "wb") as f:
        f.write(key)
    return key


def _stream_factory():
    spec = os.environ.get(AUDIO_FACTORY_ENV)
    if not spec:
        return None
    module, _, attr = spec.partition(":")
    return getattr(importlib.import_module(module), attr)


def state(player, bands: int = 0) -> dict:
    now = player.now
    out = {
        "pid": os.getpid(),
        "playing": bool(player.playing),
        "volume": float(player.volume),
        "level": float(player.level),
        "backend": player.engine.backend,
        "now": {"style": now.style.to_dict(), "piece": now.piece, "bar": now.bar,
                 "start_seconds": now.start_seconds},
        "style": player.style.to_dict(),
        "elapsed_seconds": player.elapsed_seconds,
        "cycle_remaining_seconds": player.cycle_remaining_seconds,
        "bpm": now.style.bpm,
        "target_bpm": player.engine.target_bpm,
        "journey": now.journey.to_dict() if now.journey is not None else None,
    }
    if bands > 0:
        out["spectrum"] = [round(float(v), 4) for v in player.spectrum_levels(min(bands, MAX_BANDS))]
    return out


def _finite(value, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{what} must be a finite number")
    return float(value)


def _seconds(request) -> float:
    seconds = _finite(request["seconds"], "seconds")
    if not 0 <= seconds <= 3600:
        raise ValueError("seconds must be between 0 and 3600")
    return seconds


def _glide_fields(fields) -> dict[str, float]:
    """Validated glide fields; any unknown or discrete field or bad value rejects the whole request."""
    from .engine import GLIDE_FIELDS

    if not isinstance(fields, dict) or not fields:
        raise TypeError("fields must be a non-empty object")
    unknown = [name for name in fields if name not in GLIDE_FIELDS]
    if unknown:
        raise ValueError(f"cannot glide {', '.join(map(repr, unknown))}: only {', '.join(GLIDE_FIELDS)}")
    return {name: _finite(value, name) for name, value in fields.items()}


def handle(player, request) -> dict:
    """Run one request against the player; bad requests get an error answer, never an exception."""
    from .style import Style

    try:
        cmd = request["cmd"]
        if cmd == "state":
            return {"ok": True, "state": state(player, int(request.get("bands", 0)))}
        if cmd in ("play", "pause", "toggle", "next"):
            getattr(player, cmd)()
        elif cmd == "set_volume":
            player.set_volume(float(request["volume"]))
        elif cmd == "tempo":
            bpm = _finite(request["bpm"], "bpm")
            player.engine.queue_tempo(bpm, _seconds(request))
        elif cmd == "glide":
            fields = _glide_fields(request["fields"])
            player.engine.queue_glide(fields, _seconds(request))
        elif cmd == "journey_start":
            from .journey import Journey

            if "journey" in request:
                journey = request["journey"]
                if not isinstance(journey, dict):
                    raise TypeError("journey must be an object")
                normalized = Journey.from_dict(journey)
                player.last_journey = normalized.to_dict()
                player.engine.queue_journey(normalized)
            else:  # compatibility with the PM-004 name payload; never interpret paths here
                from .journey import BUILTIN, unknown_journey
                name = request["name"]
                if not isinstance(name, str):
                    raise TypeError("name must be a string")
                if name not in BUILTIN:
                    return {"ok": False, "error": unknown_journey(name)}
                player.engine.queue_journey(BUILTIN[name])
        elif cmd == "journey_last":
            return {"ok": True, "journey": getattr(player, "last_journey", None)}
        elif cmd == "journey_stop":
            player.engine.stop_journey()
        elif cmd == "journey_restart":
            player.engine.restart_journey()
        elif cmd == "journey_skip":
            player.engine.skip_journey()
        elif cmd == "set_style":
            if not isinstance(request["style"], dict):
                raise TypeError("style must be an object")
            player.set_style(Style.from_dict(request["style"]))
        elif cmd == "stop":
            return {"ok": True}
        else:
            raise ValueError(f"unknown command {cmd!r}")
    except ValueError as e:
        from .engine import JourneyControlError, JourneyDriven

        if isinstance(e, (JourneyDriven, JourneyControlError)):
            return {"ok": False, "error": str(e)}
        return {"ok": False, "error": f"bad request: {e}"}
    except (KeyError, TypeError) as e:
        return {"ok": False, "error": f"bad request: {e}"}
    return {"ok": True, "state": state(player)}


class Server:
    def __init__(self, player, listener: Listener):
        self.player, self.listener = player, listener
        self.stopping = threading.Event()

    def accept_forever(self) -> None:
        while not self.stopping.is_set():
            try:
                conn = self.listener.accept()
            except Exception:  # a client that fails authentication or hangs up early; the listener stays up
                if self.stopping.is_set():
                    return
                continue
            threading.Thread(target=self.serve, args=(conn,), daemon=True, name="gentle-stream-client").start()

    def serve(self, conn) -> None:
        with conn:
            while True:
                try:
                    raw = conn.recv_bytes()
                except (EOFError, OSError):
                    return
                try:
                    request = json.loads(raw)
                    answer = handle(self.player, request if isinstance(request, dict) else {})
                except ValueError:
                    request, answer = {}, {"ok": False, "error": "bad request: not JSON"}
                try:
                    conn.send_bytes(json.dumps(answer).encode())
                except OSError:
                    return
                if answer["ok"] and request.get("cmd") == "stop":
                    self.stopping.set()


def _reporter(fd: int | None):
    def report(message: dict) -> None:
        line = json.dumps(message) + "\n"
        if fd is None:
            if not message.get("ready"):
                sys.stderr.write(line)
            return
        try:
            os.write(fd, line.encode())
            os.close(fd)
        except OSError:
            pass   # the spawner gave up waiting

    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gentle-stream daemon", description="internal: the background player")
    ap.add_argument("--ready-fd", type=int, help="pipe on which startup is reported as one JSON line")
    args = ap.parse_args(argv)
    report = _reporter(args.ready_fd)
    try:
        paths = prepare()
        lock = os.fdopen(os.open(paths.lock, os.O_RDWR | os.O_CREAT, 0o600), "r+")
    except (OSError, RuntimeDirError) as e:
        report({"error": str(e), "audio": False})
        return 1
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        report({"running": True})
        return 0
    lock.truncate(0)
    lock.write(str(os.getpid()))
    lock.flush()

    from .engine import Engine
    from .player import Player

    try:
        factory = _stream_factory()
        player = Player(Engine(), **({"stream_factory": factory} if factory else {}))
    except Exception as e:
        report({"error": f"cannot start the player: {e}", "audio": False})
        return 1
    try:
        player.start()
    except Exception as e:  # PortAudio missing, no output device, device busy...
        player.close()
        report({"error": str(e), "audio": True})
        return 1
    try:
        key = authkey(paths)
        if paths.sock.is_socket() or paths.sock.exists():
            paths.sock.unlink()   # left by a crashed player: we hold the lock, so nobody listens on it
        listener = Listener(str(paths.sock), family="AF_UNIX", authkey=key)
    except OSError as e:
        player.close()
        report({"error": f"cannot listen on {paths.sock}: {e}", "audio": False})
        return 1

    server = Server(player, listener)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: server.stopping.set())
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    threading.Thread(target=server.accept_forever, daemon=True, name="gentle-stream-accept").start()
    report({"ready": True})
    while not server.stopping.wait(0.5):
        pass
    player.close()
    listener.close()   # also removes the socket file
    return 0
