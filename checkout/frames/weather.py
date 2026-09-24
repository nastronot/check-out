"""WeatherFrame — ``MM/DD/YY DAY HH:MM`` on top, today's weather on the bottom.

The fetch happens elsewhere (``checkout.weather.WeatherFetcher``, a background
thread); this frame only reads the latest reading, so rendering never waits on
the network. The colon stands in for the hidden seconds, per ``weather_colon``:
steady (``on``), the hardware cursor on the colon for the first half of each
second (``tick``), or a once-a-second brightness sweep (``pulse``).
"""

from __future__ import annotations

from datetime import datetime

from .. import weather
from .base import Frame
from .clock import short_date_time

NO_LOCATION = "SET LOCATION"
_TICK_ON_US = 500_000   # tick: cursor on for the first half of each second


def colon_mode(state: dict) -> str:
    """The colon behaviour, coerced to one of ``weather.COLON_MODES``."""
    mode = state.get("weather_colon")
    return mode if mode in weather.COLON_MODES else "tick"


def colon_animation(state: dict) -> tuple[str, dict]:
    """The brightness animation weather mode runs: a 1-second pulse, or none."""
    if colon_mode(state) == "pulse":
        return "pulse", {"period_ms": 1000}
    return "none", {}


class WeatherFrame(Frame):
    name = "weather"

    def __init__(self, fetcher) -> None:
        self.fetcher = fetcher

    def render(self, now: datetime, state: dict) -> tuple[str, str]:
        top = short_date_time(now)
        if weather.location(state) is None:
            return top, NO_LOCATION
        return top, weather.bottom_line(self.fetcher.latest(), now.timestamp())

    def cursor(self, now: datetime, state: dict, top: str, bottom: str) -> int | None:
        if colon_mode(state) != "tick" or now.microsecond >= _TICK_ON_US:
            return None
        colon = top.find(":")
        return colon if colon >= 0 else None
