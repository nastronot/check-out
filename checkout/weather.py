"""Weather mode data: the Open-Meteo call, its reply, and the bottom line.

One HTTP call returns everything the bottom line needs: the current
temperature, plus hourly temperatures and rain amounts from which the high, the
low and the rain TOTAL (inches) are taken — a ROLLING 24 hours from now, not the
calendar day (so late at night it is about tomorrow, not the day that is ending). Open-Meteo refreshes ``current``
every ``interval`` seconds (900 = 15 min), so the fetcher (below) fetches once
per refresh instead of polling. Nothing here touches the serial port.
"""

from __future__ import annotations

import json
import math
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from .driver import GLYPH_CODES
from .glyphs import (AM, DEGREE, GHOST_A, GHOST_B, GHOST_C, HEART_EMPTY, HEART_FULL,
                     LABEL_C, LABEL_H, LABEL_L, LABEL_R, PACMAN_CLOSED, PACMAN_OPEN,
                     PM, TWINKLE_CORNERS, TWINKLE_DIAMOND, TWINKLE_DOT, mirror)

API_URL = "https://api.open-meteo.com/v1/forecast"
STALE_S = 3600          # a reading this old shows " --" (never pass old data as current)
FETCH_SLACK_S = 60      # fetch this long after the API's next refresh is due
HTTP_TIMEOUT_S = 10

# dynamic_colon values: a steady colon, an on/off tick, an animated loop
# (twinkle), or pacman (a steady colon with sprites beside the time).
# dynamic_colon_half doubles every loop's length.
COLON_MODES = ("on", "tick", "twinkle", "pacman")
# dynamic_pacman_sprite: which sprite shows alone when solo (remembered while
# solo is off, since the widest date/time forces solo — frames/dynamic.py).
PACMAN_SPRITES = ("ghost", "heart", "pacman")
# Names used while v1.4.0 was built -> (final name, half speed); state.py migrates.
LEGACY_COLON_MODES = {
    "wiggle": ("twinkle", False),   # wiggle was removed; twinkle is the animation left
    "pulse": ("twinkle", False),
    "throb": ("twinkle", False),
    "throb2": ("twinkle", True),
    "burst": ("twinkle", False),
    "burst2": ("twinkle", True),
}

# Dynamic's glyph sets (loaded by the daemon's mode-glyph swap): every time
# feature keeps the 5 labels in slots 0-4 and loads its own glyphs above them —
# twinkle: three frames (5-7);
# twinkle also the AM/PM marker (8); on/tick: the marker only (8); pacman:
# sprite frames (5-8).
SLOT_HIGH, SLOT_LOW, SLOT_CURRENT, SLOT_RAIN, SLOT_DEGREE = range(5)
# Pacman needs up to 4 sprite frames, so its set uses slots 5-8 for them instead
# of the colon glyphs (and its time colon is the font's ':'). Slots 5/6 hold the
# chosen sprite's two frames, 7/8 hold pacman (duo only); WHICH bitmaps sit in
# 5/6 depends on the cast (see glyph_set), so the frame code never changes.
SLOT_SPRITE_A, SLOT_SPRITE_B, SLOT_PAC_A, SLOT_PAC_B = range(5, 9)
# on/tick/twinkle end the top line with an AM/PM marker. ONE slot holds it: the
# set loads AM or PM there (the key names which), so it reloads at noon and
# midnight and never needs two slots.
SLOT_MERIDIEM = 8
MERIDIEM_FEATURES = ("on", "tick", "twinkle")
_MARKERS = {"am": AM, "pm": PM}
# twinkle is its own set too: the labels plus its three frames.
SLOT_TWINKLE_1, SLOT_TWINKLE_2, SLOT_TWINKLE_3 = 5, 6, 7
_LABEL_GLYPHS = {
    SLOT_HIGH: LABEL_H,
    SLOT_LOW: LABEL_L,
    SLOT_CURRENT: LABEL_C,
    SLOT_RAIN: LABEL_R,
    SLOT_DEGREE: DEGREE,
}
_PAC_FRAMES = {SLOT_PAC_A: PACMAN_CLOSED, SLOT_PAC_B: PACMAN_OPEN}
# The chosen sprite's two frames. Duo (being eaten): the ghost glances right, the
# heart beats, and a pacman faces its mirror (drawn on the opposite frame by the
# frame code). Solo: the ghost glances left instead.
_DUO_SPRITE_FRAMES = {
    "ghost": (GHOST_A, GHOST_B),
    "heart": (HEART_FULL, HEART_EMPTY),
    "pacman": (mirror(PACMAN_CLOSED), mirror(PACMAN_OPEN)),
}
_SOLO_SPRITE_FRAMES = {
    "ghost": (GHOST_B, GHOST_C),
    "heart": (HEART_FULL, HEART_EMPTY),
    "pacman": (PACMAN_CLOSED, PACMAN_OPEN),
}


