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

# Fade steps for a pulsing colon. The font's ':' is two 2x2 blocks of dots,
# [0, 6, 6, 0, 6, 6, 0] (8 dots). A VFD cell has no per-cell brightness (it is
# display-wide), so a colon "fades" by lighting fewer of its own dots:
COLON_MID = [0, 2, 4, 0, 2, 4, 0]   # 4 dots: one diagonal of each block
COLON_LOW = [0, 0, 2, 0, 2, 0, 0]   # 2 dots: the inner dot of each block

# A one-column colon (the centre column, 4 dots) — the weather clock's colon for
# "on" and "tick"; slimmer than the font's 2-wide ':'.
COLON_THIN = [0, 4, 4, 0, 4, 4, 0]

_LABELS = {"L": LABEL_L, "R": LABEL_R, "H": LABEL_H, "C": LABEL_C}


def label_glyph(letter: str) -> list[int]:
    """The inverted label glyph for ``letter`` (L, R, H or C), as a fresh list."""
    return list(_LABELS[letter])
