"""The broadcast picture (PM-045): 1280x720 RGB frames drawn by the player with Pillow, never captured from a screen.

A frame shows what the TUI shows: the style name, its summary and mood, the journey, vocals and binaural lines, and
a spectrum. The text changes rarely, so it is drawn once per change; each frame copies it and paints the spectrum
bars with numpy, well within the 30 frames a second the broadcast sends.

One video goes out and the service crops it for phones (a 9:16 slice of the middle), so the text is centred and wrapped
inside that middle column and only the spectrum spans the whole width: the same picture reads on both. The font is a
system one that has "♪", "→" and accented letters; without one, Pillow's own font is used and the characters it lacks
are replaced ("→" by "->", "é" by "e", "♪" left out), never drawn as empty boxes.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

import numpy as np

from .lines import binaural_line, journey_line

WIDTH, HEIGHT = 1280, 720
FPS = 30
SAFE_WIDTH = 400                   # the text column: a 9:16 crop of a 720-pixel-high frame keeps the middle 405
FONT_FILES = ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", "/Library/Fonts/Arial Unicode.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/TTF/DejaVuSans.ttf",
              "/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/noto/NotoSans-Regular.ttf",
              "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", "/System/Library/Fonts/Menlo.ttc")
REPLACE = {"♪": "", "♫": "", "→": "->", "←": "<-", "“": '"', "”": '"', "…": "...", "·": "-"}
INSTALL_HINT = "a live broadcast needs Pillow: pip install 'gentle-stream[broadcast]'"

# the TUI's gentleman theme
BACKGROUND = (0x14, 0x0A, 0x12)
ROSE = (0xFF, 0x76, 0xC3)
FOREGROUND = (0xF6, 0xEF, 0xF3)
MUTED = (0xA7, 0x8E, 0x9B)
MARGIN = 64
BAR_GAP = 2


class BroadcastUnavailable(RuntimeError):
    """The broadcast picture cannot be drawn here (Pillow is not installed)."""


@dataclass(frozen=True)
class ViewText:
    """The lines of one picture; an empty line is not drawn."""

    title: str
    details: str
    mood: str = ""
    journey: str = ""
    vocals: str = ""
    binaural: str = ""


def view_text(player) -> ViewText:
    """What the TUI shows for `player` now, line for line."""
    now = player.now
    style = now.style
    return ViewText(
        title=f"♪ {style.name}",
        details=style.summary(),
        mood=f"“{style.mood}”" if style.mood else "",
        journey=journey_line(now.journey, max(0.0, player.elapsed_seconds - now.start_seconds)),
        vocals=f"Vocals: choir ({player.vocals_backend}) · {round(style.voice * 100)}%" if style.voice > 0 else "",
        binaural=binaural_line(player.binaural),
    )


class BroadcastView:
    """Draws frames as raw RGB24 bytes, WIDTH x HEIGHT, the input of the encoder."""

    def __init__(self):
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            raise BroadcastUnavailable(INSTALL_HINT) from None
        self._image, self._draw = Image, ImageDraw
        self._fonts = {size: _font(ImageFont, size) for size in (40, 24, 22, 20)}
        probe = self._fonts[24]
        self._nothing = _shape(Image, ImageDraw, probe, "\U0010FFFD")   # what a character the font lacks looks like
        self._has: dict[str, bool] = {}
        self.spectrum_box = (MARGIN, 300, WIDTH - MARGIN, 470)
        top, bottom = self.spectrum_box[1], self.spectrum_box[3]
        # rose at the top of the box fading to muted at its base, one color per pixel row
        t = np.linspace(0.0, 1.0, bottom - top)[:, None]
        self._gradient = (np.array(ROSE) * (1 - t) + np.array(MUTED) * t).astype(np.uint8)
        self._text: ViewText | None = None
        self._base = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)

    def frame(self, text: ViewText, levels: np.ndarray) -> bytes:
        """One picture: `text` and a bar per entry of `levels` (0..1, low to high frequencies)."""
        if text != self._text:
            self._base = self._draw_text(text)
            self._text = text
        picture = self._base.copy()
        left, top, right, bottom = self.spectrum_box
        n = len(levels)
        if n:
            width = (right - left) // n
            heights = np.round(np.clip(np.asarray(levels, dtype=float), 0.0, 1.0) * (bottom - top)).astype(int)
            columns = np.zeros(right - left, dtype=int)          # bar height under each pixel column
            for i, h in enumerate(heights):
                columns[i * width:(i + 1) * width - BAR_GAP] = h
            rows = np.arange(bottom - top)[:, None]
            lit = rows >= (bottom - top) - columns[None, :]
            region = picture[top:bottom, left:right]
            region[lit] = np.broadcast_to(self._gradient[:, None, :], region.shape)[lit]
        return picture.tobytes()

    # -------------------------------------------------------- characters the font can draw
    def missing(self, text: str) -> list[str]:
        """The characters of `text` the font has no glyph for (spaces aside)."""
        return [ch for ch in dict.fromkeys(text) if not ch.isspace() and not self._can(ch)]

    def drawable(self, text: str) -> str:
        """`text` with every character the font lacks replaced by one it has: a known stand-in, the letter without
        its accent, or nothing."""
        out = []
        for ch in text:
            if ch.isspace() or self._can(ch):
                out.append(ch)
                continue
            stand_in = REPLACE.get(ch)
            if stand_in is None:
                base = unicodedata.normalize("NFKD", ch)[:1]
                stand_in = base if base and base != ch else ""
            out.append("".join(c for c in stand_in if self._can(c)))
        return " ".join("".join(out).split())

    def _can(self, ch: str) -> bool:
        if ch not in self._has:
            self._has[ch] = _shape(self._image, self._draw, self._fonts[24], ch) != self._nothing
        return self._has[ch]

    # -------------------------------------------------------- the text, centred in the column a phone keeps
    def _draw_text(self, text: ViewText) -> np.ndarray:
        image = self._image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
        draw = self._draw.Draw(image)
        top = [(text.title, 40, ROSE, 2), (text.details, 24, FOREGROUND, 3), (text.mood, 22, MUTED, 2)]
        bottom = [(text.journey, 20, FOREGROUND, 4), (text.vocals, 20, MUTED, 2), (text.binaural, 20, MUTED, 2)]
        self._column(draw, top, 28, self.spectrum_box[1] - 12)
        self._column(draw, bottom, self.spectrum_box[3] + 18, HEIGHT - 8)
        return np.asarray(image, dtype=np.uint8).copy()

    def _column(self, draw, blocks, y: int, limit: int) -> None:
        """Draw each (text, size, colour, most lines) block centred and wrapped, from `y` down, never past `limit`."""
        for text, size, color, most in blocks:
            if not text:
                continue
            font = self._fonts[size]
            step = round(size * 1.3)
            for line in self._wrap(draw, self.drawable(text), font, most):
                if y + step > limit:
                    return
                width = draw.textlength(line, font=font)
                draw.text(((WIDTH - width) / 2, y), line, font=font, fill=color)
                y += step
            y += size // 2

    @staticmethod
    def _wrap(draw, text: str, font, most: int) -> list[str]:
        """`text` in lines no wider than SAFE_WIDTH, broken between its " · " parts, then between words; at most
        `most` lines, the last cut with "..." when more would follow."""
        def fits(line: str) -> bool:
            return draw.textlength(line, font=font) <= SAFE_WIDTH

        words: list[str] = []
        for i, part in enumerate(text.split(" · ")):
            chunk = part if i == 0 else "· " + part
            words += [chunk] if fits(chunk) else chunk.split(" ")
        lines: list[str] = []
        for word in words:
            joined = f"{lines[-1]} {word}" if lines else word
            if lines and fits(joined):
                lines[-1] = joined
            else:
                lines.append(word)
        lines = [line.removeprefix("· ") for line in lines]
        while any(not fits(line) for line in lines):          # a single word wider than the column
            lines = [line if fits(line) else line[:-2] + "…" for line in lines]
        if len(lines) > most:
            last = lines[most - 1]
            while last and not fits(last + "..."):
                last = last[:-1]
            lines = [*lines[:most - 1], last.rstrip() + "..."]
        return lines


def _font(image_font, size: int):
    """A system font that has "♪", "→" and accented letters, else Pillow's own."""
    for path in FONT_FILES:
        try:
            return image_font.truetype(path, size)
        except OSError:
            continue
    return image_font.load_default(size=size)


def _shape(image, image_draw, font, ch: str) -> bytes:
    """The pixels of `ch` drawn alone: equal to the shape of a lacking character when the font has no glyph."""
    picture = image.new("L", (64, 64))
    image_draw.Draw(picture).text((8, 8), ch, font=font, fill=255)
    return picture.tobytes()
