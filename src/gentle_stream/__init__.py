"""gentle-stream: real-time generative music in the terminal (lo-fi by default, plus nine more genres), steered by moods that Gentle Shell interprets."""
from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Any, cast

CONTROLS = """controls:
  space    play / pause
  n        next piece with the same mood
  /        describe a mood (feeling, concept, place...), Enter to send, Esc to leave
  m        choose the model Gentle Shell uses
  s        save what is playing under a name (prompt and style)
  p        saved prompts: Enter applies one instantly, d deletes it
  + / -    volume up / down by 5%
  ↑ / ↓    volume up / down by 1%
  b        back: leave the app, the music keeps playing
  q        quit and stop the music

background playback:
  the music plays in a background player; gentle-stream attaches to it when it is already playing.
  gentle-stream ctl play|pause|toggle|next|stop|status controls it from any terminal
  gentle-stream ctl tempo BPM [--over SECONDS] glides the live tempo (default: 60 seconds)
  gentle-stream ctl glide FIELD=VALUE... [--over SECONDS] glides energy, brightness, space, swing, vinyl,
  lead_density or bpm in place, without restarting the piece (a new mood or next cancels glides)
  (status prints one JSON line; the others exit 1 when nothing is playing).

render to a file:
  gentle-stream render [--seconds N] [--seed S] [--genre NAME] [--mood-file STYLE.json] [--procedural] OUT.wav
  writes N seconds (default: 60) as 16-bit stereo WAV, without a player or an audio device.

saved prompts live in $XDG_CONFIG_HOME/gentle-stream/presets.json (default ~/.config/gentle-stream/).

sampled instruments (optional):
  gentle-stream setup-samples downloads the FluidR3_GM soundfont (MIT) once into the user cache;
  with FluidSynth installed it replaces the procedural instruments. Nothing is downloaded otherwise."""


def setup_samples() -> int:
    from . import samples

    print(f"downloading FluidR3_GM (MIT, Frank Wen / Toby Smithe) from {samples.DEB_URL}")

    def progress(done: int, total: int | None) -> None:
        mb = done / 1e6
        line = f"  {mb:6.1f} MB" if not total else f"  {100 * done // total:3d}%  {mb:6.1f} / {total / 1e6:.1f} MB"
        print("\r" + line, end="", flush=True)

    try:
        sf2 = samples.setup_samples(progress=progress)
    except samples.SetupError as e:
        print()
        print(f"gentle-stream: setup-samples failed: {e}", file=sys.stderr)
        return 1
    print()
    print(f"installed {sf2} (SHA-256 verified; license: {sf2.parent / samples.LICENSES_NAME})")
    if samples.fluidsynth_module() is None:
        print("note: FluidSynth or pyfluidsynth is missing, so the procedural instruments stay in use "
              "(brew install fluid-synth; uv sync --extra samples)")
    return 0


OLDER_PLAYER = ("the running player is older than this gentle-stream; run `gentle-stream ctl stop` and "
                "start again")


def ctl(action: str, bpm: float | None = None, seconds: float = 60.0,
        fields: dict[str, float] | None = None) -> int:
    from .client import NoPlayer, PlayerError, PlayerGone, connect

    try:
        player = connect()
    except NoPlayer:
        if action == "status":
            print(json.dumps({"running": False}))
            return 0
        print("gentle-stream: nothing is playing", file=sys.stderr)
        return 1
    except PlayerError as e:
        print(f"gentle-stream: {e}", file=sys.stderr)
        return 1
    if action == "status":
        style = player.now.style
        print(json.dumps({"running": True, "playing": player.playing, "name": style.name, "genre": style.genre,
                          "mood": style.mood, "bpm": player.bpm, "target_bpm": player.target_bpm}, ensure_ascii=False))
    elif action in ("tempo", "glide"):
        try:
            if action == "tempo" and bpm is not None:   # main() has already required BPM for tempo
                player.tempo(bpm, seconds)
            elif action == "glide" and fields:          # and at least one FIELD=VALUE for glide
                player.glide(fields, seconds)
        except PlayerGone:
            print("gentle-stream: nothing is playing", file=sys.stderr)
            return 1
        except PlayerError as e:
            print(f"gentle-stream: {OLDER_PLAYER if 'unknown command' in str(e) else e}", file=sys.stderr)
            return 1
    elif action == "stop":
        player.close()
        return 0
    else:
        try:
            player.request(action)
        except PlayerGone:
            print("gentle-stream: nothing is playing", file=sys.stderr)
            return 1
    player.detach()
    return 0


