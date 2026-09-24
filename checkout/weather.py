"""Weather mode data: the Open-Meteo call, its reply, and the bottom line.

One HTTP call returns everything the bottom line needs (current temperature,
today's high/low and highest rain chance). Open-Meteo refreshes ``current``
every ``interval`` seconds (900 = 15 min), so the fetcher (below) fetches once
per refresh instead of polling. Nothing here touches the serial port.
"""

from __future__ import annotations

import http.client
import json
import math
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from .driver import GLYPH_CODES
from .glyphs import (COLON_DOT, COLON_THIN, COLON_TWINKLE_BIG, COLON_TWINKLE_SMALL,
                     COLON_TWIST_L, COLON_TWIST_R, DEGREE, GHOST_A, GHOST_B,
                     LABEL_C, LABEL_H, LABEL_L, LABEL_R, PACMAN_CLOSED, PACMAN_OPEN)

API_URL = "https://api.open-meteo.com/v1/forecast"
STALE_S = 3600          # a reading this old shows " --" (never pass old data as current)
FETCH_SLACK_S = 60      # fetch this long after the API's next refresh is due
HTTP_TIMEOUT_S = 10

# weather_colon values: a steady colon, an on/off tick, an animated loop
# (wiggle, twinkle), or pacman (a steady colon with sprites beside the time).
# weather_colon_half doubles every loop's length.
COLON_MODES = ("on", "tick", "wiggle", "twinkle", "pacman")
# weather_pacman: both sprites, or one alone ("solo").
PACMAN_SPRITES = ("both", "ghost", "pacman")
# Names used while v1.4.0 was built -> (final name, half speed); state.py migrates.
LEGACY_COLON_MODES = {
    "pulse": ("wiggle", False),
    "throb": ("wiggle", False),
    "throb2": ("wiggle", True),
    "burst": ("twinkle", False),
    "burst2": ("twinkle", True),
}

# Weather's glyph set (loaded on entry by the daemon's mode-glyph swap). All 9
# slots: 5 labels, the dot + thin colons, and two PEAK frames for the animation
# (wiggle's twists or twinkle's bursts), so switching between the two animations
# redefines just slots 7 and 8.
(SLOT_HIGH, SLOT_LOW, SLOT_CURRENT, SLOT_RAIN, SLOT_DEGREE,
 SLOT_COLON_DOT, SLOT_COLON_THIN, SLOT_COLON_PEAK_A, SLOT_COLON_PEAK_B) = range(9)
# Pacman needs 4 sprite frames, so its set uses slots 5-8 for them instead of
# the colon glyphs (and its time colon is the font's ':').
SLOT_GHOST_A, SLOT_GHOST_B, SLOT_PAC_A, SLOT_PAC_B = range(5, 9)
_LABEL_GLYPHS = {
    SLOT_HIGH: LABEL_H,
    SLOT_LOW: LABEL_L,
    SLOT_CURRENT: LABEL_C,
    SLOT_RAIN: LABEL_R,
    SLOT_DEGREE: DEGREE,
}
_BASE_GLYPHS = {
    **_LABEL_GLYPHS,
    SLOT_COLON_DOT: COLON_DOT,
    SLOT_COLON_THIN: COLON_THIN,   # also the on/tick colon
}
_PACMAN_GLYPHS = {
    **_LABEL_GLYPHS,
    SLOT_GHOST_A: GHOST_A,
    SLOT_GHOST_B: GHOST_B,
    SLOT_PAC_A: PACMAN_CLOSED,
    SLOT_PAC_B: PACMAN_OPEN,
}
_PEAKS = {
    "wiggle": (COLON_TWIST_R, COLON_TWIST_L),
    "twinkle": (COLON_TWINKLE_SMALL, COLON_TWINKLE_BIG),
}


def glyph_set(colon: str) -> tuple[str, dict[int, list[int]]]:
    """``(family, {slot: rows})`` for a weather_colon value. on/tick/wiggle
    share the wiggle set (so switching among them redefines nothing); twinkle
    loads the twinkle peaks; pacman loads the sprites in place of the colons."""
    if colon == "pacman":
        return "pacman", dict(_PACMAN_GLYPHS)
    family = "twinkle" if colon == "twinkle" else "wiggle"
    peak_a, peak_b = _PEAKS[family]
    return family, {**_BASE_GLYPHS, SLOT_COLON_PEAK_A: peak_a, SLOT_COLON_PEAK_B: peak_b}


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
    """A finite float, or None (null, NaN and Infinity — json.load accepts the
    last two — would crash the rounding in _field)."""
    if value is None:
        return None
    v = float(value)
    return v if math.isfinite(v) else None


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


