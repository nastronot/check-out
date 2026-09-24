"""MessageFrame — the message mode: a custom message across the two rows.

Each row picks a content SOURCE (``scroll_{row}_source``):
  - "message" — its line of the message; it either sits still (aligned by the
    renderer) or scrolls left/right (``scroll_{row}``, ``scroll_dir_{row}``,
    shared ``scroll_speed_ms``).
  - "clock"   — the live 12-hour time line, refreshed each second.

Which text goes to which row:
  - An explicit newline splits the message into top / bottom.
  - Otherwise, when both rows show the message and neither scrolls, it is
    word-wrapped greedily across the two 20-char lines.
  - Otherwise the single line goes to the first message row (the top, or the
    bottom when the top shows the clock), where it may scroll.

This replaced the separate "scroll" mode in v1.4.0 (the two were near-duplicates);
legacy modes "scroll" and "ticker" map here. Static rows are returned as logical
strings (the renderer fits/aligns them); scrolling rows come back as their exact
20-cell window, which the renderer passes through unchanged.
"""

from __future__ import annotations

from datetime import datetime

from .. import config
from ..driver import apply_glyph_placeholders
from ..renderer import ticker_window
from .base import Frame
from .clock import clock_time

WIDTH = config.COLS  # 20

# Software scroll: each step redraws cells at 9600 baud, so a step faster than
# this floor can't keep up — scroll_speed_ms is clamped to it.
SCROLL_FLOOR_MS = 60


def _wrap_two_lines(text: str, width: int = WIDTH) -> tuple[str, str]:
    """Greedily pack ``text``'s words into two lines of at most ``width`` chars.

    Words are split on the SPACE character only — NOT ``str.split()``, which
    treats the user-glyph codes 0x1C–0x1E (slots 6–8) as whitespace and would
    silently drop those glyphs from the line.
    """
    words = [w for w in text.split(" ") if w]
    if not words:
        return "", ""
    top = ""
    i = 0
    while i < len(words):
        word = words[i]
        candidate = word if not top else f"{top} {word}"
        if len(candidate) <= width:
            top = candidate
            i += 1
        elif not top:
            # A single word longer than a line: place it (renderer truncates) so
            # we never loop forever on an unbreakable word.
            top = word
            i += 1
            break
        else:
            break
    bottom = " ".join(words[i:])
    return top, bottom


def _scroll_offset(now_ms: int, speed_ms, direction) -> int:
    """The window offset for a scrolling row: "left" advances (text moves left,
    new chars enter from the right); "right" reverses it."""
    step = max(SCROLL_FLOOR_MS, int(speed_ms or 300))
    raw = now_ms // step
    return -raw if direction == "right" else raw


class MessageFrame(Frame):
    name = "message"

    def render(self, now: datetime, state: dict) -> tuple[str, str]:
        # Substitute {gN} glyph placeholders first, so widths are measured on the
        # final single-char glyphs (not the 4-char placeholder text).
        message = apply_glyph_placeholders((state.get("message") or "").strip("\n"))
        sources = {r: state.get(f"scroll_{r}_source", "message") for r in ("top", "bottom")}
        scrolls = {r: bool(state.get(f"scroll_{r}")) for r in ("top", "bottom")}

        if "\n" in message:
            top, _, bottom = message.partition("\n")
        elif sources["top"] == "clock":
            top, bottom = "", message
        elif sources["bottom"] == "message" and not any(scrolls.values()):
            top, bottom = _wrap_two_lines(message)
        else:
            top, bottom = message, ""

        now_ms = int(now.timestamp() * 1000)
        speed = state.get("scroll_speed_ms", 300)

        def row(which: str, text: str) -> str:
            if sources[which] == "clock":
                return clock_time(now)
            if scrolls[which]:
                offset = _scroll_offset(now_ms, speed, state.get(f"scroll_dir_{which}"))
                return ticker_window(text, offset)
            return text

        return row("top", top), row("bottom", bottom)
