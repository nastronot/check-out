"""WeatherFrame — ``MM/DD/YY DAY HH:MM`` on top, today's weather on the bottom.

The fetch happens elsewhere (``checkout.weather.WeatherFetcher``, a background
thread); this frame only reads the latest reading, so rendering never waits on
the network.

The colon stands in for the hidden seconds, per ``weather_colon``, by changing
the colon CHARACTER — never the hardware cursor (an underline on this glass that
stays on across writes) and never brightness (display-wide, so the whole panel
would change):

- ``on``      — a steady thin colon (one centre column of dots, a weather glyph).
- ``tick``    — the thin colon, then a space: on for half the loop, off for half.
- ``wiggle``  — 12 frames: blank, dot, thin, twist-R, thin, dot, blank, dot, thin,
  twist-L, thin, dot (then blank again) — the twists alternate sides.
- ``twinkle`` — 8 frames straight up and down: blank, dot, thin, small burst,
  big burst, small burst, thin, dot.

Each loop takes 1 second, or 2 with ``weather_colon_half`` (half speed), and is
locked to the wall clock (a 2 s loop starts on even seconds). Wiggle's twists and
twinkle's bursts share the two PEAK glyph slots (``weather.glyph_set``).

Only the colon cell changes, so the daemon's cell-diff writes one cell.
"""

from __future__ import annotations

from datetime import datetime

from .. import weather
from ..driver import GLYPH_CODES
from .base import Frame
from .clock import short_date_time

NO_LOCATION = "SET LOCATION"
_US_PER_S = 1_000_000

_BLANK = " "
_DOT = chr(GLYPH_CODES[weather.SLOT_COLON_DOT])
_THIN = chr(GLYPH_CODES[weather.SLOT_COLON_THIN])
_PEAK_A = chr(GLYPH_CODES[weather.SLOT_COLON_PEAK_A])
_PEAK_B = chr(GLYPH_CODES[weather.SLOT_COLON_PEAK_B])

# The frames of each animated colon, spread evenly across the loop. Each loop
# wraps back to its first frame, so every frame is the same length.
_LOOPS = {
    "tick": (_THIN, _BLANK),
    "wiggle": (_BLANK, _DOT, _THIN, _PEAK_A, _THIN, _DOT,
               _BLANK, _DOT, _THIN, _PEAK_B, _THIN, _DOT),
    "twinkle": (_BLANK, _DOT, _THIN, _PEAK_A, _PEAK_B, _PEAK_A, _THIN, _DOT),
}


def colon_mode(state: dict) -> str:
    """The colon behaviour, coerced to one of ``weather.COLON_MODES``."""
    mode = state.get("weather_colon")
    return mode if mode in weather.COLON_MODES else "tick"


def colon_char(state: dict, now: datetime) -> str:
    """The character in the colon's cell at ``now``."""
    frames = _LOOPS.get(colon_mode(state))
    if frames is None:
        return _THIN  # on
    seconds = 2 if state.get("weather_colon_half") else 1
    # Phase within the loop, locked to the wall clock.
    phase_us = (now.second % seconds) * _US_PER_S + now.microsecond
    return frames[phase_us * len(frames) // (seconds * _US_PER_S)]


class WeatherFrame(Frame):
    name = "weather"

    def __init__(self, fetcher) -> None:
        self.fetcher = fetcher

    def render(self, now: datetime, state: dict) -> tuple[str, str]:
        top = short_date_time(now, colon=colon_char(state, now))
        if weather.location(state) is None:
            return top, NO_LOCATION
        return top, weather.bottom_line(self.fetcher.latest(), now.timestamp())
