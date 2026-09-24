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
- ``throb`` — a 13-frame animation once a second: blank, dots, thin, twist,
  thin, dots, blank, dots, thin, mirrored twist, thin, dots, blank.

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
_TWIST_R = chr(GLYPH_CODES[weather.SLOT_COLON_TWIST_R])
_TWIST_L = chr(GLYPH_CODES[weather.SLOT_COLON_TWIST_L])

# throb: these 13 frames, evenly spaced across each second (~77 ms apiece).
_THROB_STEPS = (
    _BLANK, _DOT, _THIN, _TWIST_R, _THIN, _DOT,
    _BLANK, _DOT, _THIN, _TWIST_L, _THIN, _DOT, _BLANK,
)


def colon_mode(state: dict) -> str:
    """The colon behaviour, coerced to one of ``weather.COLON_MODES``."""
    mode = state.get("weather_colon")
    return mode if mode in weather.COLON_MODES else "tick"


def colon_char(state: dict, now: datetime) -> str:
    """The character in the colon's cell at ``now``."""
    mode = colon_mode(state)
    if mode == "tick":
        return _THIN if now.microsecond < _US_PER_S // 2 else _BLANK
    if mode == "throb":
        return _THROB_STEPS[now.microsecond * len(_THROB_STEPS) // _US_PER_S]
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
