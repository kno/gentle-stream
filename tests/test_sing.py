"""Sung phrases: the voice re-pitched with WORLD so each syllable lands on a note of the melody (S1, S3, S5).

The voice here is synthetic and exact: three syllables, each a noise burst (the consonant) then a harmonic tone (the
vowel), so where each one lands and at what pitch can be measured."""
import builtins
import itertools

import numpy as np
import pytest

from gentle_stream import sing
from gentle_stream.sing import Note
from gentle_stream.speech import SpeechError

SR = 16000
CONSONANT, VOWEL, GAP = 0.05, 0.15, 0.1


def syllables(n=3, sr=SR, consonant=CONSONANT):
    rng = np.random.default_rng(1)
    t = np.arange(int(VOWEL * sr)) / sr
    vowel = sum(0.3 / k * np.sin(2 * np.pi * 120 * k * t) for k in range(1, 12)) * np.hanning(len(t)) ** 0.3
    parts = [np.zeros(int(GAP * sr))]
    for _ in range(n):
        parts += [0.05 * rng.standard_normal(int(consonant * sr)), vowel, np.zeros(int(GAP * sr))]
    return np.concatenate(parts)


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def pitch_track(y, sr=SR, hop=0.005, window=0.04):
    """(times, f0) every `hop` s: normalised autocorrelation over `window` s, 0 where nothing periodic sounds."""
    w, h = int(window * sr), int(hop * sr)
    lo, hi = int(sr / 500), int(sr / 60)
    loudest = max(1e-9, float(np.abs(y).max()))
    times, f0 = [], []
    for i in range(0, max(1, len(y) - w), h):
        seg = y[i:i + w] - y[i:i + w].mean()
        times.append((i + w / 2) / sr)
        if np.sqrt(np.mean(seg ** 2)) < 0.02 * loudest:
            f0.append(0.0)
            continue
        ac = np.correlate(seg, seg, "full")[w - 1:]
        ac = ac / (ac[0] + 1e-12)
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] < 0.6:
            f0.append(0.0)
            continue
        a, b, c = ac[k - 1], ac[k], ac[k + 1]                       # parabolic: a fraction of a sample
        shift = 0.5 * (a - c) / (a - 2 * b + c) if a - 2 * b + c else 0.0
        f0.append(sr / (k + shift))
    return np.array(times), np.array(f0)


def f0_at(y, t, sr=SR, window=0.04):
    times, f0 = pitch_track(y, sr, window=window)
    return float(f0[int(np.argmin(np.abs(times - t)))])


def voiced_spans(y, sr=SR):
    times, f0 = pitch_track(y, sr)
    v = f0 > 0
    spans, i = [], 0
    while i < len(v):
        if v[i]:
            j = i
            while j < len(v) and v[j]:
                j += 1
            spans.append((times[i] - 0.02, times[j - 1] + 0.02))       # the window's edges, not its centre
            i = j
        else:
            i += 1
    return [s for s in spans if s[1] - s[0] > 0.06]


NOTES = (Note(0.3, 0.5, 48), Note(0.9, 0.5, 52), Note(1.5, 0.5, 55))


def sung(notes=NOTES, vibrato=False, n=3):
    return sing.sing(sing.analyse(syllables(n), SR), notes, vibrato=vibrato)


# ------------------------------------------------------------ syllables on notes
def test_each_syllable_is_sung_at_its_notes_pitch():
    y = sung()
    for note in NOTES:
        assert f0_at(y, note.start + 0.25) == pytest.approx(hz(note.midi), rel=0.03)


def test_each_syllable_starts_on_its_note_and_lasts_most_of_it():
    spans = voiced_spans(sung())
    assert len(spans) == 3
    for (a, b), note in zip(spans, NOTES, strict=True):    # harvest finds a vowel's start up to ~30 ms late
        assert a == pytest.approx(note.start, abs=0.04)
        assert b - a == pytest.approx(sing.LEGATO * note.length, abs=0.05)


def test_the_consonant_ends_on_the_notes_start_and_silence_fills_the_rest():
    y = sung()

    def rms(t0, t1):
        return float(np.sqrt(np.mean(y[int(t0 * SR):int(t1 * SR)] ** 2)))

    for note, nxt in itertools.pairwise(NOTES):
        consonant = rms(nxt.start - CONSONANT + 0.01, nxt.start - 0.005)
        between = rms(note.start + note.length, nxt.start - CONSONANT - 0.02)
        assert consonant > 10 * between
        assert np.all(y[int((note.start + note.length) * SR):int((nxt.start - CONSONANT - 0.02) * SR)] == 0)


def test_sample_zero_is_the_origin_of_the_notes_times():
    y = sung()
    assert np.abs(y[:int((NOTES[0].start - CONSONANT - 0.02) * SR)]).max() < 1e-3
    assert np.abs(y[int((NOTES[0].start - CONSONANT) * SR):int(NOTES[0].start * SR)]).max() > 1e-2


def test_a_note_too_early_for_its_consonant_is_skipped():
    early = (Note(0.0, 0.3, 45), *NOTES)
    spans = voiced_spans(sung(early))
    assert [a for a, _ in spans] == pytest.approx([0.3, 0.9, 1.5], abs=0.04)