RENDER_SECONDS = 60.0       # default length of `render`
MAX_RENDER_SECONDS = 3600.0


def _render_seconds(text: str) -> float:
    value = _number(text)
    if value is None or not 0 < value <= MAX_RENDER_SECONDS:
        raise argparse.ArgumentTypeError(f"must be a number above 0 and at most {MAX_RENDER_SECONDS:g}, "
                                         f"got {text!r}")
    return value


def _seed(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = -1
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be a non-negative integer, got {text!r}")
    return value


def render(out: str, seconds: float, seed: int | None, genre: str | None, mood_file: str | None,
           procedural: bool) -> int:
    """Render `seconds` of music with the engine alone into a 16-bit stereo WAV at `out`."""
    import secrets
    from dataclasses import replace

    import numpy as np
    from scipy.io import wavfile

    from .engine import Engine
    from .style import Style

    style = Style()
    if mood_file is not None:
        try:
            with open(mood_file, encoding="utf-8") as f:
                data = json.load(f)
        except OSError as e:
            print(f"gentle-stream: cannot read {mood_file}: {e.strerror}", file=sys.stderr)
            return 1
        except ValueError:   # not JSON, or not UTF-8 text
            data = None
        if not isinstance(data, dict):
            print(f"gentle-stream: {mood_file}: not a JSON style object", file=sys.stderr)
            return 1
        style = Style.from_dict(data)
    if genre is not None:
        style = replace(style, genre=genre)
    seed = secrets.randbelow(2 ** 31) if seed is None else seed   # printed, so any render can be repeated
    engine = Engine(style, seed=seed, samples=not procedural)
    frames = max(1, int(round(seconds * engine.sr)))   # any length above 0 writes at least one frame
    try:
        with open(out, "wb") as f:   # opened first: a long render must not end in a path error
            bars, done = [], 0
            while done < frames:
                bars.append(engine.render_bar())
                done += len(bars[-1])
            audio = np.clip(np.concatenate(bars)[:frames], -1, 1)   # the last bar trimmed to the exact length
            wavfile.write(f, engine.sr, np.round(audio * 32767).astype(np.int16))
    except OSError as e:
        print(f"gentle-stream: cannot write {out}: {e.strerror}", file=sys.stderr)
        return 1
    print(f"wrote {out}: {seconds:g} s, {style.genre}, seed {seed}")
    return 0


def _number(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _ctl_args(parser: argparse.ArgumentParser, args) -> tuple[float | None, float, dict[str, float] | None]:
    """(bpm, seconds, fields) for `ctl`, or a usage error (exit 2) before the player is contacted."""
    if args.action not in ("tempo", "glide"):
        if args.args:
            parser.error(f"{args.action} takes no arguments")
        return None, args.over, None
    if not math.isfinite(args.over) or not 0 <= args.over <= 3600:
        parser.error("--over must be between 0 and 3600 seconds")
    if args.action == "tempo":
        if len(args.args) != 1:
            parser.error("tempo requires BPM")
        if (bpm := _number(args.args[0])) is None:
            parser.error(f"invalid BPM: {args.args[0]!r}")
        return bpm, args.over, None
    from .engine import GLIDE_FIELDS

    if not args.args:
        parser.error("glide requires FIELD=VALUE")
    fields: dict[str, float] = {}
    for item in args.args:
        name, sep, text = item.partition("=")
        if not sep or name not in GLIDE_FIELDS or name in fields:
            parser.error(f"invalid glide {item!r}: use FIELD=VALUE once per field, FIELD one of "
                         f"{', '.join(GLIDE_FIELDS)}")
        if (value := _number(text)) is None:
            parser.error(f"invalid glide {item!r}: the value must be a number")
        fields[name] = value
    return None, args.over, fields


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["daemon"]:   # the background player, started by the TUI; not listed in --help
        from .daemon import main as daemon_main

        return daemon_main(argv[1:])
    ap = argparse.ArgumentParser(prog="gentle-stream", description=__doc__, epilog=CONTROLS,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", help="model Gentle Shell uses to interpret moods, as provider/id "
                                    "(default: Gentle Shell's default model)")
    ap.add_argument("--mood", help="mood to interpret as soon as the app starts")
    ap.add_argument("--gentle-shell", default="gentle-shell", metavar="PATH",
                    help="gentle-shell executable (default: %(default)s)")
    sub = ap.add_subparsers(dest="command", metavar="command")
    sub.add_parser("setup-samples", help="download the FluidR3_GM soundfont (MIT) for sampled instruments, once")
    ctl_parser = sub.add_parser("ctl", help="control the music playing in the background")
    ctl_parser.add_argument("action", choices=("play", "pause", "toggle", "next", "stop", "status", "tempo",
                                               "glide"))
    ctl_parser.add_argument("args", nargs="*", metavar="ARG", help="tempo: BPM; glide: FIELD=VALUE...")
    ctl_parser.add_argument("--over", type=float, default=60.0, metavar="SECONDS",
                            help="tempo and glide: seconds to reach the target, 0-3600 (default: 60)")
    render_parser = sub.add_parser("render", help="render music into a 16-bit stereo WAV file (no audio device)",
                                   description="Render music offline with the engine alone into a WAV file.")
    render_parser.add_argument("out", metavar="OUT.wav", help="the WAV file to write")
    render_parser.add_argument("--seconds", type=_render_seconds, default=RENDER_SECONDS, metavar="N",
                               help=f"length, above 0 and at most {MAX_RENDER_SECONDS:g} (default: "
                                    f"{RENDER_SECONDS:g})")
    render_parser.add_argument("--seed", type=_seed, help="seed for the piece (default: random, printed)")
    render_parser.add_argument("--genre", metavar="NAME", help="genre, overriding the mood file's")
    render_parser.add_argument("--mood-file", metavar="STYLE.json",
                               help="a style as JSON (the fields of a saved prompt's style)")
    render_parser.add_argument("--procedural", action="store_true",
                               help="use the procedural instruments even if the soundfont is installed")
    args = ap.parse_args(argv)
    if args.command == "ctl":
        return ctl(args.action, *_ctl_args(ctl_parser, args))
    if args.command == "render":
        from .style import genre_names

        if args.genre is not None and args.genre not in genre_names():
            render_parser.error(f"invalid genre {args.genre!r} (choose from {', '.join(genre_names())})")
        return render(args.out, args.seconds, args.seed, args.genre, args.mood_file, args.procedural)
    if args.command == "setup-samples":
        from . import samples

        if (sf2 := samples.soundfont_path()) is not None:
            print(f"FluidR3_GM already installed: {sf2} (license: {sf2.parent / samples.LICENSES_NAME})")
            return 0
        return setup_samples()

    from .app import StreamApp
    from .bridge import GentleShell
    from .client import AudioError, PlayerError, ensure

    try:
        player = ensure()   # attach to the music already playing, or start the background player
    except AudioError as e:  # PortAudio missing, no output device, device busy...
        print(f"gentle-stream: cannot open the audio output: {e}", file=sys.stderr)
        return 1
    except PlayerError as e:
        print(f"gentle-stream: {e}", file=sys.stderr)
        return 1
    StreamApp(cast(Any, player), GentleShell(binary=args.gentle_shell, model=args.model), initial_mood=args.mood).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
