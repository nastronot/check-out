"""Hand-drawn 5x7 label and icon bitmaps shared by every mode.

Rows are editor-natural: 7 ints, top row first, LOW 5 bits = columns 1..5
(bit0 = column 1); the driver translates them to the wire format. One home for
them means a mode that needs a label imports it instead of redrawing it, and the
preview mirrors whatever the daemon reports as loaded.

The labels are INVERTED (a lit frame with the letter cut out dark) so a label
cell reads as a tag, not as text.
"""

from __future__ import annotations

LABEL_L = [31, 29, 29, 29, 29, 17, 31]
LABEL_R = [31, 17, 21, 25, 21, 21, 31]
LABEL_H = [31, 21, 21, 17, 21, 21, 31]
LABEL_C = [31, 17, 21, 29, 21, 17, 31]

# A 3x3 ring in the top rows, for temperatures.
DEGREE = [4, 10, 4, 0, 0, 0, 0]

# Weather clock colons, drawn by hand. A VFD cell has no per-cell brightness
# (it is display-wide), so the colon animates by changing its dots instead.
COLON_THIN = [0, 4, 4, 0, 4, 4, 0]      # the on/tick colon: centre column, 4 dots
COLON_DOT = [0, 0, 4, 0, 4, 0, 0]       # the two inner dots only
COLON_TWIST_R = [0, 12, 4, 0, 4, 6, 0]  # wiggle: top hooks right, bottom hooks left
COLON_TWIST_L = [0, 6, 4, 0, 4, 12, 0]  # wiggle: the mirror (top left, bottom right)
COLON_TWINKLE_SMALL = [0, 14, 4, 0, 4, 14, 0]  # twinkle: a bar caps each dot
COLON_TWINKLE_BIG = [4, 14, 4, 0, 4, 14, 4]    # twinkle: each dot a small plus

_LABELS = {"L": LABEL_L, "R": LABEL_R, "H": LABEL_H, "C": LABEL_C}


def label_glyph(letter: str) -> list[int]:
    """The inverted label glyph for ``letter`` (L, R, H or C), as a fresh list."""
    return list(_LABELS[letter])
