"""The app icon (M8-12), drawn with Pillow: no binary file in git.

Used by the tray (in memory) and the shortcuts (``data/journal.ico``, written by the
installer and by the tray at start when it is missing).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

_SIZE = 256
_BACKGROUND = (24, 39, 66, 255)
_LINE = (82, 196, 132, 255)
_ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def draw_icon(size: int = _SIZE) -> Image.Image:
    """A dark rounded square with a rising chart line."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    pad = size // 16
    draw.rounded_rectangle((pad, pad, size - pad, size - pad), radius=size // 5, fill=_BACKGROUND)
    s = size / _SIZE
    points = [(52, 180), (100, 128), (140, 156), (204, 76)]
    draw.line(
        [(x * s, y * s) for x, y in points], fill=_LINE, width=max(2, int(22 * s)), joint="curve"
    )
    return img


def write_icon(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    draw_icon().save(path, format="ICO", sizes=_ICO_SIZES)
    return path
