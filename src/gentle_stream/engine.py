"""Real-time synthesis engine.

Renders one bar at a time: notes are scheduled into an accumulation buffer (their tails ring into later bars) and
the finished bar goes through a master chain whose filters and delay lines keep state between bars, so consecutive
bars join seamlessly and the stream can run forever.

What plays in each bar (song form, harmony, melody, counter-melody, bass line) comes from `composer.Composer`; how
it sounds comes from the style's genre (`genres`, lo-fi by default): its voices (procedural, or sampled once
`gentle-stream setup-samples` has installed the FluidR3_GM soundfont, `samples.SampleInstruments`), its rhythmic
treatment and drum patterns, and its master-chain settings (convolution reverb, room, vinyl, tape wow, tone, bus
compressor from `mastering`, final tape saturation). Style changes and "next" requests are queued from any thread
and applied at the next bar boundary.

Live glides (`queue_glide`, `queue_tempo`) move the continuous fields of the playing style (`GLIDE_FIELDS`) in
place, one linear glide per field over the rendered seconds of the piece: no new piece, the form keeps going. Each
bar takes the values at its start, so tempo is constant within a bar. A new style or "next" cancels every glide.
Genres that derive something from these fields once per piece in `start` keep the start value (e.g. chiptune's
arpeggio division follows the bpm the piece started with).

A journey (`queue_journey`, see `journey.py`) moves the same fields through the same in-place path: before each bar
the engine evaluates it at its rendered seconds since the journey started (so pausing playback pauses it) and sets
the fields it owns. A new style or "next" keeps it running: the new piece starts with the journey's values. Journey
time is rendered time, so "next" also moves it on by the audio that was buffered and dropped (up to about a
second). The journey drives the fields it owns: when it starts it cancels their glides, and while it runs (or is
queued) a glide of any of them is refused (`JourneyDriven`), so when it stops or releases nothing takes over and the
music stays where it left it. Each bar rendered during a journey leaves a `journey_snapshot` of its progress for the
player to pass along.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from . import genres
from . import samples as _samples
from .binaural import Binaural, BinauralLayer, glide_seconds
from .composer import Composer
from .genres.base import Piece
from .genres.lofi import Instruments  # noqa: F401  (re-exported: the procedural lo-fi voices)
from .mastering import Compressor, ConvolutionReverb, procedural_ir, soft_clip
from .style import DEFAULT, KEYS, Style
from .synth import SR, StatefulFilter, _sos, bp, hp, lp, mtof  # noqa: F401  (re-exported)

if TYPE_CHECKING:
    from .journey import Journey, JourneySnapshot

IR_SEED = 1
RAMP = 0.05   # seconds over which a changed master gain glides to its new value
# the continuous style fields a live glide may move, with their bounds (as `Style.from_dict` clamps them)
GLIDE_FIELDS = {"bpm": (50.0, 140.0), "energy": (0.0, 1.0), "brightness": (0.0, 1.0), "space": (0.0, 1.0),
                "swing": (0.0, 0.3), "vinyl": (0.0, 1.0), "lead_density": (0.0, 1.0)}
MAX_GLIDE_SECONDS = 3600.0


@dataclass(frozen=True)
class _Glide:
    """One field's glide. Queued with only a target and a duration; the render thread fills in where and from what
    value it starts at the first bar boundary after queueing, so no other thread reads the playing style."""
    target: float
    duration: float
    start: float = 0.0    # piece seconds at the first bar it applies to
    source: float = 0.0   # the field's value at that bar
    started: bool = False

    def at(self, seconds: float) -> float:
        if self.duration == 0:
            return self.target
        return self.source + (self.target - self.source) * min(1.0, max(0.0, (seconds - self.start) / self.duration))


@dataclass(frozen=True)
class _Running:
    """The journey playing: where on the rendered timeline it started, and from which values."""
    journey: Journey
    start_sample: int
    start: dict[str, float]
    binaural_start: dict[str, float] | None = None   # where its binaural values start, when it owns the layer


class JourneyDriven(ValueError):
    """A glide of a field the running or queued journey drives; the message is meant for the terminal."""


class JourneyControlError(ValueError):
    """A control error on a journey; the message is meant for the terminal."""


def _bounded(name: str, value: float) -> float:
    lo, hi = GLIDE_FIELDS[name]
    value = float(np.clip(float(value), lo, hi))
    return round(value, 1) if name == "bpm" else value


@lru_cache(maxsize=16)
def _ir(space_tenths: int, sr: int) -> np.ndarray:
    return procedural_ir(space_tenths / 10, sr, IR_SEED)


# ---------------------------------------------------------------- engine
class Engine:
    HEADROOM = 24.0  # seconds of scheduling buffer: longest bar plus the longest note tail

    def __init__(self, style: Style = DEFAULT, seed: int | None = None, sr: int = SR,
                 samples: bool | str | Path = True):
        """`samples`: True uses the installed soundfont when FluidSynth is available, a path uses that soundfont,
        False keeps the procedural instruments. Anything unavailable falls back to procedural."""
        self.sr = sr
        sf2 = _samples.soundfont_path() if samples is True else (Path(samples) if samples else None)
        renderer = _samples.load_renderer(sf2, sr) if sf2 is not None else None
        self._sampled = _samples.SampleInstruments(renderer, np.random.default_rng(0), sr) if renderer else None
        self._lock = threading.Lock()
        self._pending_style: Style | None = None
        self._pending_next = False
        self._glides: dict[str, _Glide] = {}   # live glides by field; replaced, never mutated, under _lock
        self._journey_queued = False            # a journey command waits for the next bar (under _lock)
        self._pending_journey: Journey | None = None   # what it starts, or None to stop
        self._journey_control: str | None = None  # restart or skip, applied at the next rendered bar
        self._binaural_queued = False           # a binaural setting waits for the next bar (under _lock)
        self._pending_binaural: tuple[Binaural | None, float] = (None, 0.0)   # the setting (None: off), glide
        self._binaural = BinauralLayer(sr)      # render thread only
        self._driving: Journey | None = None    # the journey playing, as other threads may see it (under _lock)
        self._running: _Running | None = None   # the journey playing; render thread only
        self._snapshot: JourneySnapshot | None = None   # its progress at the bar rendered last
        self._rendered: tuple[Journey, float] | None = None   # its journey and seconds at the end of that bar
        self.piece_seconds = 0.0
        self._last_bar_start = 0.0   # piece seconds at the start of the bar rendered last
        self._root_rng = np.random.default_rng(seed)
        self._acc = np.zeros((int(self.HEADROOM * sr), 2))
        self.samples_out = 0
        self.piece = 0
        # master chain state
        self._room_taps = ((.031, .28), (.057, .24), (.083, .2), (.127, .17), (.191, .13), (.263, .1), (.347, .07))
        self._room_hist = np.zeros((int(0.36 * sr), 2))
        self._room_lp = StatefulFilter(_sos("lowpass", 2600, 0, sr), 2)
        self._wow_hist = np.zeros((int(0.006 * sr), 2))
        self._crackle_hp = StatefulFilter(_sos("highpass", 1500, 0, sr), 2)
        self._hiss_lp = StatefulFilter(_sos("lowpass", 6000, 0, sr), 2)
        self._tone_cut = None
        self._tone_lp: StatefulFilter | None = None
        self._send_hp = StatefulFilter(_sos("highpass", 180, 0, sr), 2)
        self._ir_space: int | None = None
        self._reverb: ConvolutionReverb | None = None
        self._comp = Compressor(sr)
        self._last: dict[str, float] = {}   # master gains of the previous bar (see `_glide`)
        self._start_piece(style)

    # ------------------------------------------------------------ control (any thread)
    def queue_style(self, style: Style) -> None:
        """Play `style` from the next bar on (a new piece)."""
        with self._lock:
            self._pending_style, self._pending_next = style, False
            self._glides = {}

    def queue_glide(self, fields: dict[str, float], seconds: float) -> None:
        """Glide each named field of the playing style to its value over `seconds`, in place (no new piece), from
        the next bar boundary on. Values and `seconds` are clamped; a field already gliding gets the new glide,
        the others keep theirs. Raises ValueError, applying nothing, if any field is not in GLIDE_FIELDS, and
        JourneyDriven (a ValueError) if the journey that drives the next bar owns any of them."""
        unknown = sorted(set(fields) - set(GLIDE_FIELDS))
        if unknown or not fields:
            raise ValueError(f"cannot glide {', '.join(map(repr, unknown))}" if unknown else "no fields to glide")
        seconds = float(np.clip(float(seconds), 0, MAX_GLIDE_SECONDS))
        new = {name: _Glide(_bounded(name, value), seconds) for name, value in fields.items()}
        with self._lock:
            driver = self._pending_journey if self._journey_queued else self._driving
            driven = [name for name in fields if driver is not None and name in driver.fields]
            if driver is not None and driven:
                raise JourneyDriven(f'{driven[0]} is driven by the journey "{driver.name}"; stop it first '
                                    f"(gentle-stream journey stop)")
            self._glides = {**self._glides, **new}

    def queue_tempo(self, bpm: float, seconds: float) -> None:
        """Glide tempo in place: `queue_glide({"bpm": bpm}, seconds)`."""
        self.queue_glide({"bpm": bpm}, seconds)

    def queue_binaural(self, setting: Binaural | None, seconds: float = 0.0) -> None:
        """From the next rendered bar, head for `setting`, gliding over `seconds` (0-3600) when the layer already
        plays; turning it on fades it in and None fades it out (see `binaural`)."""
        seconds = glide_seconds(seconds)
        with self._lock:
            driver = self._pending_journey if self._journey_queued else self._driving
            if driver is not None and driver.owns_binaural:
                raise JourneyDriven(f'binaural is driven by the journey "{driver.name}"; stop it first '
                                    f"(gentle-stream journey stop)")
            self._pending_binaural, self._binaural_queued = (setting, seconds), True

    @property
    def binaural(self) -> Binaural | None:
        """The binaural setting the layer is heading to, queued or rendering, or None when it is off or fading out."""
        with self._lock:
            if self._binaural_queued:
                return self._pending_binaural[0]
            return self._binaural.setting

    def queue_journey(self, journey: Journey) -> None:
        """Run `journey` from the next bar on, starting from the values playing then; it replaces a running one
        and, when it starts, cancels the glides of the fields it owns."""
        with self._lock:
            self._journey_queued, self._pending_journey = True, journey

    def stop_journey(self) -> None:
        """Drop the running journey (or a queued one) at the next bar, leaving the music as it is."""
        with self._lock:
            self._journey_queued, self._pending_journey = True, None
            self._journey_control = None

    def restart_journey(self) -> None:
        """Restart the running journey at the next bar."""
        self._queue_journey_control("restart")

    def skip_journey(self) -> None:
        """Advance the running journey to its next stage at the next bar."""
        self._queue_journey_control("skip")

    def _queue_journey_control(self, action: str) -> None:
        with self._lock:
            if self._driving is None:
                raise JourneyControlError("no journey is running")
            if action == "skip" and self._snapshot is not None and self._snapshot.stage == self._snapshot.stages:
                raise JourneyControlError("already at the final journey stage")
            self._journey_control = action

    @property
    def journey(self) -> Journey | None:
        """The journey of the bar rendered last (None while its first bar renders)."""
        rendered = self._rendered
        return rendered[0] if rendered is not None else None

    @property
    def journey_seconds(self) -> float | None:
        """Rendered seconds of the journey up to the end of the bar rendered last."""
        rendered = self._rendered
        return rendered[1] if rendered is not None else None

    @property
    def journey_snapshot(self) -> JourneySnapshot | None:
        """The journey's progress at the start of the bar rendered last (None without a journey). Made by
        `render_bar` from the same journey and time as that bar's values; read it on the rendering thread right
        after `render_bar`, as the player does under its render lock."""
        return self._snapshot

    @property
    def targets(self) -> dict[str, float]:
        """The target of every glide still running (or queued), by field."""
        with self._lock:
            return {name: g.target for name, g in self._glides.items()}

    @property
    def target_bpm(self) -> float | None:
        return self.targets.get("bpm")

    def queue_next(self) -> None:
        """Start a new piece with the same mood from the next bar on."""
        with self._lock:
            if self._pending_style is None:
                self._pending_next = True
            self._glides = {}

    @property
    def backend(self) -> str:
        return "procedural" if self._sampled is None else "samples"

    @property
    def bar_seconds(self) -> float:
        return 240.0 / self.style.bpm

    # ------------------------------------------------------------ piece setup
    def _start_piece(self, style: Style, skip_intro: bool = False) -> None:
        self.style = style
        self.piece_seconds = 0.0
        self.genre = genres.get(style.genre)
        self.seed = int(self._root_rng.integers(2 ** 31))
        self.rng = np.random.default_rng(self.seed)
        self.inst = self.genre.instruments(self.rng, self.sr, self._sampled)
        self.piece += 1
        self.bar = 0
        ton = 48 + KEYS.index(style.key)
        self.ton = ton - 12 if ton > 54 else ton
        self.composer = Composer(style, self.seed, self.ton, self.genre.chord, skip_intro=skip_intro)
        self.section = self.composer.plan(0).section
        self._piece = Piece(style, self.rng, self.inst, self.ton, self.sr, self._acc)
        self.genre.start(self._piece)

    # ------------------------------------------------------------ rendering
    def render_bar(self) -> np.ndarray:
        """Render the next bar as float32 stereo samples of shape (n, 2)."""
        with self._lock:
            style, nxt = self._pending_style, self._pending_next
            queued, journey, control = self._journey_queued, self._pending_journey, self._journey_control
            self._pending_style, self._pending_next = None, False
            self._journey_queued, self._pending_journey, self._journey_control = False, None, None
            binaural_queued, binaural = self._binaural_queued, self._pending_binaural
            self._binaural_queued, self._pending_binaural = False, (None, 0.0)
            if queued:   # a journey starts or stops here; one that starts takes over its fields from any glide
                self._driving = journey
                if journey is not None:
                    self._glides = {name: g for name, g in self._glides.items() if name not in journey.fields}
        if binaural_queued:   # before a journey starts here, so it starts from the layer as it now plays
            self._binaural.set(*binaural)
        if queued and journey is None:
            self._running = None
        running = self._running
        if running is not None and control == "restart":
            running = replace(running, start_sample=self.samples_out)
            self._running = running
        elif running is not None and control == "skip":
            index, _, _ = running.journey.at((self.samples_out - running.start_sample) / self.sr, running.start)
            next_start = running.journey._ends[index]
            running = replace(running, start_sample=self.samples_out - round(next_start * self.sr))
            self._running = running
        t = (self.samples_out - running.start_sample) / self.sr if running is not None else 0.0
        values = self._journey_values(running, t)   # owned by the journey: a new piece starts with them
        stage_index = running.journey.at(t, running.start)[0] if running is not None else None
        target_genre = (running.journey.stages[int(stage_index)].genre
                        if running is not None and stage_index is not None else None)
        switch_genre = (target_genre is not None and target_genre != self.style.genre
                        and self.bar > 0 and self.bar % 4 == 0)
        if running is not None and journey is None and running.journey.end == "release" \
                and t >= running.journey.seconds:   # its final values once more, then it lets go
            self._running = None
            with self._lock:
                self._driving = None
        if style is not None:
            self._start_piece(replace(style, **values))
        elif nxt:
            self._start_piece(replace(self.style.variation(self._root_rng), **values))
        elif switch_genre:
            self._start_piece(replace(self.style, genre=target_genre, **values), skip_intro=True)
        self._apply_glides()
        if journey is not None:   # starts here, at t = 0, from the values this bar already has
            playing = self._binaural.setting.to_dict() if self._binaural.active and self._binaural.setting else None
            binaural_start = journey.binaural_start(playing) if journey.owns_binaural else None
            running = _Running(journey, self.samples_out, {f: getattr(self.style, f) for f in journey.fields},
                               binaural_start)
            t = 0.0
            self._running = running
        elif values:
            self._evolve(values)
        running = self._running   # None once a released journey has given its final values
        self._snapshot = (running.journey.snapshot(t, running.start, self.style.bpm, running.binaural_start)
                          if running is not None else None)
        bar_start = self.piece_seconds
        self._schedule_bar()
        n = int(round(self.bar_seconds * self.sr))
        out = self._acc[:n].copy()
        self._acc[:-n] = self._acc[n:]
        self._acc[-n:] = 0
        out = self._master(out)
        if running is not None and running.binaural_start is not None:   # head for the journey's end-of-bar values
            end = (self.samples_out + n - running.start_sample) / self.sr
            values = running.journey.binaural_at(end, running.binaural_start)
            self._binaural.set(Binaural.from_dict(values), n / self.sr)
        if self._binaural.active:   # after the master chain: nothing colours or pumps it
            out = out + self._binaural.render(n)
        self.bar += 1
        self.samples_out += n
        self.piece_seconds += n / self.sr
        self._last_bar_start = bar_start
        self._rendered = (running.journey, (self.samples_out - running.start_sample) / self.sr) \
            if running is not None and self._running is running else None
        return out.astype(np.float32)

    @property
    def bar_start_seconds(self) -> float:
        return self._last_bar_start

    def _apply_glides(self) -> None:
        """At a bar boundary: start newly queued glides here, set every gliding field to its value at this bar on
        the style, the piece and the composer, and drop the glides that reached their target."""
        with self._lock:
            glides = self._glides
        if not glides:
            return
        now, values, running = self.piece_seconds, {}, {}
        for name, g in glides.items():
            if not g.started:
                g = replace(g, start=now, source=getattr(self.style, name), started=True)
            values[name] = _bounded(name, g.at(now))
            running[name] = g
        self._evolve(values)
        with self._lock:   # a glide queued or cancelled meanwhile by another thread wins over this bookkeeping
            current = dict(self._glides)
            for name, g in glides.items():
                if current.get(name) is not g:
                    continue
                if now - running[name].start >= running[name].duration:
                    del current[name]
                else:
                    current[name] = running[name]
            self._glides = current

    def _evolve(self, values: dict[str, float]) -> None:
        """Set continuous fields in place on the playing style, the piece and the composer: no new piece."""
        self.style = replace(self.style, **values)
        self._piece.style = replace(self._piece.style, **values)
        self.composer.style = replace(self.composer.style, **values)

    def _journey_values(self, running: _Running | None, t: float) -> dict[str, float]:
        """The values of `running` (the journey playing) for the bar about to render, `t` seconds into it; empty
        without a journey."""
        if running is None:
            return {}
        _, _, values = running.journey.at(t, running.start)
        return {name: _bounded(name, value) for name, value in values.items()}

    def _schedule_bar(self) -> None:
        p = self.composer.plan(self.bar)
        self.section = p.section
        self.genre.schedule(self._piece, p)

    def _glide(self, name: str, value: float, n: int, span: int) -> np.ndarray | float:
        """`value`, or an (n, 1) ramp to it over the first `span` samples when it changed since the last bar."""
        prev = self._last.get(name, value)
        self._last[name] = value
        if prev == value:
            return value
        k = min(n, span)
        return np.concatenate([np.linspace(prev, value, k, endpoint=False), np.full(n - k, value)])[:, None]

    def _master(self, x: np.ndarray) -> np.ndarray:
        m, n, sr = self.genre.master(self.style), len(x), self.sr
        span = int(RAMP * sr)
        # convolution reverb send (the music only; the tail rings on across bars and style changes)
        space = int(round(m.space * 10))
        if space != self._ir_space:
            if self._reverb is None:
                self._reverb = ConvolutionReverb(_ir(space, sr))
            else:
                self._reverb.set_ir(_ir(space, sr))
            self._ir_space = space
        assert self._reverb is not None   # created on the first bar
        verb = self._reverb(self._send_hp(x)) * self._glide("reverb", m.reverb, n, span)
        # vinyl crackle and hiss
        if m.vinyl > 0:
            cr = np.zeros((n, 2))
            hits = self.rng.integers(0, n, (int(n / sr * 28 * m.vinyl) + 1, 2))
            cr[hits[:, 0], 0] = self.rng.uniform(-1, 1, len(hits))
            cr[hits[:, 1], 1] = self.rng.uniform(-1, 1, len(hits))
            x = x + (self._crackle_hp(cr) * 0.22 + self._hiss_lp(self.rng.standard_normal((n, 2))) * 0.004) * m.vinyl
        # room: early-reflection taps over the dry history
        H = len(self._room_hist)
        ext = np.concatenate([self._room_hist, x])
        wet = np.zeros_like(x)
        for d, g in self._room_taps:
            k = int(d * sr)
            wet += ext[H - k:H - k + n] * g
        self._room_hist = ext[-H:]
        y = x + self._room_lp(wet) * self._glide("room", m.room, n, span) + verb
        # tape wow and flutter: a slowly modulated fractional delay, continuous in absolute time; a changed depth
        # glides over the whole bar so the delay never jumps
        W = len(self._wow_hist)
        ext = np.concatenate([self._wow_hist, y])
        t = (self.samples_out + np.arange(n)) / sr
        w = self._glide("wow", m.wow, n, n)
        w = w[:, 0] if isinstance(w, np.ndarray) else w
        d = (0.0025 + 0.0016 * w * np.sin(2 * np.pi * 0.5 * t) + 0.0005 * w * np.sin(2 * np.pi * 3.3 * t + 1)) * sr
        pos = W + np.arange(n) - d
        grid = np.arange(len(ext))
        y = np.stack([np.interp(pos, grid, ext[:, c]) for c in (0, 1)], 1)
        self._wow_hist = ext[-W:]
        # tone: darker or more open tape; a new cutoff crossfades from the old filter, whose output stays continuous
        cut = int(m.tone)
        old = None
        if cut != self._tone_cut:
            new = StatefulFilter(_sos("lowpass", cut, 0, sr), 2)
            if self._tone_lp is not None:
                new.zi = self._tone_lp.zi.copy()
                old = self._tone_lp
            self._tone_lp, self._tone_cut = new, cut
        tone_lp = self._tone_lp
        assert tone_lp is not None        # created on the first bar
        if old is None:
            y = tone_lp(y)
        else:
            k = min(n, span)
            fade = np.linspace(0, 1, k, endpoint=False)[:, None]
            faded = old(y[:k])
            y = tone_lp(y)
            y[:k] = faded + (y[:k] - faded) * fade
        if self.samples_out < 0.6 * sr:  # fade in at the very start of the stream
            y *= np.clip((self.samples_out + np.arange(n)) / (0.6 * sr), 0, 1)[:, None]
        self._comp.threshold, self._comp.ratio = m.threshold, m.ratio
        drive = self._glide("drive", m.drive, n, span)   # a number, or an (n, 1) ramp after a change
        return soft_clip(self._comp(y), drive, 0.9)
