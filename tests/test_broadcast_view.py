"""PM-045 T3: the broadcast picture, 1280x720 RGB frames drawn by the player with Pillow (never a screen capture)."""
import builtins
import time

import numpy as np
import pytest

from gentle_stream import broadcast_view
from gentle_stream.binaural import Binaural
from gentle_stream.broadcast_view import (
    HEIGHT,
    WIDTH,
    BroadcastUnavailable,
    BroadcastView,
    ViewText,
    view_text,
)
from gentle_stream.lines import binaural_line, journey_line

W, H = 1280, 720
TEXT = ViewText(title="♪ Midnight Rain", details="lofi · A minor · 72 bpm", mood="“rain on a window”",
                journey='Journey: Warm-up · stage 2/3 "Rise" · 62% · 84 → 100 bpm · 6:40 left',
                vocals="Vocals: choir (built-in) · 30%",
                binaural="Binaural: 200 Hz carrier · 6 Hz beat · 5% · headphones recommended")


def image(frame: bytes) -> np.ndarray:
    return np.frombuffer(frame, dtype=np.uint8).reshape(H, W, 3).astype(int)


@pytest.fixture(scope="module")
def view():
    return BroadcastView()


def test_a_frame_is_raw_rgb_at_720p(view):
    assert (WIDTH, HEIGHT) == (W, H)
    assert len(view.frame(TEXT, np.zeros(48))) == W * H * 3


def test_the_same_input_draws_the_same_bytes(view):
    levels = np.linspace(0, 1, 48)
    assert view.frame(TEXT, levels) == view.frame(TEXT, levels)


def test_the_spectrum_follows_the_levels(view):
    quiet, loud = image(view.frame(TEXT, np.zeros(48))), image(view.frame(TEXT, np.ones(48)))
    top, bottom = view.spectrum_box[1], view.spectrum_box[3]
    region = slice(top, bottom)
    assert loud[region].sum() > quiet[region].sum() * 3
    one = np.zeros(48)
    one[0] = 1.0                                              # only the lowest band
    lit = image(view.frame(TEXT, one))[region] - quiet[region]  # what the levels added to the picture
    left, right = view.spectrum_box[0], view.spectrum_box[2]
    width = (right - left) // 48
    assert lit[:, left:left + width].any() and not lit[:, left + width:right].any()


def test_the_text_is_drawn_and_an_empty_line_leaves_the_background(view):
    full = image(view.frame(TEXT, np.zeros(48)))
    bare = image(view.frame(ViewText(title=TEXT.title, details=TEXT.details), np.zeros(48)))
    assert (full != bare).any()                                # mood, journey, vocals, binaural are drawn
    other = image(view.frame(ViewText(title="♪ Something else", details=TEXT.details), np.zeros(48)))
    assert (other != bare).any()                               # and the title is


def test_it_draws_ten_frames_a_second_with_room_to_spare(view):
    levels = np.random.default_rng(1).random(48)
    start = time.perf_counter()
    for _ in range(10):
        view.frame(TEXT, levels)
    assert (time.perf_counter() - start) / 10 < 0.05


