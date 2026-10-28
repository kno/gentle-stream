"""PM-016: a genre step that changes mode prepares the new key."""
import pytest

from gentle_stream import genres
from gentle_stream.composer import harmonic_handoff
from gentle_stream.engine import Engine
from gentle_stream.journey import Journey, Stage
from gentle_stream.style import KEYS, MODES, Style


def collection(key: str, mode: str) -> frozenset[int]:
    return frozenset((KEYS.index(key) + step) % 12 for step in MODES[mode])


def fifths(a: frozenset[int], b: frozenset[int]) -> int:
    """Steps on the circle of fifths between two diatonic collections (by their major-scale tonic)."""
    def tonic(c):
        return next(k for k in range(12) if collection(KEYS[k], "major") == c)
    return min((tonic(a) * 7 - tonic(b) * 7) % 12, (tonic(b) * 7 - tonic(a) * 7) % 12)


@pytest.mark.parametrize("source", genres.NAMES)
@pytest.mark.parametrize("target", genres.NAMES)
def test_every_genre_pair_lands_within_one_fifth_or_on_the_relative_key(source, target):
    modes = genres.get(target).modes
    for mode in genres.get(source).modes:
        for key in KEYS:
            new_key, new_mode = harmonic_handoff(key, mode, modes)
            assert new_mode in modes
            relative = collection(new_key, new_mode) == collection(key, mode)
            assert relative or fifths(collection(new_key, new_mode), collection(key, mode)) <= 1


def test_a_mode_the_target_genre_plays_keeps_key_and_mode():
    assert harmonic_handoff("D", "minor", genres.get("synthwave").modes) == ("D", "minor")


def test_an_unsupported_mode_moves_to_the_most_typical_relative_mode():
    # C lydian shares its notes with E minor, A dorian and G major; synthwave lists minor first
    assert harmonic_handoff("C", "lydian", ("minor", "dorian", "major")) == ("E", "minor")
    assert harmonic_handoff("C", "lydian", ("major", "minor")) == ("G", "major")
    assert harmonic_handoff("A", "minor", ("phrygian",)) == ("E", "phrygian")


AMBIENT_TO_SYNTHWAVE = Journey("handoff", (
    Stage("Ambient", 20, {"bpm": 70.0}, genre="ambient"),
    Stage("Synthwave", 60, {"bpm": 70.0}, genre="synthwave"),
))


def run_to_the_switch(style):
    """Render the journey until the genre changes: (engine, the last plan of the old piece, its ton, its style)."""
    e = Engine(style, seed=4, samples=False)
    e.queue_journey(AMBIENT_TO_SYNTHWAVE)
    e.render_bar()
    while True:
        old_piece, old_ton, old_style, last = e.piece, e.ton, e.style, e.composer.plan(e.bar - 1)
        e.render_bar()
        if e.piece != old_piece:
            return e, last, old_ton, old_style


def test_the_last_bar_before_the_switch_carries_the_pivot_dominant_of_the_new_key():
    e, last, old_ton, old_style = run_to_the_switch(Style(genre="ambient", key="C", mode="lydian"))
    assert (e.style.genre, e.style.key, e.style.mode) == ("synthwave", "E", "minor")
    assert last.passing is not None
    root = (old_ton + last.key_offset + last.passing.tones[0]) % 12
    assert root == (KEYS.index("E") + 7) % 12                   # B7, the dominant of E minor
    intervals = [(t - last.passing.tones[0]) % 12 for t in last.passing.tones]
    assert intervals == [0, 4, 7, 10]                            # a dominant seventh
    assert old_style.mode == "lydian"


def test_a_supported_mode_keeps_the_key_and_still_gets_the_pivot():
    e, last, old_ton, _ = run_to_the_switch(Style(genre="ambient", key="D", mode="minor"))
    assert (e.style.genre, e.style.key, e.style.mode) == ("synthwave", "D", "minor")
    assert last.passing is not None
    assert (old_ton + last.key_offset + last.passing.tones[0]) % 12 == (KEYS.index("D") + 7) % 12


def test_music_without_a_journey_is_unchanged():
    a = Engine(Style(genre="ambient", key="C", mode="lydian"), seed=4, samples=False)
    plans = [a.composer.plan(bar) for bar in range(40)]
    b = Engine(Style(genre="ambient", key="C", mode="lydian"), seed=4, samples=False)
    assert plans == [b.composer.plan(bar) for bar in range(40)]
