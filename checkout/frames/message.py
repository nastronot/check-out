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
from .base import Frame

WIDTH = config.COLS  # 20


def _wrap_two_lines(text: str, width: int = WIDTH) -> tuple[str, str]:
    """Greedily pack ``text``'s words into two lines of at most ``width`` chars."""
    words = text.split()
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
        message = (state.get("message") or "").strip("\n")
        if "\n" in message:
            top, _, bottom = message.partition("\n")
            return top, bottom
        return _wrap_two_lines(message)
