"""PM-022: a procedural wordless choir pad that follows the harmony."""
import json
import time

import numpy as np
import pytest

from gentle_stream import genres
from gentle_stream.composer import Composer
from gentle_stream.engine import GLIDE_FIELDS, SR, Engine
from gentle_stream.presets import PresetStore
from gentle_stream.style import Style
from gentle_stream.vocals import FORMANTS, choir_notes, sung


def spectrum_peaks(x, low, high):
    """Frequencies of the local maxima of the smoothed magnitude spectrum of `x` between `low` and `high` Hz."""
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), 1 / SR)
    width = int(120 / freqs[1])
    smooth = np.convolve(mag, np.ones(width) / width, mode="same")
    band = (freqs >= low) & (freqs <= high)
    idx = np.where(band)[0]
    return [freqs[i] for i in idx[1:-1] if smooth[i] >= smooth[i - 1] and smooth[i] >= smooth[i + 1]]


# ------------------------------------------------------------ the voice
@pytest.mark.parametrize("vowel", sorted(FORMANTS))
def test_a_sung_note_shows_formant_peaks_near_its_vowel_targets(vowel):
    x = sung(43, 2.0, vowel)                                    # G2: harmonics every ~98 Hz fill the envelope
    first, second = FORMANTS[vowel][:2]
    peaks = spectrum_peaks(x[SR // 2:], 200, 2000)
    assert min(abs(p - first) for p in peaks) <= 150, peaks
    assert min(abs(p - second) for p in peaks) <= 150, peaks


def test_the_a_vowel_has_its_peaks_near_800_and_1200_hz():
    assert FORMANTS["a"][:2] == (800, 1200)


def test_a_sung_note_swells_in_and_stays_bounded():
    x = sung(60, 3.0, "a")
    assert len(x) == int(3.0 * SR) + int(0.4 * SR)              # a short release rings past the note
    assert np.abs(x[: SR // 50]).max() < 0.1 * np.abs(x).max()  # swells in, no attack click
    assert np.all(np.isfinite(x)) and np.abs(x).max() <= 1.0
    assert sung(60, 3.0, "a") is sung(60, 3.0, "a")             # cached like the other voices


# ------------------------------------------------------------ the harmony
def test_the_choir_sings_upper_chord_tones_with_smooth_voice_leading():
    style = Style(key="D", mode="minor")
    composer = Composer(style, 5, 50)
    center = None
    previous = None
    for bar in range(32):
        plan = composer.plan(bar)
        notes, center = choir_notes(plan, 50, center)
        chord = plan.chord if plan.passing is None else None
        if chord is not None:
            tones = {(50 + plan.key_offset + t) % 12 for t in chord.tones[:4]}
            assert {m % 12 for m, _, _ in notes} <= tones
        assert all(55 <= m <= 79 for m, _, _ in notes)             # a choir's range
        first = sorted(m for m, start, _ in notes if start == 0)
        if previous is not None:
            assert max(abs(a - b) for a, b in zip(first, previous, strict=False)) <= 7
        previous = sorted(m for m, start, _ in notes if start > 0) or first


# ------------------------------------------------------------ acceptance criteria
def test_voice_is_off_by_default_and_old_presets_load_without_it(tmp_path):
    assert Style().voice == 0.0
    assert Style.from_dict({"name": "Old", "energy": 0.4}).voice == 0.0
    path = tmp_path / "presets.json"
    old = Style().to_dict()
    del old["voice"]
    path.write_text(json.dumps({"version": 1, "presets": [{"name": "Old", "mood": "", "style": old}]}))
    (preset,) = PresetStore(path).list()
    assert preset.style.voice == 0.0


def test_voice_is_a_continuous_glide_field_clamped_to_0_1():
    assert GLIDE_FIELDS["voice"] == (0.0, 1.0)
    assert Style.from_dict({"voice": 3}).voice == 1.0 and Style.from_dict({"voice": -1}).voice == 0.0


@pytest.mark.parametrize("name", genres.NAMES)
def test_a_voice_of_zero_renders_exactly_as_without_the_choir(name, monkeypatch):
    from gentle_stream import vocals

    calls = []
    monkeypatch.setattr(vocals, "schedule", lambda *a, **k: calls.append(a))
    e = Engine(Style(genre=name, voice=0.0), seed=3, samples=False)
    for _ in range(4):
        e.render_bar()
    assert calls == []


@pytest.mark.parametrize("name", genres.NAMES)
def test_the_choir_joins_every_genre_fast_and_below_full_scale(name):
    e = Engine(Style(genre=name, voice=1.0), seed=3, samples=False)
    t0 = time.perf_counter()
    x = np.concatenate([e.render_bar() for _ in range(8)])
    assert len(x) / SR / (time.perf_counter() - t0) > 4
    assert np.all(np.isfinite(x)) and np.abs(x).max() < 1.0
    plain = Engine(Style(genre=name, voice=0.0), seed=3, samples=False)
    y = np.concatenate([plain.render_bar() for _ in range(8)])
    assert not np.array_equal(x, y)


def test_the_mood_prompt_offers_the_voice_field():
    from gentle_stream.bridge import PROMPT

    assert '"voice": 0-1' in PROMPT and "wordless" in PROMPT


# ------------------------------------------------------------ PM-023: the sampled choir
from gentle_stream import samples  # noqa: E402

REAL = samples.soundfont_path()
needs_sf2 = pytest.mark.skipif(REAL is None or samples.load_renderer(REAL) is None,
                               reason="FluidR3_GM or FluidSynth not installed (gentle-stream setup-samples)")


@pytest.mark.parametrize("genre, vowel, program", [
    ("lofi", "a", 52), ("ambient", "a", 52), ("jazz", "o", 53), ("rock", "o", 53),
    ("synthwave", "a", 54), ("electro", "o", 54), ("electrohouse", "a", 54), ("dubstep", "a", 54),
    ("chiptune", "o", 54), ("cumbia", "a", 52),
])
def test_acoustic_genres_sing_choir_aahs_or_voice_oohs_and_synth_genres_synth_voice(genre, vowel, program):
    from gentle_stream.vocals import choir_program

    assert choir_program(genre, vowel).program == program


def choir_level(genre, sampled, voice=0.6, bars=12):
    """RMS (dB) of the choir alone: the same engine with and without it, subtracted."""
    with_choir = Engine(Style(genre=genre, voice=voice), seed=3, samples=sampled)
    without = Engine(Style(genre=genre, voice=0.0), seed=3, samples=sampled)
    x = np.concatenate([with_choir.render_bar().astype(float) - without.render_bar().astype(float)
                        for _ in range(bars)])
    return 20 * np.log10(np.sqrt(np.mean(np.square(x))))


@needs_sf2
@pytest.mark.parametrize("genre", ["lofi", "ambient", "synthwave"])
def test_the_sampled_choir_matches_the_procedural_level_within_3_db(genre):
    assert abs(choir_level(genre, True) - choir_level(genre, False)) <= 3.0


@needs_sf2
@pytest.mark.parametrize("name", genres.NAMES)
def test_the_sampled_choir_renders_in_every_genre(name, monkeypatch):
    from gentle_stream import vocals

    monkeypatch.setattr(vocals, "sung", lambda *a, **k: pytest.fail("the procedural voice ran"))
    e = Engine(Style(genre=name, voice=1.0), seed=3, samples=True)
    assert e.vocals_backend == "sampled"
    x = np.concatenate([e.render_bar() for _ in range(4)])
    assert np.all(np.isfinite(x)) and np.abs(x).max() < 1.0


def test_without_the_soundfont_the_choir_falls_back_to_the_procedural_voice():
    e = Engine(Style(voice=1.0), seed=3, samples=False)
    assert e.vocals_backend == "procedural"
    x = np.concatenate([e.render_bar() for _ in range(2)])
    assert np.all(np.isfinite(x))
