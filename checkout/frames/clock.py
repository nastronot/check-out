"""ClockFrame — date on top, wall-clock time on the bottom."""

from __future__ import annotations

from datetime import datetime

from .base import Frame


class ClockFrame(Frame):
    name = "clock"

    def render(self, now: datetime, state: dict) -> tuple[str, str]:
        # Logical strings; the renderer centers them within the 20-char width.
        return now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")
