"""Text normalisation used to compare the model's quotes with the user's text. Pure.

Shared by the extraction guards (app.domain.extraction) and the number-word config loader
(app.config_files.extraction), so words Borys writes in the YAML are folded exactly like
the texts they are matched against.
"""

from __future__ import annotations

import re

# Typographic variants folded before the evidence comparison (speech-to-text and phone
# keyboards mix them): apostrophes, quotes, dashes, non-breaking spaces.
_FOLD = str.maketrans(
    {
        **dict.fromkeys(map(chr, (0x2019, 0x2018, 0x02BC, 0x60)), "'"),
        **dict.fromkeys(map(chr, (0x201C, 0x201D, 0x00AB, 0x00BB)), '"'),
        **dict.fromkeys(map(chr, (0x2013, 0x2014)), "-"),
        chr(0x00A0): " ",
        chr(0x0451): chr(0x0435),  # Cyrillic yo -> ie (Russian texts mix them)
        chr(0x0401): chr(0x0415),
    }
)
_WHITESPACE = re.compile(r"\s+")


def normalise_for_match(text: str) -> str:
    """Case-insensitive, whitespace-normalised form used to find evidence in the text."""
    return _WHITESPACE.sub(" ", text.translate(_FOLD).casefold()).strip()