def glyph_set(colon: str, cast: str = "duo-ghost",
              meridiem: str = "am") -> tuple[str, dict[int, list[int]]]:
    """``(family, {slot: rows})`` for a dynamic_colon value — and, for pacman,
    the CAST from ``pacman_cast``: "duo-<sprite>" (pacman eating the sprite) or
    "<sprite>" (solo). on/tick load the AM/PM marker; twinkle its frames + the marker; each pacman cast
    loads its own sprite frames, and the family names it."""
    marker = {SLOT_MERIDIEM: _MARKERS.get(meridiem, AM)}
    if colon in ("on", "tick"):
        return f"clock-{meridiem}", {**_LABEL_GLYPHS, **marker}
    if colon == "twinkle":
        return f"twinkle-{meridiem}", {
            **_LABEL_GLYPHS, SLOT_TWINKLE_1: TWINKLE_DOT, SLOT_TWINKLE_2: TWINKLE_DIAMOND,
            SLOT_TWINKLE_3: TWINKLE_CORNERS, **marker}
    if colon == "pacman":
        solo = not cast.startswith("duo-")
        sprite = cast.removeprefix("duo-")
        if sprite not in PACMAN_SPRITES:
            sprite, solo = "ghost", False
        frame_a, frame_b = (_SOLO_SPRITE_FRAMES if solo else _DUO_SPRITE_FRAMES)[sprite]
        glyphs = {**_LABEL_GLYPHS, SLOT_SPRITE_A: frame_a, SLOT_SPRITE_B: frame_b}
        if not solo:
            glyphs.update(_PAC_FRAMES)
        return f"pacman-{sprite if solo else 'duo-' + sprite}", glyphs
    raise ValueError(f"unknown dynamic colon {colon!r}")


_DEG = chr(GLYPH_CODES[SLOT_DEGREE])
_DASHES = " --"


@dataclass(frozen=True)
class Reading:
    """One reply. Temperatures are °F; rain is the next-24-hour total in inches;
    times are epoch seconds (UTC)."""

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
        # 24 hourly steps starting at the current hour (~1.1 KB reply).
        # 25 hourly steps starting at the current hour; parse() drops the first,
        # whose value covers the hour that already passed (~1.1 KB reply).
        "hourly": "temperature_2m,precipitation",
        "forecast_hours": 25,
        "precipitation_unit": "inch",
        "temperature_unit": "fahrenheit",
        "timezone": "auto",
    }, safe=",")
    return f"{API_URL}?{query}"


def _num(value) -> float | None:
    """A finite float, or None (null, NaN and Infinity — json.load accepts the
    last two — would crash the rounding in _field)."""
    if value is None:
        return None
    v = float(value)
    return v if math.isfinite(v) else None


def _extreme(values, pick) -> float | None:
    """``pick`` (max/min) of the finite values, or None if there are none."""
    finite = [v for v in (_num(x) for x in values) if v is not None]
    return pick(finite) if finite else None