def test_without_pillow_it_says_how_to_install_it(monkeypatch):
    real = builtins.__import__

    def no_pil(name, *args, **kw):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("No module named 'PIL'")
        return real(name, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", no_pil)
    with pytest.raises(BroadcastUnavailable, match=r"a live broadcast needs Pillow: "
                                                   r"pip install 'gentle-stream\[broadcast\]'"):
        BroadcastView()


def test_the_picture_shows_what_the_tui_shows():
    from gentle_stream.engine import Engine
    from gentle_stream.player import Player
    from gentle_stream.style import Style
    from tests.test_player import FakeStream

    player = Player(Engine(Style(name="Midnight Rain", mood="rain on a window", voice=0.3), seed=1),
                    stream_factory=FakeStream)
    player.engine.queue_binaural(Binaural(200, 6, 0.05))
    player.engine.render_bar()
    now = player.now
    text = view_text(player)
    assert text.title == f"♪ {now.style.name}" and text.details == now.style.summary()
    assert text.mood == f"“{now.style.mood}”"
    assert text.journey == journey_line(now.journey, max(0.0, player.elapsed_seconds - now.start_seconds))
    assert text.binaural == binaural_line(player.binaural) != ""
    assert text.vocals == f"Vocals: choir ({player.vocals_backend}) · 30%"


def test_the_picture_makes_no_claims_about_the_listener():
    words = ("focus", "sleep", "relax", "heal", "therapy", "anxiety", "health", "cure", "brainwave")
    fixed = " ".join(v for v in vars(broadcast_view).values() if isinstance(v, str)).lower()
    assert not any(word in fixed for word in words)


def test_the_tui_still_finds_the_lines_where_it_imported_them():
    from gentle_stream import app

    assert app.journey_line is journey_line and app.binaural_line is binaural_line


def test_a_long_line_is_cut_inside_the_margins(view):
    from gentle_stream.broadcast_view import MARGIN

    long = ViewText(title=TEXT.title, details=TEXT.details, journey=TEXT.journey + " · mood" * 60)
    drawn = image(view.frame(long, np.zeros(48))) != image(view.frame(ViewText(TEXT.title, TEXT.details), np.zeros(48)))
    columns = np.flatnonzero(drawn.any(axis=(0, 2)))
    assert columns.size and columns.max() < W - MARGIN


def test_silent_vocals_and_no_binaural_leave_their_lines_empty_as_in_the_tui():
    from gentle_stream.engine import Engine
    from gentle_stream.player import Player
    from gentle_stream.style import Style
    from tests.test_player import FakeStream

    player = Player(Engine(Style(name="Plain", voice=0.0), seed=1), stream_factory=FakeStream)
    player.engine.render_bar()
    text = view_text(player)
    assert (text.mood, text.vocals, text.binaural) == ("", "", "")


# ------------------------------------------------------------ after the first live test (S6)
LONG = ViewText(title="♪ Café Noir, a long name for a quiet late evening", details=TEXT.details, mood=TEXT.mood,
                journey='Journey: Warm-up · stage 2/3 "Rise" · 62% · 84 → 100 bpm · 6:40 left · mood "calm": '
                        'energy -0.10 until "Rise" ends',
                vocals="Vocals: choir (pack: FreePats Synth Pad Choir) · 44%", binaural=TEXT.binaural)


def text_pixels(frame: bytes, view) -> np.ndarray:
    """Where anything but the background was drawn, outside the spectrum box."""
    picture = image(frame)
    drawn = (picture != np.array(broadcast_view.BACKGROUND)).any(axis=2)
    left, top, right, bottom = view.spectrum_box
    drawn[top:bottom, left:right] = False
    return drawn


def test_every_character_drawn_has_a_glyph(view):
    """No empty boxes: "♪", "→" and accented letters exist in the font used, or are replaced by ones that do."""
    for line in (LONG.title, LONG.journey, "Mañana · canción · été"):
        assert view.missing(view.drawable(line)) == []


def test_without_a_font_that_has_them_glyphs_are_replaced_not_drawn_as_boxes(monkeypatch):
    monkeypatch.setattr(broadcast_view, "FONT_FILES", ())
    plain = BroadcastView()                                  # Pillow's own font: no ♪, no →, no é
    assert plain.drawable("♪ Café 84 → 100") == "Cafe 84 -> 100"
    assert plain.missing(plain.drawable(LONG.journey)) == []


def test_the_text_stays_in_the_centre_column_a_vertical_crop_keeps(view):
    """A 9:16 crop of a 720-pixel-high frame keeps the middle 405 pixels: all text is drawn there."""
    drawn = text_pixels(view.frame(LONG, np.zeros(48)), view)
    columns = np.flatnonzero(drawn.any(axis=0))
    keep = 720 * 9 / 16
    assert columns.min() >= (W - keep) / 2 and columns.max() <= (W + keep) / 2


def test_long_lines_wrap_instead_of_running_off(view):
    one = text_pixels(view.frame(ViewText(title="♪ X", details="", journey="Journey: short"), np.zeros(48)), view)
    many = text_pixels(view.frame(ViewText(title="♪ X", details="", journey=LONG.journey), np.zeros(48)), view)

    def rows(drawn):
        return np.flatnonzero(drawn.any(axis=1))

    assert rows(many).max() - rows(many).min() > rows(one).max() - rows(one).min() + 40   # more lines, not cut


def test_the_spectrum_spans_the_whole_width(view):
    left, _, right, _ = view.spectrum_box
    assert left <= 64 and right >= W - 64
