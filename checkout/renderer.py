"""Pure rendering helpers: fit/pad/center and marquee ticker.

No serial, no I/O — every function here is a pure transform of strings, so the
whole module is trivially unit-testable on any machine. The daemon feeds a
frame's logical (top, bottom) strings plus per-line align/scroll hints through
``render_lines`` to get the final exact-width pair handed to ``driver.show()``.
"""

from __future__ import annotations

from . import config

WIDTH = config.COLS  # 20

# Gap (in spaces) appended after a scrolling string before it repeats, so the
# end and start of the marquee don't run together.
TICKER_GAP = 4


def fit_line(text: str, align: str = "center", width: int = WIDTH) -> str:
    """Pad or truncate ``text`` to exactly ``width`` chars.

    ``align`` is "left", "center" (default), or "right". Text longer than
    ``width`` is truncated (alignment then has no effect).
    """
    text = text[:width]
    if align == "left":
        return text.ljust(width)
    if align == "right":
        return text.rjust(width)
    if align == "center":
        return text.center(width)
    raise ValueError(f"unknown align {align!r}")


def ticker_window(
    text: str, offset: int, width: int = WIDTH, gap: int = TICKER_GAP
) -> str:
    """Return the visible ``width``-char window of a scrolling marquee.

    The marquee is ``text`` followed by ``gap`` spaces, repeated forever; the
    returned window starts at ``offset`` (wrapping around the cycle). Strings
    that already fit are returned left-justified with no scrolling.
    """
    if len(text) <= width:
        return text.ljust(width)
    cycle = text + " " * gap
    n = len(cycle)
    offset %= n
    # Double the cycle so a single slice covers any wrap point.
    return (cycle + cycle)[offset : offset + width]


def render_line(
    text: str, align: str = "center", offset: int | None = None, width: int = WIDTH
) -> str:
    """Render one logical line to exactly ``width`` chars.

    When ``offset`` is given the line scrolls via :func:`ticker_window`;
    otherwise it is statically fit via :func:`fit_line`.
    """
    if offset is not None:
        return ticker_window(text, offset, width=width)
    return fit_line(text, align=align, width=width)


def render_lines(
    top: str,
    bottom: str,
    top_align: str = "center",
    bottom_align: str = "center",
    top_offset: int | None = None,
    bottom_offset: int | None = None,
) -> tuple[str, str]:
    """Render a frame's logical (top, bottom) into the final 20-char pair."""
    return (
        render_line(top, align=top_align, offset=top_offset),
        render_line(bottom, align=bottom_align, offset=bottom_offset),
    )
