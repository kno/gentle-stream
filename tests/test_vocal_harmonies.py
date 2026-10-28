"""PM-026: one or two voice-led harmony parts under the vocal melody at high energy."""
import itertools
from dataclasses import replace

import numpy as np
import pytest

from gentle_stream import vocals
from gentle_stream.composer import Composer, Note
from gentle_stream.style import Style
from gentle_stream.vocals import ONE_PART_ENERGY, TWO_PART_ENERGY, harmony_parts


def plans(mode="minor", key="D", bars=96, energy=1.0, seed=5):
    composer = Composer(Style(key=key, mode=mode, energy=energy), seed, 50)
    return [composer.plan(b) for b in range(bars)]


def chord_pcs(plan, beat, ton=50):
    chord = plan.passing if plan.passing is not None and beat >= 2 else plan.chord
    return {(ton + plan.key_offset + t) % 12 for t in chord.tones[:4]}


@pytest.mark.parametrize("mode", ["minor", "major", "dorian", "mixolydian", "lydian", "phrygian"])
def test_every_harmony_note_on_a_strong_beat_is_a_chord_tone(mode):
    checked = 0
    for plan in plans(mode):
        for part in harmony_parts(plan, 50, 2):
            for note in part:
                if note.beat in (0, 2):
                    assert note.midi % 12 in chord_pcs(plan, note.beat), (plan.bar, note)
                    checked += 1
    assert checked > 50


@pytest.mark.parametrize("mode", ["minor", "major", "dorian"])
def test_harmonies_sit_below_the_melody_and_never_double_it_at_the_octave(mode):
    for plan in plans(mode):
        parts = harmony_parts(plan, 50, 2)
        for part in parts:
            assert [(n.beat, n.length) for n in part] == [(n.beat, n.length) for n in plan.melody]
        for i, melody in enumerate(plan.melody):
            upper = parts[0][i].midi if parts else None
            for part in parts:
                gap = melody.midi - part[i].midi
                assert 3 <= gap <= 18 and gap % 12 != 0, (plan.bar, melody, part[i])
            if len(parts) == 2 and upper is not None:
                assert parts[1][i].midi < upper


def test_no_parallel_octaves_between_consecutive_notes():
    melody = tuple(Note(b, m, 1) for b, m in zip((0, 1, 2, 3), (69, 67, 65, 64), strict=True))
    for plan in plans("major", "C"):
        plan = replace(plan, melody=melody)
        for part in harmony_parts(plan, 48, 2):
            octave = [(m.midi - h.midi) % 12 == 0 for m, h in zip(melody, part, strict=True)]
            assert not any(a and b for a, b in itertools.pairwise(octave))


def test_the_number_of_parts_follows_the_energy_and_never_exceeds_two():
    plan = plans()[16]
    assert harmony_parts(replace(plan, energy=ONE_PART_ENERGY - 0.01), 50) == []
    assert len(harmony_parts(replace(plan, energy=ONE_PART_ENERGY), 50)) == 1
    assert len(harmony_parts(replace(plan, energy=TWO_PART_ENERGY), 50)) == 2
    assert len(harmony_parts(replace(plan, energy=1.0), 50, 5)) == 2
    assert harmony_parts(replace(plan, melody=()), 50) == []


class FakePiece:
    def __init__(self, style):
        self.style, self.ton, self.sr, self.state, self.calls = style, 50, 48000, {}, []

    def add(self, sig, t, pan=0.0, g=1.0):
        self.calls.append((len(sig), t, pan, g, sig))


def lead_plan(energy):
    plan = plans()[16]
    melody = (Note(0, 69, 1), Note(1, 67, 1), Note(2, 65, 2))
    return replace(plan, layers=plan.layers | {"lead"}, melody=melody, energy=energy)


@pytest.mark.parametrize("energy, parts", [(0.5, 0), (ONE_PART_ENERGY, 1), (TWO_PART_ENERGY, 2)])
def test_the_singer_adds_quieter_panned_high_passed_harmony_voices(energy, parts):
    piece = FakePiece(Style(voice=0.8))
    vocals.schedule(piece, lead_plan(energy), 0.8)  # type: ignore[arg-type]
    melody = [c for c in piece.calls if c[2] == vocals.MELODY_PAN]
    harmony = [c for c in piece.calls if c[2] != vocals.MELODY_PAN]
    assert len(melody) == 3 and len(harmony) == 3 * parts
    assert {c[2] for c in harmony} == set(vocals.HARMONY_PANS[:parts])
    assert all(c[3] < melody[0][3] for c in harmony)
    for _, _, _, _, sig in harmony:
        spectrum = np.abs(np.fft.rfft(sig))
        freqs = np.fft.rfftfreq(len(sig), 1 / 48000)
        assert spectrum[freqs < 60].sum() < 0.01 * spectrum.sum()


def test_every_harmony_note_and_no_melody_note_goes_through_the_high_pass(monkeypatch):
    filtered = []
    real = vocals.hp
    monkeypatch.setattr(vocals, "hp", lambda x, f, sr: filtered.append(f) or real(x, f, sr))
    piece = FakePiece(Style(voice=0.8))
    vocals.schedule(piece, lead_plan(TWO_PART_ENERGY), 0.8)  # type: ignore[arg-type]
    assert filtered == [vocals.HARMONY_HIGHPASS] * 6   # 3 melody notes x 2 parts; the melody stays full range


def test_without_the_lead_or_below_the_melody_threshold_no_harmony_sings():
    piece = FakePiece(Style(voice=0.4))
    vocals.schedule(piece, lead_plan(1.0), 0.4)  # type: ignore[arg-type]
    assert all(c[2] in vocals.PANS for c in piece.calls)   # the pad only
