"""Real-time playback: a producer thread renders bars ahead of time and the audio callback only copies samples.

The callback never synthesizes. It pulls from a short queue of rendered bars, applies a smoothed gain (so play,
pause and volume never click) and records level/spectrum data for the TUI. "Now playing" follows the bar that is
actually audible, not the one being rendered: its style and its journey progress travel with its audio.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from .binaural import Binaural
from .composer import cycle_position
from .engine import Engine
from .journey import Journey, JourneySnapshot
from .recorder import Recorder, RecordError
from .style import Style

RAMP_SECONDS = 0.03
CROSSFADE_SECONDS = 0.08
SPECTRUM_SIZE = 8192                   # ~0.19 s of output: fine enough for narrow low bands
SPECTRUM_RANGE = (50.0, 10000.0)       # Hz covered by the bar; the master low-pass leaves little above
SPECTRUM_MIN_BINS = 3.0                # narrow low bands average at least this many FFT bins
SPECTRUM_TILT = 3.0                    # dB per octave around 1 kHz: pink noise (and most music) reads flat
SPECTRUM_FLOOR, SPECTRUM_DB = -96.0, 60.0   # dB shown as empty, and the dB span up to a full column
SPECTRUM_FALL = 0.12                   # how much a column may drop per call; rises are immediate


@dataclass(frozen=True)
class NowPlaying:
    style: Style
    piece: int
    bar: int
    start_seconds: float = 0.0
    journey: JourneySnapshot | None = None   # the journey's progress at this bar


@dataclass
class _Chunk:
    audio: np.ndarray
    meta: NowPlaying


def settle(level: np.ndarray, shown: np.ndarray) -> np.ndarray:
    """Spectrum columns rise at once and fall by at most SPECTRUM_FALL from what was `shown` last time."""
    return np.maximum(level, shown - SPECTRUM_FALL) if shown.shape == level.shape else level


def _default_stream(**kw):
    import sounddevice as sd

    return sd.OutputStream(**kw)


class Player:
    def __init__(self, engine: Engine, stream_factory=_default_stream, prebuffer: float = 1.0,
                 blocksize: int = 1024, volume: float = 0.8):
        self.engine = engine
        self._factory = stream_factory
        self._prebuffer = int(prebuffer * engine.sr)
        self._blocksize = blocksize
        self._lock = threading.Lock()          # guards the chunk queue (held briefly by the callback)
        self._render_lock = threading.Lock()   # one bar render + enqueue at a time; next() waits for it
        self._chunks: deque[_Chunk] = deque()
        self._offset = 0                 # read position inside the first chunk
        self._buffered = 0               # samples queued and not yet played
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._producer = threading.Thread(target=self._produce, name="gentle-stream-producer", daemon=True)
        self._stream = None
        self.playing = True
        self.volume = float(np.clip(volume, 0, 1))
        self._gain = 0.0
        self.position = 0                # samples played since start
        self.underruns = 0
        self.level = 0.0
        self._tail = np.zeros(SPECTRUM_SIZE, dtype=np.float32)
        self._window = np.hanning(SPECTRUM_SIZE).astype(np.float32)
        self._shown = np.zeros(0)        # last spectrum() result, for the gentle fall
        self.now = NowPlaying(engine.style, engine.piece, 0, 0.0)
        self._recorder: Recorder | None = None   # the session recording, fed by the audio callback
        self._broadcast = None                   # the live broadcast (broadcast.Broadcast), fed by it too
        self._pack_aside = None                  # a voice pack set aside while broadcasting (not redistributable)

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        """Open the output stream and start rendering; calling it again is a no-op."""
        if self._stream is not None:
            return
        self._stream = self._factory(samplerate=self.engine.sr, channels=2, dtype="float32",
                                     blocksize=self._blocksize, latency="high", callback=self._callback)
        self._producer.start()
        deadline = time.monotonic() + 5
        while self._buffered == 0 and self._producer.is_alive() and time.monotonic() < deadline:
            time.sleep(0.005)    # the first bar is ready before the device starts pulling
        self._stream.start()

    def close(self) -> None:
        self._stopping.set()
        self._wake.set()
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
        if self._producer.is_alive():
            self._producer.join(timeout=5)
        self.record_stop()   # a recording in progress is saved and closed
        self.stream_stop()   # and a broadcast ends

    # ------------------------------------------------------------ broadcasting
    def stream_start(self):
        """Broadcast what plays to the configured ingest (`gentle-stream stream url/key`): its status, or
        BroadcastError with the reason. While it runs, phrases are spoken with espeak-ng and a voice pack that may not
        be redistributed gives way to the built-in choir."""
        import shutil

        from .broadcast import Broadcast, BroadcastError
        from .broadcast_view import BroadcastUnavailable, BroadcastView, view_text
        from .streamconf import StreamConfigError, load_key, load_url

        current = self._broadcast
        if current is not None and current.status()["running"]:
            raise BroadcastError(f"already broadcasting to {current.url}")
        self.stream_stop()                      # a failed broadcast still kept for its status
        url = load_url()
        if url is None:
            raise BroadcastError("no ingest URL: run `gentle-stream stream url URL` "
                                 "(e.g. rtmps://a.rtmps.youtube.com/live2)")
        try:
            key = load_key()
            view = BroadcastView()
        except (StreamConfigError, BroadcastUnavailable) as e:
            raise BroadcastError(str(e)) from None
        phrases = self.engine.journey_phrases()
        if phrases and shutil.which("espeak-ng") is None:
            raise BroadcastError("the journey speaks phrases, and a broadcast speaks them with espeak-ng, which is "
                                 "not installed (macOS voices are licensed for personal use only); install espeak-ng "
                                 "or stop the journey")
        self._safe_sources(True, phrases)
        broadcast = Broadcast(url, key, self.engine.sr, view, lambda: view_text(self),
                              lambda: self.spectrum_levels(48))
        broadcast.start()
        status = broadcast.status()
        if not status["running"]:
            broadcast.stop()
            self._safe_sources(False, phrases)
            raise BroadcastError(status["error"] or "the broadcast did not start")
        self._broadcast = broadcast
        return status

    def stream_stop(self):
        """End the broadcast: its final status, or None when there was none."""
        broadcast, self._broadcast = self._broadcast, None
        if broadcast is None:
            return None
        broadcast.stop()
        self._safe_sources(False, self.engine.journey_phrases())
        return broadcast.status()

    @property
    def streaming(self):
        """The broadcast's status (also after it failed, until it is stopped), or None."""
        broadcast = self._broadcast
        return broadcast.status() if broadcast is not None else None

    def _safe_sources(self, on: bool, phrases: tuple[str, ...]) -> None:
        """Only what may be broadcast while `on`: espeak-ng for phrases, no pack that may not be redistributed; the
        usual sources again when off. The journey's phrases are rendered again with the program now in use."""
        from . import speech

        speech.use_only("espeak-ng" if on else None)
        if on:
            pack = self.engine.voices
            if pack is not None and not pack.pack.redistributable:
                self._pack_aside = pack
                self.engine.set_voices(None)
        elif self._pack_aside is not None:
            self.engine.set_voices(self._pack_aside)
            self._pack_aside = None
        if phrases:
            self.engine.forget_phrases()
            speech.prerender(phrases, self.engine.sr, self.engine.provide_phrase)

    # ------------------------------------------------------------ recording
    def record_start(self, path, force: bool = False) -> None:
        """Record what the device is given into the WAV at `path` from the next audio block; RecordError when a
        recording runs, the path is not a .wav in an existing folder, or the file exists without `force`."""
        if self._recorder is not None:
            raise RecordError(f"already recording to {self._recorder.path}")
        self._recorder = Recorder(path, self.engine.sr, force)

    def record_stop(self):
        """Stop recording: (path, seconds) of the saved file, or None when nothing was recording."""
        recorder, self._recorder = self._recorder, None
        if recorder is None:
            return None
        recorder.stop()
        return recorder.path, recorder.seconds

    @property
    def recording(self):
        """(path, seconds so far) while recording, else None."""
        recorder = self._recorder
        return (recorder.path, recorder.seconds) if recorder is not None else None

    # ------------------------------------------------------------ controls
    def play(self) -> None:
        self.playing = True

    def pause(self) -> None:
        self.playing = False

    def toggle(self) -> None:
        self.playing = not self.playing

    def set_volume(self, volume: float) -> None:
        self.volume = float(np.clip(volume, 0, 1))

    def glide(self, fields: dict[str, float], seconds: float) -> None:
        """Glide continuous style fields in place, as the background player's `glide` (`ctl glide`)."""
        self.engine.queue_glide(fields, seconds)

    def tempo(self, bpm: float, seconds: float) -> None:
        """Glide the tempo in place, as the background player's `tempo` (`ctl tempo`)."""
        self.engine.queue_tempo(bpm, seconds)

    def say(self, text: str, voice: str | None = None, rate: int | None = None, effect: str = "dry") -> list[str]:
        """Speak `text` from the next phrase boundary, as the background player's `say` (`ctl say`): the warnings
        (an unknown voice); SpeechError when it cannot be spoken. Renders here: call it off the UI thread."""
        from .speech import render, resolve_voice

        voice, warning = resolve_voice(voice)
        self.engine.queue_speech(render(text, self.engine.sr, voice, rate, effect))
        return [warning] if warning else []

    def set_binaural(self, setting: Binaural | None, seconds: float = 0.0) -> None:
        """Head for `setting` (None fades it out), as the background player's `binaural` (`ctl binaural on|off`)."""
        self.engine.queue_binaural(setting, seconds)

    def glide_binaural(self, values: dict[str, float], seconds: float = 0.0) -> None:
        """Glide only the given carrier, beat or level, as the background player's `binaural_set`; refused while the
        layer is off, with the same message."""
        current = self.engine.binaural
        if current is None:
            raise ValueError("binaural is off; turn it on first")
        self.engine.queue_binaural(Binaural.from_dict({**current.to_dict(), **values}), seconds)

    def set_style(self, style: Style) -> None:
        """The new style starts at the next rendered bar, after the audio already buffered."""
        self.engine.queue_style(style)

    def journey_start(self, journey: dict) -> None:
        """Run a journey object (`Journey.to_dict`) from the next rendered bar, like the background player, rendering
        its phrases ahead in the background."""
        normalized = Journey.from_dict(journey)
        self.engine.queue_journey(normalized)
        if normalized.phrases:
            from .speech import prerender
            prerender(normalized.phrases, self.engine.sr, self.engine.provide_phrase)

    def journey_current(self) -> dict | None:
        """The journey the engine is running, like the background player's `journey_current`."""
        current = self.engine.journey
        return current.to_dict() if current is not None else None

    def journey_edit(self, journey: dict) -> None:
        """Replace the running journey from the next bar, keeping its place, like the background player."""
        edited = Journey.from_dict(journey)
        self.engine.queue_journey_edit(edited)
        if edited.phrases:
            from .speech import prerender
            prerender(edited.phrases, self.engine.sr, self.engine.provide_phrase)

    def journey_restart(self) -> None:
        """Restart the running journey at the next rendered bar."""
        self.engine.restart_journey()

    def journey_skip(self) -> None:
        """Advance the running journey to its next stage at the next rendered bar."""
        self.engine.skip_journey()

    def journey_stop(self) -> None:
        """Stop the running journey at the next rendered bar."""
        self.engine.stop_journey()

    @property
    def vocals_backend(self) -> str:
        """The backend singing the wordless vocal layer."""
        return self.engine.vocals_backend

    @property
    def binaural(self) -> Binaural | None:
        """The binaural setting the layer is heading to, or None when it is off."""
        return self.engine.binaural

    def next(self) -> None:
        """A new piece with the same mood, right away: its first bar is rendered now and crossfaded over the
        pending audio of the old piece, which is dropped. No gap, no jump."""
        with self._render_lock:  # waits for a bar being rendered, so no old bar can be queued after this
            self.engine.queue_next()
            audio = self.engine.render_bar()
            meta = self._meta()
            fade = min(int(CROSSFADE_SECONDS * self.engine.sr), len(audio))
            ramp = np.linspace(0, 1, fade, dtype=np.float32)[:, None]
            audio[:fade] *= ramp
            with self._lock:
                old = self._pending(fade)
                audio[:len(old)] += old * ramp[::-1][:len(old)]
                self._chunks.clear()
                self._chunks.append(_Chunk(audio, meta))
                self._offset = 0
                self._buffered = len(audio)
        self._wake.set()

    def _meta(self) -> NowPlaying:
        """What the bar rendered last is, for when it becomes audible. Caller holds _render_lock."""
        e = self.engine
        return NowPlaying(e.style, e.piece, e.bar - 1, e.bar_start_seconds, e.journey_snapshot)

    def _pending(self, n: int) -> np.ndarray:
        """The next `n` queued samples (fewer if less is queued), without consuming them. Caller holds _lock."""
        parts, need, offset = [], n, self._offset
        for c in self._chunks:
            part = c.audio[offset:offset + need]
            parts.append(part)
            need -= len(part)
            offset = 0
            if need <= 0:
                break
        return np.concatenate(parts) if parts else np.zeros((0, 2), dtype=np.float32)

    @property
    def buffered_seconds(self) -> float:
        return self._buffered / self.engine.sr

    @property
    def elapsed_seconds(self) -> float:
        """Seconds into the current piece, following the bar that is audible now."""
        return self.now.start_seconds + self._offset / self.engine.sr

    @property
    def cycle_remaining_seconds(self) -> float:
        """Seconds left in the song-form cycle playing now, before it loops with fresh variation."""
        cycle_bar, cycle_len = cycle_position(self.now.bar)
        return (cycle_len - cycle_bar) * (240.0 / self.now.style.bpm) - self._offset / self.engine.sr

    @property
    def style(self) -> Style:
        """The style being rendered, which may not be audible yet: the base for the next mood."""
        return self.engine.style

    def detach(self) -> None:
        """Leave the music playing without this app; an in-process player cannot outlive it, so it closes."""
        self.close()

    def spectrum(self, bands: int = 32) -> np.ndarray:
        """`spectrum_levels`, with columns that rise at once and fall gently between calls. Runs on the UI thread."""
        self._shown = settle(self.spectrum_levels(bands), self._shown)
        return self._shown

    def spectrum_levels(self, bands: int = 32) -> np.ndarray:
        """Log-spaced band levels of the latest output, scaled to 0..1 for display.

        Each band is the mean power over its frequency range, integrated from the FFT with fractional bins, so a
        band narrower than one bin still gets a value and wide high bands are averaged instead of merged. A tilt
        of SPECTRUM_TILT dB/octave makes pink noise flat. Stateless, so any thread may call it.
        """
        df = self.engine.sr / SPECTRUM_SIZE
        x = self._tail * self._window
        power = np.abs(np.fft.rfft(x)) ** 2 * (2 / self._window.sum()) ** 2
        # bin k covers [(k - 0.5) df, (k + 0.5) df]; interpolating the running sum integrates fractional bins
        cum = np.concatenate([[0.0], np.cumsum(power)])
        cum_freqs = (np.arange(len(cum)) - 0.5) * df
        edges = np.geomspace(*SPECTRUM_RANGE, bands + 1)
        centers = np.sqrt(edges[:-1] * edges[1:])
        width = np.maximum(np.diff(edges), SPECTRUM_MIN_BINS * df)
        lo = (edges[:-1] + edges[1:] - width) / 2
        hi = lo + width
        mean = (np.interp(hi, cum_freqs, cum) - np.interp(lo, cum_freqs, cum)) / ((hi - lo) / df)
        db = 10 * np.log10(mean + 1e-12) + SPECTRUM_TILT * np.log2(centers / 1000)
        return np.clip((db - SPECTRUM_FLOOR) / SPECTRUM_DB, 0, 1)

    # ------------------------------------------------------------ threads
    def _produce(self) -> None:
        while not self._stopping.is_set():
            if self._buffered < self._prebuffer:
                with self._render_lock:
                    audio = self.engine.render_bar()
                    meta = self._meta()
                    with self._lock:
                        self._chunks.append(_Chunk(audio, meta))
                        self._buffered += len(audio)
            else:
                self._wake.wait(0.05)
                self._wake.clear()

    def _pull(self, frames: int) -> np.ndarray:
        out = np.zeros((frames, 2), dtype=np.float32)
        got = 0
        with self._lock:
            while got < frames and self._chunks:
                c = self._chunks[0]
                take = min(frames - got, len(c.audio) - self._offset)
                out[got:got + take] = c.audio[self._offset:self._offset + take]
                self.now = c.meta
                got += take
                self._offset += take
                if self._offset >= len(c.audio):
                    self._chunks.popleft()
                    self._offset = 0
            self._buffered -= got
        if got < frames:
            self.underruns += 1
        self.position += frames
        return out

    def _callback(self, outdata, frames, time_info, status) -> None:
        target = self.volume if self.playing else 0.0
        recorder, broadcast = self._recorder, self._broadcast
        if self._gain == 0.0 and target == 0.0 and not self.playing:
            outdata[:] = 0
            self.level = 0.0
            self._tail[:] = 0
            if recorder is not None:
                recorder.feed(outdata)
            if broadcast is not None:
                broadcast.feed(outdata)
            return
        audio = self._pull(frames)
        self._wake.set()
        rate = 1.0 / (RAMP_SECONDS * self.engine.sr)
        diff = target - self._gain
        steps = np.minimum(np.arange(1, frames + 1) * rate, abs(diff))
        gain = (self._gain + np.sign(diff) * steps).astype(np.float32)
        self._gain = float(gain[-1]) if abs(gain[-1] - target) > 1e-6 else target
        outdata[:] = audio * gain[:, None]
        if recorder is not None:   # a copy into a queue: never waits for the disk
            recorder.feed(outdata)
        if broadcast is not None:  # the same for the broadcast: never waits for the encoder or the network
            broadcast.feed(outdata)
        mono = outdata.mean(axis=1)
        self.level = float(np.sqrt(np.mean(mono ** 2)))
        n = min(frames, SPECTRUM_SIZE)
        self._tail = np.concatenate([self._tail[n:], mono[-n:]])
