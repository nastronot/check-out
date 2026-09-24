"""WeatherFrame — ``MM/DD/YY DAY HH:MM`` on top, today's weather on the bottom.

The fetch happens elsewhere (``checkout.weather.WeatherFetcher``, a background
thread); this frame only reads the latest reading, so rendering never waits on
the network.

The colon stands in for the hidden seconds, per ``weather_colon``, by changing
the colon CHARACTER — never the hardware cursor (an underline on this glass that
stays on across writes) and never brightness (display-wide, so the whole panel
would change):

- ``on``    — a steady thin colon (one centre column of dots, a weather glyph).
- ``tick``  — the thin colon for the first half of each second, a space for the
  second.
- ``throb`` / ``burst`` — a 12-frame loop once a second: blank, dots, thin,
  peak A, thin, dots, blank, dots, thin, peak B, thin, dots (then blank again).
  The two share the order; weather's glyph set puts throb's twists or burst's
  bursts in the peak slots (``weather.glyph_set``).
- ``throb2`` / ``burst2`` — the same loops at half speed (2 seconds).

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

# throb/burst: these 12 frames, evenly spaced across the loop (~83 ms apiece at
# full speed). The loop wraps from the last dot back to the first blank, so there
# is one blank between loops and every frame is the same length.
_LOOP_STEPS = (
    _BLANK, _DOT, _THIN, _PEAK_A, _THIN, _DOT,
    _BLANK, _DOT, _THIN, _PEAK_B, _THIN, _DOT,
)
# Loop length in seconds per animated colon mode.
_LOOP_SECONDS = {"throb": 1, "burst": 1, "throb2": 2, "burst2": 2}


def colon_mode(state: dict) -> str:
    """The colon behaviour, coerced to one of ``weather.COLON_MODES``."""
    mode = state.get("weather_colon")
    return mode if mode in weather.COLON_MODES else "tick"


def colon_char(state: dict, now: datetime) -> str:
    """The character in the colon's cell at ``now``."""
    mode = colon_mode(state)
    if mode == "tick":
        return _THIN if now.microsecond < _US_PER_S // 2 else _BLANK
    if mode in _LOOP_SECONDS:
        # Phase within the loop, locked to the wall clock (a 2 s loop starts on
        # even seconds).
        seconds = _LOOP_SECONDS[mode]
        phase_us = (now.second % seconds) * _US_PER_S + now.microsecond
        return _LOOP_STEPS[phase_us * len(_LOOP_STEPS) // (seconds * _US_PER_S)]
    return _THIN


class WeatherFrame(Frame):
    name = "weather"

    def __init__(self, fetcher) -> None:
        self.fetcher = fetcher

    def render(self, now: datetime, state: dict) -> tuple[str, str]:
        top = short_date_time(now, colon=colon_char(state, now))
        if weather.location(state) is None:
            return top, NO_LOCATION
        return top, weather.bottom_line(self.fetcher.latest(), now.timestamp())
