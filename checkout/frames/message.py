"""MessageFrame — show a static custom message across the two lines.

Fitting rules (logical strings; the renderer centers each line afterward):
  - An explicit newline splits the message into top / bottom.
  - Otherwise the message is word-wrapped greedily across the two 20-char lines.
  - Anything past 40 chars (or a single word longer than a line) is truncated by
    the renderer.
"""

from __future__ import annotations

from datetime import datetime

from .. import config
from ..driver import apply_glyph_placeholders
from .base import Frame

WIDTH = config.COLS  # 20


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


class MessageFrame(Frame):
    name = "message"

    def render(self, now: datetime, state: dict) -> tuple[str, str]:
        # Substitute {gN} glyph placeholders first, so widths are measured on the
        # final single-char glyphs (not the 4-char placeholder text).
        message = apply_glyph_placeholders((state.get("message") or "").strip("\n"))
        if "\n" in message:
            top, _, bottom = message.partition("\n")
            return top, bottom
        return _wrap_two_lines(message)
