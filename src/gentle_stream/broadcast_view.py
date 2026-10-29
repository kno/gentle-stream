"""The broadcast picture (PM-045): 1280x720 RGB frames drawn by the player with Pillow, never captured from a screen.

A frame shows what the TUI shows: the style name, its summary and mood, the journey, vocals and binaural lines, and
a spectrum. The text changes rarely, so it is drawn once per change; each frame copies it and paints the spectrum
bars with numpy, well within the 10 frames a second the broadcast sends.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .lines import binaural_line, journey_line

WIDTH, HEIGHT = 1280, 720
FPS = 10
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
        self._fonts = {size: ImageFont.load_default(size=size) for size in (56, 30, 26, 24)}
        self.spectrum_box = (MARGIN, 250, WIDTH - MARGIN, 540)
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

    def _draw_text(self, text: ViewText) -> np.ndarray:
        image = self._image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
        draw = self._draw.Draw(image)
        lines = [(text.title, 56, 56, ROSE), (text.details, 30, 132, FOREGROUND), (text.mood, 26, 180, MUTED),
                 (text.journey, 24, 572, FOREGROUND), (text.vocals, 24, 612, MUTED), (text.binaural, 24, 652, MUTED)]
        for line, size, y, color in lines:
            if line:
                font = self._fonts[size]
                draw.text((MARGIN, y), self._fit(draw, line, font), font=font, fill=color)
        return np.asarray(image, dtype=np.uint8).copy()

    @staticmethod
    def _fit(draw, line: str, font) -> str:
        """`line`, cut with an ellipsis when it is wider than the picture's margins."""
        room = WIDTH - 2 * MARGIN
        if draw.textlength(line, font=font) <= room:
            return line
        while line and draw.textlength(line + "…", font=font) > room:
            line = line[:-1]
        return line.rstrip() + "…"