RETRY_START_S = 60      # first retry after a failed fetch
RETRY_MAX_S = 900       # retries double up to this (the data's own refresh)


def _http_get_json(url: str, timeout: float):
    request = urllib.request.Request(url, headers={"User-Agent": "check-out"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _iso(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc).isoformat()


class WeatherFetcher:
    """Fetches weather on a background thread so the display loop never waits.

    The daemon calls :meth:`set_location` every tick (cheap; only a CHANGE wakes
    the thread) with the location while in weather mode and None otherwise, and
    reads :meth:`latest`. The thread sleeps on an Event until the next fetch is
    due — it never polls. A failed fetch keeps the last good reading and retries
    after 60 s, doubling to 15 min. A reply for a location that changed while the
    request was out is dropped.
    """

    def __init__(self, get_json=_http_get_json, clock=time.time, log=None,
                 autostart: bool = True) -> None:
        self._get_json = get_json
        self._clock = clock
        self._log = log or (lambda msg: None)
        self._autostart = autostart
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._loc = None            # wanted now (None = idle)
        self._reading_loc = None    # the location the reading/backoff belong to
        self._reading: Reading | None = None
        self._error: str | None = None
        self._retry_at: float | None = None
        self._backoff = 0.0
        self._thread: threading.Thread | None = None
        self._stopping = False

    def set_location(self, loc) -> None:
        with self._lock:
            if loc == self._loc:
                return
            self._loc = loc
            if loc is not None and loc != self._reading_loc:
                self._reading_loc = loc
                self._reading = None
                self._error = None
                self._retry_at = None
                self._backoff = 0.0
        if loc is not None and self._autostart and self._thread is None:
            self._thread = threading.Thread(
                target=self._run, name="weather-fetch", daemon=True)
            self._thread.start()
        self._wake.set()

    def latest(self) -> Reading | None:
        with self._lock:
            return self._reading

    def due_in(self, now: float) -> float | None:
        with self._lock:
            if self._loc is None:
                return None
            if self._retry_at is not None:
                at = self._retry_at
            elif self._reading is None:
                return 0.0
            else:
                at = next_fetch_at(self._reading)
        return max(0.0, at - now)

    def fetch_once(self) -> None:
        with self._lock:
            loc = self._loc
        if loc is None:
            return
        now = self._clock()
        try:
            reading, error = parse(self._get_json(build_url(*loc), HTTP_TIMEOUT_S), now), None
        except (OSError, ValueError, http.client.HTTPException) as exc:
            reading, error = None, f"{type(exc).__name__}: {exc}"
        with self._lock:
            if loc != self._reading_loc:
                return  # the location changed while the request was out
            if reading is not None:
                self._reading, self._error = reading, None
                self._retry_at, self._backoff = None, 0.0
            else:
                self._error = error
                self._backoff = min(RETRY_MAX_S, max(RETRY_START_S, self._backoff * 2))
                self._retry_at = now + self._backoff
        if error:
            self._log(f"weather fetch failed ({error}); retrying in {self._backoff:.0f}s")

    def status(self) -> dict | None:
        """What status.json reports: the reading, its times and the last error."""
        with self._lock:
            if self._reading_loc is None:
                return None
            r = self._reading
            return {
                "high": r.high if r else None,
                "low": r.low if r else None,
                "current": r.current if r else None,
                "rain": r.rain if r else None,
                "observed_at": _iso(r.observed_at if r else None),
                "fetched_at": _iso(r.fetched_at if r else None),
                "error": self._error,
            }

    def stop(self) -> None:
        self._stopping = True
        self._wake.set()

    def _run(self) -> None:
        while not self._stopping:
            self._wake.clear()  # before reading the schedule, so no wake-up is lost
            wait = self.due_in(self._clock())
            if wait is None:
                self._wake.wait()
            elif wait > 0:
                self._wake.wait(wait)
            else:
                try:
                    self.fetch_once()
                except Exception as exc:  # noqa: BLE001 — keep the thread alive
                    # fetch_once handles network/reply errors itself; anything
                    # else is a bug. Log it and back off instead of letting the
                    # thread die and weather read " --" forever.
                    self._log(f"weather fetcher error: {exc!r}")
                    with self._lock:
                        self._error = repr(exc)
                        self._backoff = min(RETRY_MAX_S, max(RETRY_START_S, self._backoff * 2))
                        self._retry_at = self._clock() + self._backoff