def parse(payload: dict, fetched_at: float) -> Reading:
    """Turn a reply into a Reading; raise ValueError if it is malformed.

    High / low are the max / min of the next 24 hourly temperatures; rain is the
    SUM of the next 24 hourly amounts, in inches. Each hourly precipitation value
    covers the hour BEFORE its timestamp, so the first (stamped with the current
    hour) is dropped. Hours with no value are skipped.

    ``current.time`` is local to the location (``timezone=auto``), so the reply's
    ``utc_offset_seconds`` converts it to an absolute instant.
    """
    try:
        cur, hourly = payload["current"], payload["hourly"]
        temps, rain = hourly["temperature_2m"][1:], hourly["precipitation"][1:]
        if not temps or not rain:
            raise ValueError("no hourly values")
        local = datetime.fromisoformat(cur["time"]).replace(tzinfo=timezone.utc)
        return Reading(
            high=_extreme(temps, max),
            low=_extreme(temps, min),
            current=_num(cur["temperature_2m"]),
            rain=_extreme(rain, sum),
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


def _whole(value: float | None) -> str:
    """A number rounded to a whole, in 3 cells, or `` --`` if it doesn't fit."""
    if value is None:
        return _DASHES
    rounded = str(math.floor(value + 0.5))
    return rounded.rjust(3) if len(rounded) <= 3 else _DASHES


def _inches(value: float | None) -> str:
    """A rain total in 3 cells with the fewest digits that fit: ``.04`` under an
    inch, ``1.2`` under ten, whole inches (`` 42``, ``100``) above; ``  0`` when
    dry; `` --`` only past 999 (the US 24-hour record is ~42")."""
    if value is None:
        return _DASHES
    if value < 0.005:
        return "  0"
    if value < 0.995:
        return f"{value:.2f}"[1:]          # ".04" (drop the leading 0)
    if value < 9.95:
        return f"{value:.1f}"              # "1.2"
    return _whole(value)                    # " 42" / "100"; " --" past 999


def _field(slot: int, text: str, suffix: str) -> str:
    """One 5-cell field: label glyph + a 3-cell value + suffix."""
    return chr(GLYPH_CODES[slot]) + text + suffix


def bottom_line(reading: Reading | None, now: float) -> str:
    """``[H] 93°[L] 74°[C] 82°[R] .40"`` — always exactly 20 cells.

    High / low / current are whole °F; rain is the next-24-hour total in inches.
    A missing, unfittable or stale (≥ STALE_S old) value shows `` --``.
    """
    if reading is not None and now - reading.observed_at >= STALE_S:
        reading = None
    get = (lambda name: getattr(reading, name)) if reading else (lambda name: None)
    return (
        _field(SLOT_HIGH, _whole(get("high")), _DEG)
        + _field(SLOT_LOW, _whole(get("low")), _DEG)
        + _field(SLOT_CURRENT, _whole(get("current")), _DEG)
        + _field(SLOT_RAIN, _inches(get("rain")), '"')
    )


from .poller import Poller

# Retry timing lives on the shared Poller; re-exported for callers and tests.
RETRY_START_S = Poller.RETRY_START_S
RETRY_MAX_S = Poller.RETRY_MAX_S


def _http_get_json(url: str, timeout: float):
    request = urllib.request.Request(url, headers={"User-Agent": "check-out"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _iso(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc).isoformat()


class WeatherFetcher(Poller):
    """Weather on the shared background :class:`~checkout.poller.Poller`.

    The key is the ``(lat, lon)`` location. The daemon sets it every tick (None
    outside dynamic mode) and reads :meth:`latest`. The next fetch follows
    Open-Meteo's own refresh (:func:`next_fetch_at`), not a fixed timer.
    """

    def __init__(self, get_json=_http_get_json, clock=time.time, log=None,
                 autostart: bool = True) -> None:
        super().__init__(clock=clock, log=log, autostart=autostart, name="weather fetch")
        self._get_json = get_json
        self._reading: Reading | None = None

    def set_location(self, loc) -> None:
        self.set_key(loc)

    def latest(self) -> Reading | None:
        with self._lock:
            return self._reading

    # --- Poller hooks ---------------------------------------------------------
    def _fetch(self, key, now):
        return parse(self._get_json(build_url(*key), HTTP_TIMEOUT_S), now)

    def _next_at(self, key, now) -> float:
        return next_fetch_at(self._reading)

    def _accept(self, key, result, now) -> None:
        self._reading = result

    def _has_result(self) -> bool:
        return self._reading is not None

    def _reset(self) -> None:
        self._reading = None

    def status(self) -> dict | None:
        """What status.json reports: the reading, its times and the last error."""
        with self._lock:
            if self._result_key is None:
                return None
            r = self._reading
            return {
                "high": r.high if r else None,
                "low": r.low if r else None,
                "current": r.current if r else None,
                "rain": r.rain if r else None,
                "observed_at": _iso(r.observed_at if r else None),
                "fetched_at": _iso(r.fetched_at if r else None),
                "error": self.error,
            }
