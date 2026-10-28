"""A wordless choir: a soft "aah" pad that sings the upper tones of each chord, in every genre (`Style.voice`).

Each voice is procedural, no download: a band-limited saw source shaped by three vowel formant band-passes
(`FORMANTS`), a slow vibrato that enters after the onset, a little breath noise, and a swell envelope. Notes are
cached by (midi, duration, vowel, rate) like the genres' own voices. The engine schedules the choir after the genre
through `Piece.add`, before the master chain, so the genre's room and reverb carry it; with `voice` 0 it never runs.

With the soundfont installed (`setup-samples`) the choir sings FluidR3_GM instead (`choir_program`): Choir Aahs
or Voice Oohs, following the vowel, in the acoustic genres and Synth Voice in the synth ones, each scaled so its
reference note has the procedural voice's level; without it the procedural voice sings.

The choir keeps its own voice-leading centre in the piece's state, so the genre's chord voicing and the random draws
of the music stay exactly as they are. The vowel follows the section: "a" where the melody plays, "o" in the intro,
the breakdown and the release.
"""
from __future__ import annotations

from dataclasses import replace
from functools import lru_cache

import numpy as np

from .composer import BarPlan, Chord, Note
from .genres.base import Piece
from .samples import Program, SampleInstruments
from .synth import SR, adsr, bp, hp, mtof, osc

# vowel -> (F1, F2, F3) in Hz; each formant's band-pass width and gain below
FORMANTS = {"a": (800, 1200, 2500), "o": (500, 850, 2400), "u": (350, 650, 2300)}
WIDTHS = (110, 130, 180)
GAINS = (1.0, 0.65, 0.25)
RANGE = (55, 79)            # G3 to G5: where the choir sings
CENTRE = 67                 # where its voicing starts, G4
GAIN = 0.12                 # each choir voice's level at voice=1
RELEASE = 0.4               # seconds a note rings past its length
PANS = (-0.35, 0.0, 0.35)
SYNTH_GENRES = ("synthwave", "electro", "electrohouse", "dubstep", "chiptune")
CHOIR_AAHS, VOICE_OOHS, SYNTH_VOICE = 52, 53, 54   # General MIDI programs, 0-based
VELOCITY = 0.8
# PM-025: the vocal melody needs a voice that sings melodies convincingly. The General MIDI choirs and the
# procedural formant voice do not (listening review: metallic, flute-like), so melody mode waits for an M8 voice
# pack: until the engine reports a melodic voice, the choir is a pad at any level.
MELODY_VOICE = 0.5
MELODY_PAN = 0.1
# PM-026: harmony parts under the vocal melody, one from ONE_PART_ENERGY, two from TWO_PART_ENERGY (never more)
ONE_PART_ENERGY = 0.7       # where the composer brings in the counter-melody too (`composer.COUNTER_ENERGY`)
TWO_PART_ENERGY = 0.9
HARMONY_PANS = (-0.45, 0.45)
HARMONY_GAIN = 0.55         # each part relative to the melody
HARMONY_HIGHPASS = 180      # Hz: keeps two low parts from clouding the mix
# semitones below the voice above: thirds, then sixths, then fourths/fifths; the rest only as a last resort
BELOW = (3, 4, 8, 9, 5, 7, 6, 10, 11, 2, 1)


@lru_cache(maxsize=512)
def sung(midi: int, seconds: float, vowel: str, sr: int = SR) -> np.ndarray:
    """One sung note of `seconds` (plus RELEASE) on `vowel`: peak at most 1, swelling in without a click."""
    n = int(seconds * sr) + int(RELEASE * sr)
    t = np.arange(n) / sr
    depth = 0.012 * np.clip((t - 0.4) / 0.6, 0.0, 1.0)            # vibrato enters after the onset
    freq = mtof(midi) * (1 + depth * np.sin(2 * np.pi * 5.2 * t))
    source = osc("saw", freq, n, sr)
    voice = np.zeros(n)
    for f, w, g in zip(FORMANTS[vowel], WIDTHS, GAINS, strict=True):
        voice += g * np.asarray(bp(source, f - w / 2, f + w / 2, sr))
    breath = np.asarray(bp(np.random.default_rng(midi).standard_normal(n), 1500, 4000, sr)) * 0.02
    env = adsr(n, sr, attack=min(0.6, 0.35 * seconds), decay=0.0, sustain=1.0, release=RELEASE, hold=seconds)
    x = (voice + breath) * env
    peak = float(np.abs(x).max())
    return x / peak if peak > 0 else x


@lru_cache(maxsize=8)
def reference_rms(sr: int = SR) -> float:
    """RMS over the first half second of the procedural voice's reference note (middle C, 1 s, "a"): the level a
    sampled choir's reference note is scaled to (`Program.rms`)."""
    x = sung(60, 1.0, "a", sr)
    return float(np.sqrt(np.mean(np.square(x[: int(0.5 * sr)]))))


