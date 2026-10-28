"""gentle-stream: real-time generative music in the terminal (lo-fi by default, plus nine more genres), steered by moods that Gentle Shell interprets."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
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
  lead_density, voice (the wordless choir) or bpm in place, without restarting the piece (a new mood or next
  cancels glides)
  gentle-stream ctl binaural on [--carrier HZ] [--beat HZ] [--level L] fades in an optional binaural texture
  under the music: a carrier - beat/2 tone on the left and carrier + beat/2 on the right (headphones; defaults
  200, 6, 0.05); ctl binaural set --beat 10 [--over SECONDS] glides only the values given; ctl binaural off
  fades it out (fades take 2 seconds; status shows "binaural": the setting or null)
  (status prints one JSON line, with "journey": the running journey's progress or null; the others exit 1 when
  nothing is playing).

journeys:
  gentle-stream journey play NAME runs a built-in journey in the background player: it moves tempo, energy and
  colour stage by stage on its own, then holds the last stage (or lets go). It owns the fields it moves: a new
  mood or next keeps it running. gentle-stream journey stop ends it; gentle-stream journey list shows them.
  While it runs the app shows: Journey: Warm-up · stage 2/4 "Wake" · 62% · 67 → 72 bpm · 7:08 left
  ("sustaining" instead of the time left once a journey holds its last stage).

render to a file:
  gentle-stream render [--seconds N] [--seed S] [--genre NAME] [--mood-file STYLE.json] [--journey NAME]
                       [--procedural] OUT.wav
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
        fields: dict[str, float] | None = None, binaural_request: tuple[str, dict[str, float]] | None = None) -> int:
    """`binaural_request` is (on|off|set, the --carrier/--beat/--level given) for `ctl binaural`."""
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
        style, journey = player.now.style, player.now.journey
        print(json.dumps({"running": True, "playing": player.playing, "name": style.name, "genre": style.genre,
                          "mood": style.mood, "bpm": player.bpm, "target_bpm": player.target_bpm,
                          "journey": journey.to_dict() if journey is not None else None,
                          "binaural": player.binaural.to_dict() if player.binaural is not None else None},
                         ensure_ascii=False))
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
    elif action == "binaural" and binaural_request is not None:   # main() has already validated the switch and values
        from .binaural import Binaural

        switch, values = binaural_request
        try:
            if switch == "set":
                player.glide_binaural(values, seconds)
            else:
                player.set_binaural(Binaural.from_dict(values) if switch == "on" else None, seconds)
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


def _journey_source(source: str):
    from .journey import BUILTIN, Journey, JourneyStore
    path = Path(source)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            warnings = []
            journey = Journey.from_dict(data, warnings, name=path.stem)
            return journey, warnings
        except (OSError, ValueError, json.JSONDecodeError) as e:
            raise ValueError(str(e)) from e
    builtin = next((journey for key, journey in BUILTIN.items() if key.casefold() == source.casefold()), None)
    if builtin is not None:
        return builtin, []
    saved = JourneyStore().get(source)
    if saved is not None:
        return saved, []
    if path.suffix.lower() == ".json" or "/" in source or "\\" in source:
        raise ValueError(f"cannot read {source}: file does not exist")
    raise ValueError(f'no journey called "{source}" (choose from {", ".join(BUILTIN)})')


def journey_command(action: str, name: str | None = None, *, prompt: str | None = None,
                    model: str | None = None, gentle_shell: str = "gentle-shell", dry_run: bool = False,
                    source: str | None = None, last: bool = False) -> int:
    """`journey play|create|save|delete|validate|show|list|restart|skip|stop` (the journey module is a package
    attribute). `create` is the only action that calls a model; `save` takes a journey file (`source`) or the last
    journey the background player started (`last`)."""
    from .journey import BUILTIN, Journey, JourneyStore, JourneyStoreError

    if action == "save":
        from .client import NoPlayer, PlayerError, PlayerGone, connect
        try:
            store = JourneyStore()
            if last:
                try:
                    player = connect()
                    data = player.journey_last()
                    player.detach()
                except NoPlayer:
                    print("gentle-stream: nothing is playing", file=sys.stderr)
                    return 1
                except PlayerGone:
                    print("gentle-stream: nothing is playing", file=sys.stderr)
                    return 1
                except PlayerError as e:
                    message = OLDER_PLAYER if "unknown command" in str(e) else str(e)
                    print(f"gentle-stream: {message}", file=sys.stderr)
                    return 1
                if data is None:
                    print("gentle-stream: no journey has been started yet", file=sys.stderr)
                    return 1
                warnings = []
                journey = Journey.from_dict(data, warnings)
            else:
                journey, warnings = _journey_source(str(source))
            stored, replaced = store.save(str(name), journey)
        except (JourneyStoreError, ValueError) as e:
            print(f"gentle-stream: {e}", file=sys.stderr)
            return 1
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
        print(f"{'Replaced' if replaced else 'Saved'} journey \"{stored}\"")
        return 0
    if action == "delete":
        if any(str(name).casefold() == builtin.casefold() for builtin in BUILTIN):
            print(f'gentle-stream: "{name}" is a built-in journey; it cannot be deleted.', file=sys.stderr)
            return 1
        store = JourneyStore()
        try:
            deleted = store.delete(str(name))
        except JourneyStoreError as e:
            print(f"gentle-stream: {e}", file=sys.stderr)
            return 1
        if not deleted:
            print(f'gentle-stream: no saved journey called "{name}"', file=sys.stderr)
            return 1
        print(f'Deleted journey "{name}"')
        return 0

    if action == "create":
        if prompt is None:
            print("gentle-stream: journey create requires a prompt", file=sys.stderr)
            return 1
        from .bridge import GentleShell, InterpretError
        shell = GentleShell(binary=gentle_shell, model=model)
        try:
            journey, usage = shell.journey_from_prompt(prompt)
            print(json.dumps(journey.to_dict(), ensure_ascii=False))
            if usage is not None:
                print(f"usage: {usage.format()}", file=sys.stderr)
            if dry_run:
                return 0
            from .client import NoPlayer, PlayerError, PlayerGone, connect
            try:
                player = connect()
            except NoPlayer:
                print("gentle-stream: nothing is playing", file=sys.stderr)
                return 1
            except PlayerError as e:
                print(f"gentle-stream: {e}", file=sys.stderr)
                return 1
            try:
                player.journey_start(journey.to_dict())
            except PlayerGone:
                print("gentle-stream: nothing is playing", file=sys.stderr)
                return 1
            except PlayerError as e:
                message = OLDER_PLAYER if "unknown command" in str(e) else str(e)
                print(f"gentle-stream: {message}", file=sys.stderr)
                return 1
            player.detach()
            return 0
        except (InterpretError, ValueError) as e:
            print(f"gentle-stream: {e}", file=sys.stderr)
            return 1
    if action in ("validate", "show"):
        try:
            journey, warnings = _journey_source(str(name))
        except ValueError as e:
            print(f"gentle-stream: {e}", file=sys.stderr)
            return 1
        print(json.dumps(journey.to_dict(), ensure_ascii=False))
        if action == "validate":
            for warning in warnings:
                print(f"warning: {warning}", file=sys.stderr)
        return 0
    if action == "list":
        store = JourneyStore()
        saved = store.list()
        width = max([*map(len, BUILTIN), *(len(name) for name, _ in saved)], default=1)
        for j in BUILTIN.values():
            print(f"{j.name:<{width}}  {j.description}")
        for saved_name, journey in saved:
            minutes = journey.seconds / 60
            print(f"{saved_name:<{width}}  {len(journey.stages)} stages, {minutes:g} minutes")
        if store.error:
            print(f"gentle-stream: {store.error}", file=sys.stderr)
        return 0
    parsed_journey = None
    if action == "play":
        try:
            parsed_journey, _ = _journey_source(str(name))
        except ValueError as e:
            print(f"gentle-stream: {e}", file=sys.stderr)
            return 1
    from .client import NoPlayer, PlayerError, PlayerGone, connect

    try:
        player = connect()
    except NoPlayer:
        print("gentle-stream: nothing is playing", file=sys.stderr)
        return 1
    except PlayerError as e:
        print(f"gentle-stream: {e}", file=sys.stderr)
        return 1
    try:
        if action == "play" and parsed_journey is not None:
            player.journey_start(parsed_journey.to_dict())
        elif action == "restart":
            player.journey_restart()
        elif action == "skip":
            player.journey_skip()
        else:
            player.journey_stop()
    except PlayerGone:
        print("gentle-stream: nothing is playing", file=sys.stderr)
        return 1
    except PlayerError as e:
        if 'unknown command' in str(e):
            print(f"gentle-stream: {OLDER_PLAYER}", file=sys.stderr)
        else:
            print(f"gentle-stream: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"gentle-stream: {e}", file=sys.stderr)
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
           procedural: bool, journey_name: str | None = None) -> int:
    """Render `seconds` of music with the engine alone into a 16-bit stereo WAV at `out`, running the built-in
    journey `journey_name` from the first bar when given."""
    import secrets
    from dataclasses import replace

    import numpy as np
    from scipy.io import wavfile

    from .engine import Engine
    from .journey import BUILTIN
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
    from .voicepacks import active_voice

    engine = Engine(style, seed=seed, samples=not procedural, voices=None if procedural else active_voice())
    if journey_name is not None:
        engine.queue_journey(BUILTIN[journey_name])
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
    suffix = f", journey {journey_name}" if journey_name else ""
    print(f"wrote {out}: {seconds:g} s, {style.genre}, seed {seed}{suffix}")
    return 0


def _number(text: str) -> float | None:
    try:
        value = float(text)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _ctl_args(parser: argparse.ArgumentParser, args) -> tuple[float | None, float, dict[str, float] | None]:
    """(bpm, seconds, fields) for `ctl`, or a usage error (exit 2) before the player is contacted."""
    if any(value is not None for value in (args.carrier, args.beat, args.level)):
        parser.error("--carrier, --beat and --level are only for binaural")
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


def _binaural_args(parser: argparse.ArgumentParser, args) -> tuple[tuple[str, dict[str, float]], float]:
    """((on|off|set, the values given), seconds) for `ctl binaural`, or a usage error (exit 2) before the player is
    contacted. Values a `set` leaves out keep what the layer plays; the ones `on` leaves out take the defaults."""
    from .binaural import Binaural

    if args.args not in (["on"], ["off"], ["set"]):
        parser.error("binaural requires on, off or set")
    switch = args.args[0]
    values = {name: getattr(args, name) for name in ("carrier", "beat", "level") if getattr(args, name) is not None}
    if not math.isfinite(args.over) or not 0 <= args.over <= 3600:
        parser.error("--over must be between 0 and 3600 seconds")
    if switch == "off" and values:
        parser.error("binaural off takes no --carrier, --beat or --level")
    if switch == "set" and not values:
        parser.error("binaural set requires --carrier, --beat or --level")
    try:
        Binaural.from_dict(values)   # each given value in its range
    except ValueError as e:
        parser.error(f"invalid binaural setting: {e}")
    return (switch, values), args.over


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
                                               "glide", "binaural"))
    ctl_parser.add_argument("args", nargs="*", metavar="ARG",
                            help="tempo: BPM; glide: FIELD=VALUE...; binaural: on, off or set")
    ctl_parser.add_argument("--over", type=float, default=60.0, metavar="SECONDS",
                            help="tempo, glide, binaural on/set while it plays: seconds to reach the target, 0-3600 "
                                 "(default: 60)")
    ctl_parser.add_argument("--carrier", type=float, metavar="HZ",
                            help="binaural on/set: the carrier tone, 40-1000 Hz (default: 200)")
    ctl_parser.add_argument("--beat", type=float, metavar="HZ",
                            help="binaural on/set: the difference between the ears, 0.5-40 Hz (default: 6)")
    ctl_parser.add_argument("--level", type=float, metavar="L",
                            help="binaural on/set: the level of each tone, 0-0.08 (default: 0.05)")
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
    render_parser.add_argument("--journey", metavar="NAME", help="run a built-in journey from the start "
                                                                 "(see `journey list`)")
    render_parser.add_argument("--procedural", action="store_true",
                               help="use the procedural instruments even if the soundfont is installed")
    journey_parser = sub.add_parser("journey", help="create, manage, and play journeys",
                                    description="Create, validate, save, list, delete, show, and play journeys.")
    journey_sub = journey_parser.add_subparsers(dest="journey_action", metavar="action", required=True)
    journey_sub.add_parser("play", help="start a journey (it replaces a running one)").add_argument(
        "name", metavar="NAME|FILE", help="a built-in journey or JSON file")
    journey_sub.add_parser("validate", help="validate and normalize a JSON journey file").add_argument("name", metavar="FILE")
    journey_sub.add_parser("show", help="show a normalized journey or JSON file").add_argument("name", metavar="NAME|FILE")
    journey_sub.add_parser("stop", help="end the journey, leaving the music as it is")
    journey_sub.add_parser("restart", help="restart the journey from its first stage")
    journey_sub.add_parser("skip", help="advance the journey to its next stage")
    journey_sub.add_parser("list", help="list built-in and saved journeys")
    save_parser = journey_sub.add_parser("save", help="save a journey file or the last started journey")
    save_parser.add_argument("name", metavar="NAME")
    source = save_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("file", nargs="?", metavar="FILE")
    source.add_argument("--last", action="store_true", help="save the last journey started by the player")
    delete_parser = journey_sub.add_parser("delete", help="delete a saved journey")
    delete_parser.add_argument("name", metavar="NAME")
    create_parser = journey_sub.add_parser("create", help="create a journey from a text prompt")
    create_parser.add_argument("prompt", metavar="PROMPT", help="a text description of the journey you want")
    create_parser.add_argument("--dry-run", action="store_true", help="print without starting")
    voices_parser = sub.add_parser("voices", help="add, list, and remove voice packs the choir sings",
                                   description="Voice packs: folders of note-named WAV recordings with a pack.json "
                                               "that states their license. The last pack added is the choir's "
                                               "voice; packs are registered by path, never copied.")
    voices_sub = voices_parser.add_subparsers(dest="voices_action", metavar="action", required=True)
    voices_sub.add_parser("add", help="register a pack folder and make it the choir's voice").add_argument(
        "target", metavar="FOLDER")
    voices_sub.add_parser("list", help="list packs with their license and attribution (* the active one)")
    voices_sub.add_parser("remove", help="unregister a pack; the built-in choir sings again").add_argument(
        "target", metavar="NAME")
    args = ap.parse_args(argv)
    if args.command == "ctl":
        if args.action == "binaural":
            request, seconds = _binaural_args(ctl_parser, args)
            return ctl("binaural", seconds=seconds, binaural_request=request)
        return ctl(args.action, *_ctl_args(ctl_parser, args))
    if args.command == "journey":
        return journey_command(args.journey_action, getattr(args, "name", None),
                              prompt=getattr(args, "prompt", None), model=args.model,
                              gentle_shell=args.gentle_shell, dry_run=getattr(args, "dry_run", False),
                              source=getattr(args, "file", None), last=getattr(args, "last", False))
    if args.command == "voices":
        from .voicepacks import voices_command

        return voices_command(args.voices_action, getattr(args, "target", None))
    if args.command == "render":
        from .style import genre_names

        if args.genre is not None and args.genre not in genre_names():
            render_parser.error(f"invalid genre {args.genre!r} (choose from {', '.join(genre_names())})")
        from .journey import BUILTIN

        if args.journey is not None and args.journey not in BUILTIN:
            render_parser.error(f"invalid journey {args.journey!r} (choose from {', '.join(BUILTIN)})")
        return render(args.out, args.seconds, args.seed, args.genre, args.mood_file, args.procedural, args.journey)
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