def test_a_consonant_that_does_not_fit_shortens_the_vowel_before_it():
    voice = sing.analyse(syllables(2, consonant=0.1), SR)                 # a long consonant, short notes
    y = sing.sing(voice, (Note(0.3, 0.25, 48), Note(0.55, 0.25, 55)), vibrato=False)
    spans = voiced_spans(y)
    assert spans[1][0] == pytest.approx(0.55, abs=0.03)                 # the second syllable is still on its beat
    assert spans[0][1] < 0.55 - 0.1 + 0.03                              # the first one gave up its tail
    assert f0_at(y, 0.55 + 0.15) == pytest.approx(hz(55), rel=0.03)


def test_the_voice_glides_into_a_note_from_the_one_before():
    y = sung((Note(0.3, 0.5, 48), Note(0.9, 0.5, 55)), n=2)
    f0 = [f0_at(y, 0.9 + d) for d in (0.035, 0.045, 0.06, 0.2)]
    assert f0[0] < f0[1] < f0[2] <= f0[3] * 1.01
    assert f0[3] == pytest.approx(hz(55), rel=0.03)
    early = f0_at(y, 0.9 + 0.025, window=0.02)                          # inside the 40 ms glide: still below
    assert hz(48) < early < hz(55) * 2 ** (-1 / 12)


def test_more_syllables_than_notes_sing_the_rest_on_the_last_note():
    y = sing.sing(sing.analyse(syllables(3), SR), NOTES[:2], vibrato=False)
    after = NOTES[1].start + sing.LEGATO * NOTES[1].length + CONSONANT       # right after it, never on top of it
    assert np.abs(y[int((after - CONSONANT + 0.01) * SR):int((after - 0.005) * SR)]).max() > 1e-2   # its consonant
    assert f0_at(y, after + 0.2) == pytest.approx(hz(NOTES[1].midi), rel=0.03)
    assert len(y) == pytest.approx((after + sing.LEGATO * NOTES[1].length) * SR, abs=0.02 * SR)


def test_fewer_syllables_than_notes_leave_the_rest_unsung():
    y = sing.sing(sing.analyse(syllables(2), SR), NOTES, vibrato=False)
    assert len(voiced_spans(y)) == 2
    assert len(y) < NOTES[2].start * SR


# ------------------------------------------------------------ vibrato
def semitones(y, t0, t1, ref):
    times, f0 = pitch_track(y)
    seg = f0[(times >= t0) & (times < t1)]
    return 12 * np.log2(seg[seg > 0] / ref)


def test_vibrato_grows_after_a_quarter_second_of_a_long_note():
    long = (Note(0.3, 1.4, 50),)
    y = sing.sing(sing.analyse(syllables(1), SR), long, vibrato=True)
    before = semitones(y, 0.35, 0.3 + sing.VIBRATO_START, hz(50))
    after = semitones(y, 0.3 + 0.75, 0.3 + 1.2, hz(50))
    assert np.std(before) < 0.06                                          # measurement noise only
    assert np.std(after) == pytest.approx(sing.VIBRATO_DEPTH / np.sqrt(2), abs=0.05)   # a sine of that depth
    crossings = np.count_nonzero(np.diff(np.sign(after - after.mean())) != 0) / 2
    assert crossings / 0.45 == pytest.approx(sing.VIBRATO_HZ, abs=1.0)


def test_without_vibrato_a_long_note_stays_flat():
    y = sing.sing(sing.analyse(syllables(1), SR), (Note(0.3, 1.4, 50),), vibrato=False)
    assert np.std(semitones(y, 0.4, 1.2, hz(50))) < 0.06


# ------------------------------------------------------------ register and level
def test_the_melody_moves_by_whole_octaves_into_the_voices_register():
    high = (Note(0, 1, 74), Note(1, 1, 76), Note(2, 1, 79))
    moved = sing.transpose(high)
    assert [n.midi for n in moved] == [50, 52, 55]
    assert [(n.start, n.length) for n in moved] == [(n.start, n.length) for n in high]
    assert sing.transpose(NOTES) == NOTES


def test_a_sung_phrase_is_a_lead_vocal_level():
    y = sung()
    voiced = y[np.abs(y) > 0]
    assert np.sqrt(np.mean(y[int(0.25 * SR):int(2.0 * SR)] ** 2)) > 0
    assert np.abs(y).max() <= sing.SING_PEAK + 1e-9
    rms = float(np.sqrt(np.mean(voiced ** 2)))
    assert rms == pytest.approx(sing.SING_RMS, rel=0.05) or np.abs(y).max() == pytest.approx(sing.SING_PEAK)
    assert sing.SING_DUCK_DB == 6.0 and sing.SING_RMS > 0.08                 # above a spoken phrase (S5)


# ------------------------------------------------------------ failures
def test_a_voice_with_nothing_voiced_cannot_be_sung():
    noise = 0.05 * np.random.default_rng(2).standard_normal(SR)
    with pytest.raises(SpeechError, match="^nothing in the phrase can be sung"):
        sing.sing(sing.analyse(noise, SR), NOTES)


def test_without_pyworld_the_error_says_how_to_install_it(monkeypatch):
    real = builtins.__import__

    def no_pyworld(name, *args, **kwargs):
        if name == "pyworld":
            raise ImportError("No module named 'pyworld'")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_pyworld)
    assert not sing.available()
    with pytest.raises(SpeechError) as e:
        sing.analyse(syllables(1), SR)
    assert str(e.value) == ("singing needs pyworld: pip install 'gentle-stream[sing]' "
                            "(or uv sync --extra sing in a checkout)")