@lru_cache(maxsize=16)
def choir_program(genre: str, vowel: str, sr: int = SR) -> Program:
    """The FluidR3_GM program a genre's choir sings on `vowel`, level-matched to the procedural voice."""
    if genre in SYNTH_GENRES:
        program = SYNTH_VOICE
    else:
        program = CHOIR_AAHS if vowel == "a" else VOICE_OOHS
    return Program(program, velocity=(50, 100), tail=RELEASE, rms=reference_rms(sr))


def _voicing(chord: Chord, ton: int, key_offset: int, center: float) -> list[int]:
    """The chord's upper tones (no root) each placed in the choir's range nearest `center`."""
    out = []
    for interval in chord.tones[1:4]:
        m = ton + key_offset + interval + 12
        while m - center > 6 and m - 12 >= RANGE[0]:
            m -= 12
        while center - m > 6 and m + 12 <= RANGE[1]:
            m += 12
        while m > RANGE[1]:
            m -= 12
        while m < RANGE[0]:
            m += 12
        out.append(m)
    return out


def choir_notes(plan: BarPlan, ton: int, center: float | None) -> tuple[list[tuple[int, float, float]], float]:
    """(midi, start beat, beats) of the choir in `plan`'s bar, and the voicing centre it leaves for the next bar:
    the bar's chord for the whole bar, or its first half then the passing chord."""
    center = CENTRE if center is None else center
    segments = [(0.0, 4.0, plan.chord)] if plan.passing is None else [(0.0, 2.0, plan.chord), (2.0, 2.0, plan.passing)]
    notes = []
    for start, beats, chord in segments:
        voiced = _voicing(chord, ton, plan.key_offset, center)
        notes += [(m, start, beats) for m in voiced]
        center = float(np.mean(voiced))
    return notes, center


def instrumental_plan(plan: BarPlan, voice: float, melodic: bool = False) -> BarPlan:
    """With a melodic voice at melodic vocal levels, reserve the lead layer for the singer, not the genre's
    instrument. Without one (`melodic` False) the genre keeps its lead at any `voice`."""
    if melodic and voice >= MELODY_VOICE and "lead" in plan.layers:
        return replace(plan, layers=plan.layers - {"lead"})
    return plan


def _formants(source: np.ndarray, vowel: str, sr: int) -> np.ndarray:
    x = np.zeros(len(source))
    for f, w, g in zip(FORMANTS[vowel], WIDTHS, GAINS, strict=True):
        x += g * np.asarray(bp(source, f - w / 2, f + w / 2, sr))
    return x


def _rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)))) if len(x) else 0.0


@lru_cache(maxsize=8)
def melody_rms(sr: int = SR) -> float:
    """RMS of the procedural melodic reference note (middle C, 1 s, "o") at peak 1: the level every melodic note
    is scaled to, sampled or procedural, so both backends sing the melody equally loud."""
    x = _formants(osc("saw", mtof(60), sr, sr), "o", sr)
    return _rms(x / max(float(np.max(np.abs(x))), 1e-9))


def melodic_note(midi: int, seconds: float, vowel: str, previous: int | None, genre: str,
                 sampled: SampleInstruments | None = None, sr: int = SR) -> np.ndarray:
    """An articulated vowel: 90 ms close-note glide, delayed 18-cent vibrato, and a short legato release.

    Sampled voices retain their soundfont timbre via variable-rate playback of an isolated sustained note.
    No pitch-bend state is written to the shared FluidSynth renderer or its cached arrays. Either backend is
    scaled to `melody_rms` over the note after its glide, so the level does not depend on the backend.
    """
    tail = 0.06
    n = int((seconds + tail) * sr)
    t = np.arange(n) / sr
    cents = 18 * np.clip((t - 0.3) / 0.5, 0, 1) * np.sin(2 * np.pi * 5.2 * t)
    if previous is not None and 0 < abs(previous - midi) <= 4:
        cents += (previous - midi) * 100 * np.clip(1 - t / 0.09, 0, 1)
    rate = 2 ** (cents / 1200)
    if sampled is not None:
        # Sustain beyond the largest possible playback offset; our envelope owns note-off.
        source = sampled.play(choir_program(genre, vowel, sr), midi, (seconds + tail) * 1.3 + 0.1, VELOCITY)
        positions = np.concatenate(([0.0], np.cumsum(rate[:-1])))
        x = np.interp(positions, np.arange(len(source)), source)
    else:
        x = _formants(osc("saw", mtof(midi) * rate, n, sr), vowel, sr)
    steady = x[int(0.1 * sr):] if n > int(0.2 * sr) else x
    x = x * (melody_rms(sr) / max(_rms(steady), 1e-9))
    attack = 0.01 if previous is not None else 0.04
    env = adsr(n, sr, attack=min(attack, seconds / 3), decay=0, sustain=1, release=tail, hold=seconds)
    return x * env


