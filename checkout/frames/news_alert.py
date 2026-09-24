"""The NEWS ALERT screen: banner, scrolling headline, timing and effects.

Pure functions (no fetching, no state) used by DynamicFrame while an alert is
showing: the top line is a fixed banner of fade-in bars around " NEWS ALERT ",
the bottom scrolls "SOURCE: headline" in from the right edge, 1 + repeat
passes 6 spaces apart, until the last character leaves at the left; and
brightness can flash or throb.
"""

from __future__ import annotations

from ..driver import GLYPH_CODES
from ..glyphs import NEWS_BANNER_LEFT, NEWS_BANNER_RIGHT
from ..renderer import WIDTH

GAP = 6                      # spaces between repeats of the headline
_WORDS = " NEWS ALERT "      # 12 cells; 4 bars either side make 20

# The 7 distinct bars (the {g3} bar appears on both sides), in first-use order,
# each assigned a glyph slot for the alert's glyph set.
_BARS: list[list[int]] = []
for _rows in NEWS_BANNER_LEFT + NEWS_BANNER_RIGHT:
    if _rows not in _BARS:
        _BARS.append(_rows)
_CELL = {tuple(rows): chr(GLYPH_CODES[slot]) for slot, rows in enumerate(_BARS)}

# Brightness curves: a triangle through the four levels.
_TRIANGLE = (0, 1, 2, 3, 2, 1)
FLASH_STEP_MS = 120          # flash: 3 sweeps, then back up to the set level
THROB_STEP_MS = 150          # throb: sweeps for the whole alert


def alert_glyphs() -> dict[int, list[int]]:
    """The glyph set loaded while an alert shows: slot -> bar rows."""
    return {slot: list(rows) for slot, rows in enumerate(_BARS)}


def banner() -> str:
    """The 20-cell top line: bars, " NEWS ALERT ", bars."""
    left = "".join(_CELL[tuple(r)] for r in NEWS_BANNER_LEFT)
    right = "".join(_CELL[tuple(r)] for r in NEWS_BANNER_RIGHT)
    return left + _WORDS + right


def _tape(text: str, repeat: int) -> str:
    """Everything that scrolls past: a screen of blanks (so the text enters from
    the right), 1 + repeat copies of the text 6 spaces apart, then a screen of
    blanks (so the last character leaves at the left before it ends)."""
    blank = " " * WIDTH
    return blank + (" " * GAP).join([text] * (1 + max(0, repeat))) + blank


def window(text: str, elapsed_ms: int, repeat: int, speed_ms: int) -> str:
    """The 20 cells showing ``elapsed_ms`` into the alert (one cell per step)."""
    step = max(0, elapsed_ms) // max(1, speed_ms)
    return _tape(text, repeat)[step:step + WIDTH].ljust(WIDTH)


def duration_ms(text: str, repeat: int, speed_ms: int) -> int:
    """From the text's first character entering to its last one leaving."""
    return (len(_tape(text, repeat)) - WIDTH) * speed_ms


def flash_level(elapsed_ms: int, base: int) -> int:
    """Min to max three times, then step back up to the user's level ``base``."""
    steps = _TRIANGLE * 3 + tuple(range(0, base + 1))
    step = max(0, elapsed_ms) // FLASH_STEP_MS
    return steps[step] if step < len(steps) else base


def throb_level(elapsed_ms: int) -> int:
    """Min to max and back, over and over, while the alert shows."""
    return _TRIANGLE[(max(0, elapsed_ms) // THROB_STEP_MS) % len(_TRIANGLE)]
