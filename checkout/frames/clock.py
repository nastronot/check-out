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


def clock_date(now: datetime) -> str:
    """``DD MON YYYY`` (locale-independent), e.g. ``05 JUN 2026``."""
    return f"{now.day:02d} {_MONTHS[now.month - 1]} {now.year}"


def clock_time(now: datetime) -> str:
    """12-hour ``HH:MM:SS AM/PM`` (12 at midnight/noon), e.g. ``08:47:03 PM``."""
    hour12 = now.hour % 12 or 12
    meridiem = "AM" if now.hour < 12 else "PM"
    return f"{hour12:02d}:{now.minute:02d}:{now.second:02d} {meridiem}"


class ClockFrame(Frame):
    name = "clock"

    def render(self, now: datetime, state: dict) -> tuple[str, str]:
        # Logical strings; the renderer fits them to 20 cells with the active
        # per-line alignment (align_top / align_bottom).
        return clock_date(now), clock_time(now)
