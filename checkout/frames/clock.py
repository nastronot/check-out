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


# 3-letter UPPERCASE weekday names, indexed by datetime.weekday() (Mon = 0).
_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _hour12(now: datetime) -> int:
    """12-hour clock hour: 12 at midnight and noon, else 1..11."""
    return now.hour % 12 or 12


def numeric_date(now: datetime) -> str:
    """``MM/DD/YY``, e.g. ``09/23/26`` (8 chars)."""
    return f"{now.month:02d}/{now.day:02d}/{now.year % 100:02d}"


def weekday(now: datetime) -> str:
    """3-letter weekday, e.g. ``WED``."""
    return _DAYS[now.weekday()]


def hh_mm(now: datetime, colon: str = ":") -> str:
    """12-hour ``HH:MM`` (no AM/PM), e.g. ``08:33`` (5 chars).

    ``colon`` is the one character between HH and MM, so a caller can blink or
    animate it (dynamic mode) without re-deriving the layout.
    """
    return f"{_hour12(now):02d}{colon}{now.minute:02d}"


def short_date_time(now: datetime, colon: str = ":") -> str:
    """``MM/DD/YY DAY HH:MM`` (12-hour, no AM/PM), e.g. ``09/23/26 WED 08:33``."""
    return f"{numeric_date(now)} {weekday(now)} {hh_mm(now, colon)}"


def compact_date_time(now: datetime) -> str:
    """``M/D/YY DAY H:MM`` without leading zeros, e.g. ``9/23/26 WED 8:33``.

    Month, day and hour drop their leading zero (the year and minutes keep
    theirs), and every field is one space from the next, so a 2-digit month,
    day or hour shifts what follows right by one. 15-18 chars (longest:
    ``12/31/26 THU 12:59``)."""
    return (f"{now.month}/{now.day}/{now.year % 100:02d} "
            f"{weekday(now)} {_hour12(now)}:{now.minute:02d}")


def clock_date(now: datetime) -> str:
    """``DD MON YYYY`` (locale-independent), e.g. ``05 JUN 2026``."""
    return f"{now.day:02d} {_MONTHS[now.month - 1]} {now.year}"


def clock_time(now: datetime) -> str:
    """12-hour ``HH:MM:SS AM/PM`` (12 at midnight/noon), e.g. ``08:47:03 PM``."""
    meridiem = "AM" if now.hour < 12 else "PM"
    return f"{_hour12(now):02d}:{now.minute:02d}:{now.second:02d} {meridiem}"


class ClockFrame(Frame):
    name = "clock"

    def render(self, now: datetime, state: dict) -> tuple[str, str]:
        # Logical strings; the renderer fits them to 20 cells with the active
        # per-line alignment (align_top / align_bottom).
        return clock_date(now), clock_time(now)
