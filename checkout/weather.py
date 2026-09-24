"""Weather mode data: the Open-Meteo call, its reply, and the bottom line.

One HTTP call returns everything the bottom line needs (current temperature,
today's high/low and highest rain chance). Open-Meteo refreshes ``current``
every ``interval`` seconds (900 = 15 min), so the fetcher (below) fetches once
per refresh instead of polling. Nothing here touches the serial port.
"""

from __future__ import annotations

import math
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone

from .driver import GLYPH_CODES
from .glyphs import DEGREE, LABEL_C, LABEL_H, LABEL_L, LABEL_R

API_URL = "https://api.open-meteo.com/v1/forecast"
STALE_S = 3600          # a reading this old shows " --" (never pass old data as current)
FETCH_SLACK_S = 60      # fetch this long after the API's next refresh is due
HTTP_TIMEOUT_S = 10

# weather_colon values: steady colon, cursor tick, or brightness pulse.
COLON_MODES = ("on", "tick", "pulse")

# Weather's glyph set (loaded on entry by the daemon's mode-glyph swap).
SLOT_HIGH, SLOT_LOW, SLOT_CURRENT, SLOT_RAIN, SLOT_DEGREE = range(5)
WEATHER_GLYPHS = {
    SLOT_HIGH: LABEL_H,
    SLOT_LOW: LABEL_L,
    SLOT_CURRENT: LABEL_C,
    SLOT_RAIN: LABEL_R,
    SLOT_DEGREE: DEGREE,
}
_DEG = chr(GLYPH_CODES[SLOT_DEGREE])
_DASHES = " --"


@dataclass(frozen=True)
class Reading:
    """One reply. Temperatures are °F, rain is %; times are epoch seconds (UTC)."""

    high: float | None
    low: float | None
    current: float | None
    rain: float | None
    observed_at: float   # when Open-Meteo took the current reading
    interval_s: int      # how often Open-Meteo refreshes it
    fetched_at: float    # when we received it


def location(state: dict) -> tuple[float, float] | None:
    """``(lat, lon)`` from state, or None when either is unset or not a number."""
    try:
        lat, lon = state.get("weather_lat"), state.get("weather_lon")
        if lat is None or lon is None:
            return None
        return float(lat), float(lon)
    except (TypeError, ValueError):
        return None


def build_url(lat: float, lon: float) -> str:
    """The single Open-Meteo request, asking only for the fields we show."""
    query = urllib.parse.urlencode({
        "latitude": f"{lat:.4f}",
        "longitude": f"{lon:.4f}",
        "current": "temperature_2m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "temperature_unit": "fahrenheit",
        "timezone": "auto",
        "forecast_days": 1,
    }, safe=",")
    return f"{API_URL}?{query}"


def _num(value) -> float | None:
    return None if value is None else float(value)


def parse(payload: dict, fetched_at: float) -> Reading:
    """Turn a reply into a Reading; raise ValueError if it is malformed.

    ``current.time`` is local to the location (``timezone=auto``), so the reply's
    ``utc_offset_seconds`` converts it to an absolute instant.
    """
    try:
        cur, daily = payload["current"], payload["daily"]
        local = datetime.fromisoformat(cur["time"]).replace(tzinfo=timezone.utc)
        return Reading(
            high=_num(daily["temperature_2m_max"][0]),
            low=_num(daily["temperature_2m_min"][0]),
            current=_num(cur["temperature_2m"]),
            rain=_num(daily["precipitation_probability_max"][0]),
            observed_at=local.timestamp() - int(payload.get("utc_offset_seconds", 0)),
            interval_s=int(cur.get("interval", 900)),
            fetched_at=fetched_at,
        )
    except (KeyError, IndexError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"malformed weather reply: {exc!r}") from None


def next_fetch_at(reading: Reading) -> float:
    """When the next fetch is worth making: just after Open-Meteo's next refresh,
    and never sooner than a minute after the last fetch (if it served old data)."""
    return max(
        reading.observed_at + reading.interval_s + FETCH_SLACK_S,
        reading.fetched_at + FETCH_SLACK_S,
    )


def _field(slot: int, value: float | None, suffix: str) -> str:
    """One 5-cell field: label glyph + 3-wide right-aligned number + suffix."""
    text = _DASHES
    if value is not None:
        rounded = str(math.floor(value + 0.5))
        if len(rounded) <= 3:
            text = rounded.rjust(3)
    return chr(GLYPH_CODES[slot]) + text + suffix


def bottom_line(reading: Reading | None, now: float) -> str:
    """``[H] 93°[L] 74°[C] 82°[R] 82%`` — always exactly 20 cells.

    A missing, unfittable or stale (≥ STALE_S old) value shows `` --``.
    """
    if reading is not None and now - reading.observed_at >= STALE_S:
        reading = None
    get = (lambda name: getattr(reading, name)) if reading else (lambda name: None)
    return (
        _field(SLOT_HIGH, get("high"), _DEG)
        + _field(SLOT_LOW, get("low"), _DEG)
        + _field(SLOT_CURRENT, get("current"), _DEG)
        + _field(SLOT_RAIN, get("rain"), "%")
    )
