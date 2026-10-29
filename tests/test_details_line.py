"""The details line says what plays in the genre playing, not the shared names of the style's fields (the maintainer
saw "piano/piano · drums lofi" during a synthwave stage, where "piano" means polysynth stabs and a saw lead)."""
import pytest

from gentle_stream.broadcast_view import view_text
from gentle_stream.genres import get
from gentle_stream.lines import details_line
from gentle_stream.style import Style, genre_names

SYNTHWAVE = Style(genre="synthwave", key="D", mode="minor", bpm=106.3, chords="piano", lead="piano", drums="lofi")


def test_a_synthwave_stage_shows_synthwave_instruments():
    assert details_line(SYNTHWAVE) == ("synthwave · D minor · 106.3 bpm · 1-6-3-7 · brassy polysynth stabs · "
                                       "bright saw lead · drums")


def test_lofi_reads_as_it_did_with_its_own_names():
    style = Style(genre="lofi", key="A", mode="minor", bpm=72.0, chords="rhodes", lead="nylon", drums="lofi")
    assert details_line(style) == ("lofi · A minor · 72 bpm · 1-6-3-7 · rhodes electric piano · nylon guitar · "
                                   "lofi drums")


@pytest.mark.parametrize("lead, drums, tail", [("none", "none", "no lead · no drums"),
                                                ("pad", "soft", "detuned saw pad · soft drums"),
                                                ("rhodes", "busy", "square lead · busy drums")])
def test_no_lead_no_drums_and_the_other_patterns(lead, drums, tail):
    style = Style(genre="synthwave", key="D", mode="minor", bpm=110.0, chords="pad", lead=lead, drums=drums)
    assert details_line(style).endswith(tail)


@pytest.mark.parametrize("genre", genre_names())
def test_every_genre_describes_every_choice(genre):
    """No genre falls back to the bare field names: each one says what its four choices sound like."""
    voices = get(genre).voices
    assert set(voices) >= {"piano", "rhodes", "nylon", "pad"}
    for chords in ("piano", "rhodes", "nylon", "pad"):
        line = details_line(Style(genre=genre, chords=chords, lead=chords))
        assert f"· {chords}/{chords} ·" not in line


def test_the_tui_and_the_picture_show_it():
    from gentle_stream.engine import Engine
    from gentle_stream.player import Player
    from tests.test_player import FakeStream

    player = Player(Engine(SYNTHWAVE, seed=1, samples=False), stream_factory=FakeStream)
    assert view_text(player).details == details_line(player.now.style)