def _chord_pcs(plan: BarPlan, ton: int, beat: float) -> set[int]:
    chord = plan.passing if plan.passing is not None and beat >= 2 else plan.chord
    return {(ton + plan.key_offset + t) % 12 for t in chord.tones[:4]}


def _below(midi: int, pcs: set[int], avoid: set[int]) -> int:
    """The chord tone below `midi` at the most consonant interval in `BELOW`, never a pitch class in `avoid`."""
    for d in BELOW:
        if (midi - d) % 12 in pcs and (midi - d) % 12 not in avoid:
            return midi - d
    return midi - 3   # unreachable: a chord's tones leave no gap of a whole octave


def harmony_parts(plan: BarPlan, ton: int, limit: int = 2) -> list[tuple[Note, ...]]:
    """The harmony lines under `plan`'s melody: none below ONE_PART_ENERGY, one, or two from TWO_PART_ENERGY.

    Each note keeps the melody note's rhythm and is a chord tone of the chord sounding at its beat, a third or
    sixth below the voice above when the chord has one, so the parts move with the melody. A part never takes the
    melody's pitch class, so there is no unison or octave with it and no parallel octaves."""
    if not plan.melody or plan.energy < ONE_PART_ENERGY:
        return []
    count = min(limit, 2 if plan.energy >= TWO_PART_ENERGY else 1)
    parts: list[list[Note]] = [[] for _ in range(count)]
    for note in plan.melody:
        pcs, above = _chord_pcs(plan, ton, note.beat), note.midi
        avoid = {note.midi % 12}
        for part in parts:
            above = _below(above, pcs, avoid)
            avoid.add(above % 12)
            part.append(Note(note.beat, above, note.length))
    return [tuple(part) for part in parts]


def _sing(piece: Piece, line, key: str, vowel: str, bar: int, pan: float, gain: float,
          sampled: SampleInstruments | None, highpass: int = 0) -> None:
    """One vocal line in the bar, gliding between connected close notes (state kept under `key`)."""
    beat = 60 / piece.style.bpm
    previous = piece.state.get(key)
    for note in line:
        start = bar * 4 + note.beat
        connected = previous is not None and abs(previous[1] - start) < 1e-6
        midi = previous[0] if previous is not None and connected else None
        audio = melodic_note(note.midi, note.length * beat, vowel, midi, piece.style.genre, sampled, piece.sr)
        if highpass:
            audio = np.asarray(hp(audio, highpass, piece.sr))
        piece.add(audio, note.beat * beat, pan, gain)
        previous = (note.midi, start + note.length)
    piece.state[key] = previous if line else None


def _melody(piece: Piece, plan: BarPlan, voice: float, sampled: SampleInstruments | None) -> None:
    vowel = ("o", "u")[(plan.section_bar // 4) % 2]
    _sing(piece, plan.melody, "vocal_previous", vowel, plan.bar, MELODY_PAN, 0.2 * voice, sampled)
    parts = harmony_parts(plan, piece.ton)
    for i, pan in enumerate(HARMONY_PANS):
        line = parts[i] if i < len(parts) else ()
        _sing(piece, line, f"vocal_harmony_{i}", vowel, plan.bar, pan, 0.2 * voice * HARMONY_GAIN, sampled,
              HARMONY_HIGHPASS)


def schedule(piece: Piece, plan: BarPlan, voice: float, sampled: SampleInstruments | None = None,
             melodic: bool = False) -> None:
    """Sing the melody when a melodic voice is available (`melodic`), `voice` >= MELODY_VOICE and the lead plays;
    otherwise sing the choir pad."""
    if melodic and voice >= MELODY_VOICE and "lead" in plan.layers:
        _melody(piece, plan, voice, sampled)
        return
    for key in ("vocal_previous", *(f"vocal_harmony_{i}" for i in range(len(HARMONY_PANS)))):
        piece.state.pop(key, None)   # the pad breaks the line: the next melody starts without a glide
    notes, piece.state["choir_center"] = choir_notes(plan, piece.ton, piece.state.get("choir_center"))
    vowel = "a" if plan.section in ("A", "B", "A'", "B'") else "o"
    beat = 60.0 / piece.style.bpm
    for i, (midi, start, beats) in enumerate(notes):
        seconds = max(0.25, round(beats * beat * 4) / 4)           # quarter-second buckets keep the cache small
        if sampled is not None:
            note = sampled.play(choir_program(piece.style.genre, vowel, piece.sr), midi, seconds, VELOCITY)
        else:
            note = sung(midi, seconds, vowel, piece.sr)
        piece.add(note, start * beat, PANS[i % len(PANS)], GAIN * voice)
