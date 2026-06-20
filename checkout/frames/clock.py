"""ClockFrame — ``DD MON YYYY`` on top, ``HH:MM:SS AM/PM`` on the bottom.

Formatting is done by hand (not ``strftime``) so it is deterministic and never
depends on the host locale: e.g. ``05 JUN 2026`` / ``08:47:03 PM``.
"""

from __future__ import annotations

from datetime import datetime

from .base import Frame

# 3-letter UPPERCASE month abbreviations, indexed by month number (1-12).
_MONTHS = (
    "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
    "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
)


class ClockFrame(Frame):
    name = "clock"

    def render(self, now: datetime, state: dict) -> tuple[str, str]:
        top = f"{now.day:02d} {_MONTHS[now.month - 1]} {now.year}"

        # 12-hour clock: 12 at midnight/noon (not 00), AM/PM uppercase.
        hour12 = now.hour % 12 or 12
        meridiem = "AM" if now.hour < 12 else "PM"
        bottom = f"{hour12:02d}:{now.minute:02d}:{now.second:02d} {meridiem}"

        # Logical strings; the renderer fits them to 20 cells with the active
        # per-line alignment (align_top / align_bottom).
        return top, bottom
