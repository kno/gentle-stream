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


def syllables(n=3, sr=SR, consonant=CONSONANT, wobble=0.0):
    """`wobble`: the vowel's own pitch moving ±that many cents, 8 times a second (a speaking voice's intonation)."""
    rng = np.random.default_rng(1)
    t = np.arange(int(VOWEL * sr)) / sr
    phase = np.cumsum(120 * 2 ** (wobble * np.sin(2 * np.pi * 8 * t) / 1200)) / sr
    vowel = sum(0.3 / k * np.sin(2 * np.pi * k * phase) for k in range(1, 12)) * np.hanning(len(t)) ** 0.3
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


def test_the_voice_slides_into_a_note_along_an_eased_90_ms_curve():
    y = sung((Note(0.3, 0.5, 48), Note(0.9, 0.5, 55)), n=2)
    assert sing.PORTAMENTO == 0.09
    early = f0_at(y, 0.9 + 0.025, window=0.02)                          # an eased start: still near the note before
    middle = f0_at(y, 0.9 + 0.045, window=0.02)                         # half way, half way up
    assert hz(48) < early < hz(49.6)                                    # a straight line would be at 49.9 by now
    assert hz(50) < middle < hz(53)
    assert f0_at(y, 0.9 + 0.2) == pytest.approx(hz(55), rel=0.03)


def test_the_same_phrase_on_the_same_notes_is_sung_the_same_way():
    assert np.array_equal(sung(), sung())


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


def test_vibrato_grows_after_a_quarter_second_of_a_long_note_and_is_never_regular():
    long = (Note(0.3, 1.4, 50),)
    y = sing.sing(sing.analyse(syllables(1), SR), long, vibrato=True)
    before = semitones(y, 0.35, 0.3 + sing.VIBRATO_START, hz(50))
    after = semitones(y, 0.3 + 0.75, 0.3 + 1.2, hz(50))
    nominal = sing.VIBRATO_DEPTH / np.sqrt(2)                           # the std of a sine of that depth
    assert np.std(before) < 0.1
    assert 0.6 * nominal < np.std(after) < 1.5 * nominal
    crossings = np.count_nonzero(np.diff(np.sign(after - after.mean())) != 0) / 2
    assert crossings / 0.45 == pytest.approx(sing.VIBRATO_HZ, abs=1.0)


def test_a_held_note_is_never_perfectly_still_but_stays_on_its_pitch():
    y = sing.sing(sing.analyse(syllables(1), SR), (Note(0.3, 1.4, 50),), vibrato=False)
    cents = 100 * semitones(y, 0.4, 1.3, hz(50))                         # (the fading end measures poorly)
    windows = [np.median(cents[i:i + 20]) for i in range(0, len(cents) - 20, 20)]    # 100 ms each
    assert np.ptp(windows) >= 3                                          # it drifts (held still: under 1 cent)
    assert np.abs(cents).max() <= sing.DRIFT_CENTS + sing.OWN_INTONATION_MAX + 5   # never off the note (5: measuring)


def test_the_voices_own_intonation_rides_on_the_note():
    flat = sing.sing(sing.analyse(syllables(1), SR), (Note(0.3, 1.4, 50),), vibrato=False)
    lively = sing.sing(sing.analyse(syllables(1, wobble=50), SR), (Note(0.3, 1.4, 50),), vibrato=False)
    assert np.std(semitones(lively, 0.4, 1.55, hz(50))) > 2 * np.std(semitones(flat, 0.4, 1.55, hz(50)))


def test_without_vibrato_a_long_note_has_no_vibrato():
    y = sing.sing(sing.analyse(syllables(1), SR), (Note(0.3, 1.4, 50),), vibrato=False)
    assert np.std(semitones(y, 0.4, 1.2, hz(50))) < 0.1


def crossings_per_second(curve):
    rises = np.flatnonzero((curve[:-1] <= 0) & (curve[1:] > 0))
    return len(rises) / (len(curve) * sing.FRAME), np.diff(rises)


def test_each_note_has_its_own_vibrato_rate_and_depth():
    rng = np.random.default_rng(3)
    n = round(3.0 / sing.FRAME)
    notes = [sing._vibrato(rng, n) for _ in range(6)]
    rates = [crossings_per_second(v[round(sing.VIBRATO_START / sing.FRAME):])[0] for v in notes]
    depths = [np.abs(v).max() for v in notes]
    assert all(abs(r - sing.VIBRATO_HZ) <= sing.VIBRATO_HZ * (sing.VIBRATO_RATE_SPREAD + 0.5 * sing.VIBRATO_WOBBLE) + 0.3
               for r in rates)
    assert np.ptp(rates) > 0.5 and np.ptp(depths) > 0.03                  # never the same twice (wobble alone: < 0.5)
    assert all(np.all(v[:round(sing.VIBRATO_START / sing.FRAME)] == 0) for v in notes)


def test_a_notes_vibrato_wobbles_within_it():
    v = sing._vibrato(np.random.default_rng(3), round(3.0 / sing.FRAME))
    _, periods = crossings_per_second(v[round((sing.VIBRATO_START + sing.VIBRATO_RAMP) / sing.FRAME):])
    peaks = [np.abs(v[i:i + 36]).max() for i in range(120, len(v) - 36, 36)]
    assert np.ptp(periods) >= 2                                          # frames: its rate moves
    assert np.ptp(peaks) > 0.02                                          # and its depth


def own(f0, n=200):
    voice = sing.Voice(SR, np.asarray(f0, dtype=float), np.zeros((len(f0), 3)), np.zeros((len(f0), 3)), (), np.ones(len(f0), bool))
    return sing._own_intonation(voice, 0, len(f0), n)


def test_a_syllables_overall_slope_is_not_its_intonation():
    assert np.abs(own(np.geomspace(120, 130, 40))).max() < 1


def test_a_syllables_wobble_is_kept_at_60_percent_within_20_cents():
    t = np.arange(40) / 40
    gentle = own(120 * 2 ** (10 * np.sin(2 * np.pi * 2 * t) / 1200))
    wild = own(120 * 2 ** (200 * np.sin(2 * np.pi * 2 * t) / 1200))
    assert 4 < np.abs(gentle).max() <= 0.6 * 10 + 1
    assert np.abs(wild).max() == pytest.approx(sing.OWN_INTONATION_MAX)


def test_a_one_frame_glitch_and_the_syllables_edges_are_ignored():
    f0 = np.full(40, 120.0)
    f0[20] = 200                                                          # harvest's one-frame mistake
    f0[:4] = f0[-4:] = 90                                                 # where the vowel starts and ends
    assert np.abs(own(f0)).max() < 1


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
