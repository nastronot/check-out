# Weather Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `weather` mode — a date/weekday/HH:MM clock on the top line with a colon that is steady, ticks (hardware cursor) or pulses (brightness), and today's high / low / current / rain chance for a lat/lon on the bottom line.

**Architecture:** A background thread in the daemon (`WeatherFetcher`) calls Open-Meteo once per 15-minute data refresh and holds the latest reading. A stateless `WeatherFrame` renders it. A new generic "mode glyph set" mechanism in the daemon replaces spectrum's one-off glyph swap, so any mode can claim glyph slots on entry and give the user's glyphs back on exit. The driver's `show()` learns to leave the cursor on at a chosen cell.

**Tech Stack:** Python 3.14 stdlib (`urllib`, `threading`, `dataclasses`), pytest; Svelte 4 + TypeScript + vitest for the UI.

**Spec:** `docs/superpowers/specs/2026-09-23-weather-mode-design.md`

## Global Constraints

- Only the confirmed-safe command bytes are ever sent; the cursor uses `0x10 <pos> 0x13` (both on the confirmed list).
- The daemon stays the sole owner of the serial port; the web process never opens it.
- No new Python or npm dependencies (HTTP is stdlib `urllib`).
- No test touches the real network.
- Bottom line is always exactly 20 cells.
- Version: `1.4.0` in `checkout/__init__.py` and `ui/package.json`.
- Run Python tests with `.venv/bin/python -m pytest -q`; UI gate is `cd ui && npm run verify`.
- Conventional commits, one per task, ending with the `Co-Authored-By` trailer.

## Review Focus

1. **Location changed while a fetch is in flight** — the reply for the old place must be dropped, not shown under the new place. Test in Task 5.
2. **Network hangs or is down** — the display loop must never wait on it; the clock keeps ticking and the fields show ` --` after an hour. Tests in Tasks 4 and 5 (fetch runs off-thread; stale reading renders ` --`).
3. **Weather → spectrum → clock round trip** — each switch loads the right glyph set and the user's glyphs come back in clock. Test in Task 8.
4. **Blank while in weather** — no cursor block may appear on a dark screen. Test in Task 9.
5. **Lat/lon arriving as strings, blanks or junk from the UI** — coerced to a number or `null`, never crashing the daemon. Test in Task 6.

---

### Task 1: Shared glyph bitmaps

**Files:**
- Create: `checkout/glyphs.py`
- Modify: `checkout/spectrum.py:255-268` (remove the local `LABEL_*` / `label_glyph`, import them)
- Test: `tests/test_glyphs.py`

**Interfaces:**
- Produces: `LABEL_L, LABEL_R, LABEL_H, LABEL_C, DEGREE: list[int]`; `label_glyph(letter: str) -> list[int]` (letters `L R H C`).

- [ ] **Step 1: Write the failing test** — `tests/test_glyphs.py`

```python
"""The shared hand-drawn label/icon bitmaps."""

from checkout import glyphs, spectrum


def _draw(rows):
    return ["".join("#" if r >> c & 1 else "." for c in range(5)) for r in rows]


def test_l_and_r_are_unchanged_by_the_move():
    assert glyphs.LABEL_L == [31, 29, 29, 29, 29, 17, 31]
    assert glyphs.LABEL_R == [31, 17, 21, 25, 21, 21, 31]
    # spectrum re-exports the same objects' values
    assert spectrum.LABEL_L == glyphs.LABEL_L
    assert spectrum.label_glyph("R") == glyphs.LABEL_R


def test_h_is_an_inverted_h():
    assert _draw(glyphs.LABEL_H) == [
        "#####", "#.#.#", "#.#.#", "#...#", "#.#.#", "#.#.#", "#####",
    ]


def test_c_is_an_inverted_c():
    assert _draw(glyphs.LABEL_C) == [
        "#####", "#...#", "#.#.#", "#.###", "#.#.#", "#...#", "#####",
    ]


def test_degree_is_a_small_ring_at_the_top():
    assert _draw(glyphs.DEGREE) == [
        "..#..", ".#.#.", "..#..", ".....", ".....", ".....", ".....",
    ]


def test_label_glyph_returns_a_copy():
    g = glyphs.label_glyph("H")
    g[0] = 0
    assert glyphs.LABEL_H[0] == 31
```

- [ ] **Step 2: Run it to see it fail**

Run: `.venv/bin/python -m pytest tests/test_glyphs.py -q`
Expected: FAIL, `ImportError: cannot import name 'glyphs'`.

- [ ] **Step 3: Implement** — `checkout/glyphs.py`

```python
"""Hand-drawn 5x7 label and icon bitmaps shared by every mode.

Rows are editor-natural: 7 ints, top row first, LOW 5 bits = columns 1..5
(bit0 = column 1); the driver translates them to the wire format. One home for
them means a mode that needs a label imports it instead of redrawing it, and the
preview mirrors whatever the daemon reports as loaded.

The labels are INVERTED (a lit frame with the letter cut out dark) so a label
cell reads as a tag, not as text.
"""

from __future__ import annotations

LABEL_L = [31, 29, 29, 29, 29, 17, 31]
LABEL_R = [31, 17, 21, 25, 21, 21, 31]
LABEL_H = [31, 21, 21, 17, 21, 21, 31]
LABEL_C = [31, 17, 21, 29, 21, 17, 31]

# A 3x3 ring in the top rows, for temperatures.
DEGREE = [4, 10, 4, 0, 0, 0, 0]

_LABELS = {"L": LABEL_L, "R": LABEL_R, "H": LABEL_H, "C": LABEL_C}


def label_glyph(letter: str) -> list[int]:
    """The inverted label glyph for ``letter`` (L, R, H or C), as a fresh list."""
    return list(_LABELS[letter])
```

In `checkout/spectrum.py`, replace the block from `LABEL_L = [...]` through the end of `def label_glyph(...)` with:

```python
from .glyphs import LABEL_L, LABEL_R, label_glyph  # noqa: E402  (shared bitmaps)
```

and keep the comment above it, reworded to say the bitmaps live in `checkout/glyphs.py`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_glyphs.py tests/test_spectrum.py -q`
Expected: all pass.

- [ ] **Step 5: Commit** — `refactor: shared glyphs module (inverted L/R/H/C labels + degree)`

---

### Task 2: Weather clock formatting

**Files:**
- Modify: `checkout/frames/clock.py`
- Test: `tests/test_clock.py`

**Interfaces:**
- Produces: `short_date_time(now: datetime) -> str` → `"MM/DD/YY DAY HH:MM"` (12-hour, no AM/PM).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_clock.py`)

```python
from checkout.frames.clock import short_date_time


def test_short_date_time_matches_mockup():
    assert short_date_time(datetime(2026, 9, 23, 20, 33, 59)) == "09/23/26 WED 08:33"


def test_short_date_time_midnight_and_noon_are_12():
    assert short_date_time(datetime(2026, 9, 27, 0, 5)) == "09/27/26 SUN 12:05"
    assert short_date_time(datetime(2026, 9, 28, 12, 0)) == "09/28/26 MON 12:00"


def test_short_date_time_is_18_chars_and_fits():
    assert len(short_date_time(datetime(2026, 12, 31, 23, 59))) == 18
```

- [ ] **Step 2: Run to fail** — `.venv/bin/python -m pytest tests/test_clock.py -q` → ImportError.

- [ ] **Step 3: Implement** in `checkout/frames/clock.py`

```python
# 3-letter UPPERCASE weekday names, indexed by datetime.weekday() (Mon = 0).
_DAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _hour12(now: datetime) -> int:
    """12-hour clock hour: 12 at midnight and noon, else 1..11."""
    return now.hour % 12 or 12


def short_date_time(now: datetime) -> str:
    """``MM/DD/YY DAY HH:MM`` (12-hour, no AM/PM), e.g. ``09/23/26 WED 08:33``."""
    return (
        f"{now.month:02d}/{now.day:02d}/{now.year % 100:02d} "
        f"{_DAYS[now.weekday()]} {_hour12(now):02d}:{now.minute:02d}"
    )
```

and make `clock_time` use `_hour12(now)` instead of its inline `now.hour % 12 or 12`.

- [ ] **Step 4: Run** — `.venv/bin/python -m pytest tests/test_clock.py -q` → pass.

- [ ] **Step 5: Commit** — `feat: short_date_time clock format for weather`

---

### Task 3: Driver cursor on `show()`

**Files:**
- Modify: `checkout/driver.py` (`show`)
- Test: `tests/test_driver.py`

**Interfaces:**
- Produces: `VFDDriver.show(top: str, bottom: str, cursor: int | None = None) -> None`. With a cursor the write ends `0x10 <cursor> 0x13` instead of `0x14`.

- [ ] **Step 1: Write failing tests** (append to `tests/test_driver.py`)

```python
from checkout.driver import CURSOR_ON


def test_show_with_cursor_ends_by_parking_the_cursor(driver, capsys):
    driver.show("A" * 20, "B" * 20, cursor=15)
    data = capture_bytes(capsys)
    assert data[:44] == [0x10, 0x00] + [ord("A")] * 20 + [0x10, 0x14] + [ord("B")] * 20
    assert data[44:] == [0x10, 15, CURSOR_ON]
    assert CURSOR_OFF not in data[44:]


def test_show_without_cursor_is_unchanged(driver, capsys):
    driver.show("A" * 20, "B" * 20)
    assert capture_bytes(capsys)[-1] == CURSOR_OFF


def test_show_rejects_cursor_out_of_range(driver):
    with pytest.raises(ValueError):
        driver.show("A", "B", cursor=40)
```

- [ ] **Step 2: Run to fail** — `.venv/bin/python -m pytest tests/test_driver.py -q` → TypeError (unexpected keyword).

- [ ] **Step 3: Implement** — replace the tail of `show()`:

```python
    def show(self, top: str, bottom: str, cursor: int | None = None) -> None:
        # (docstring: add) ``cursor`` parks the hardware cursor block on that
        # linear cell (0x00-0x27) instead of hiding it: the write then ends
        # ``0x10 <cursor> 0x13`` (position, cursor on). Weather's colon tick
        # uses it. Without it the write ends in 0x14 exactly as before.
        if cursor is not None and not (POS_TOP <= cursor <= POS_MAX):
            raise ValueError(f"cursor {cursor} out of range 0..{POS_MAX}")
        top_b = _sanitize(_pad(top))
        bottom_b = _sanitize(_pad(bottom))

        buf = bytearray()
        buf += bytes([DISPLAY_POSITION, POS_TOP])
        buf += top_b
        buf += bytes([DISPLAY_POSITION, POS_BOTTOM])
        buf += bottom_b
        if cursor is None:
            buf.append(CURSOR_OFF)  # MUST be last — any later write re-shows cursor
        else:
            buf += bytes([DISPLAY_POSITION, cursor, CURSOR_ON])
        self._write(bytes(buf))
```

- [ ] **Step 4: Run** — driver tests pass.
- [ ] **Step 5: Commit** — `feat: driver show() can park the cursor on a cell`

---

### Task 4: Weather reading, URL and bottom line

**Files:**
- Create: `checkout/weather.py` (first half — pure functions)
- Test: `tests/test_weather.py`

**Interfaces:**
- Consumes: `glyphs.LABEL_H/L/C/R, DEGREE`; `driver.GLYPH_CODES`.
- Produces:
  - `Reading(high, low, current, rain: float | None, observed_at: float, interval_s: int, fetched_at: float)` (frozen dataclass; times are epoch seconds UTC)
  - `COLON_MODES = ("on", "tick", "pulse")`
  - `SLOT_HIGH, SLOT_LOW, SLOT_CURRENT, SLOT_RAIN, SLOT_DEGREE = 0..4`; `WEATHER_GLYPHS: dict[int, list[int]]`
  - `location(state: dict) -> tuple[float, float] | None`
  - `build_url(lat: float, lon: float) -> str`
  - `parse(payload: dict, fetched_at: float) -> Reading` (raises `ValueError`)
  - `next_fetch_at(reading: Reading) -> float`
  - `bottom_line(reading: Reading | None, now: float) -> str` (exactly 20 cells)
  - `STALE_S = 3600`

- [ ] **Step 1: Write failing tests** — `tests/test_weather.py`

```python
"""Weather: reply parsing, URL, schedule and the fixed-width bottom line."""

from datetime import datetime, timezone

import pytest

from checkout import weather
from checkout.driver import GLYPH_CODES

# The reply probed live on 2026-09-23 (Chicago), trimmed to used fields.
PAYLOAD = {
    "utc_offset_seconds": -18000,
    "current": {"time": "2026-09-23T20:45", "interval": 900, "temperature_2m": 82.4},
    "daily": {
        "time": ["2026-09-23"],
        "temperature_2m_max": [92.6],
        "temperature_2m_min": [74.2],
        "precipitation_probability_max": [82],
    },
}
# 20:45 local at UTC-5 is 01:45 UTC the next day.
OBSERVED = datetime(2026, 9, 24, 1, 45, tzinfo=timezone.utc).timestamp()

H, L, C, R, DEG = (chr(GLYPH_CODES[s]) for s in range(5))


def test_parse_reads_the_used_fields():
    r = weather.parse(PAYLOAD, fetched_at=OBSERVED + 30)
    assert (r.high, r.low, r.current, r.rain) == (92.6, 74.2, 82.4, 82.0)
    assert r.observed_at == OBSERVED
    assert r.interval_s == 900
    assert r.fetched_at == OBSERVED + 30


@pytest.mark.parametrize("bad", [{}, {"current": {}}, {**PAYLOAD, "daily": {}}, [] ])
def test_parse_rejects_malformed_replies(bad):
    with pytest.raises(ValueError):
        weather.parse(bad, fetched_at=0)


def test_parse_keeps_null_values_as_none():
    p = {**PAYLOAD, "daily": {**PAYLOAD["daily"], "precipitation_probability_max": [None]}}
    assert weather.parse(p, 0).rain is None


def test_build_url_asks_only_for_the_used_fields():
    url = weather.build_url(41.8781, -87.6298)
    assert url.startswith("https://api.open-meteo.com/v1/forecast?")
    for part in ("latitude=41.8781", "longitude=-87.6298", "current=temperature_2m",
                 "temperature_unit=fahrenheit", "timezone=auto", "forecast_days=1"):
        assert part in url
    assert "precipitation_probability_max" in url


def test_next_fetch_follows_the_data_refresh():
    r = weather.parse(PAYLOAD, fetched_at=OBSERVED + 30)
    assert weather.next_fetch_at(r) == OBSERVED + 900 + 60


def test_next_fetch_is_never_sooner_than_a_minute_after_fetching():
    # The API handed back an old reading: don't hammer it.
    r = weather.parse(PAYLOAD, fetched_at=OBSERVED + 5000)
    assert weather.next_fetch_at(r) == OBSERVED + 5000 + 60


def test_bottom_line_matches_the_mockup():
    r = weather.parse(PAYLOAD, fetched_at=OBSERVED)
    line = weather.bottom_line(r, now=OBSERVED + 60)
    assert line == f"{H} 93{DEG}{L} 74{DEG}{C} 82{DEG}{R} 82%"
    assert len(line) == 20


@pytest.mark.parametrize("value,text", [(100, "100"), (-10, "-10"), (-4.6, " -5"),
                                        (0.4, "  0"), (1000, " --"), (None, " --")])
def test_bottom_line_fields_stay_three_wide(value, text):
    r = weather.Reading(high=value, low=value, current=value, rain=value,
                        observed_at=OBSERVED, interval_s=900, fetched_at=OBSERVED)
    line = weather.bottom_line(r, now=OBSERVED)
    assert len(line) == 20
    assert line[1:4] == text


def test_bottom_line_without_a_reading_shows_dashes():
    assert weather.bottom_line(None, now=0) == f"{H} --{DEG}{L} --{DEG}{C} --{DEG}{R} --%"


def test_bottom_line_goes_to_dashes_after_an_hour():
    r = weather.parse(PAYLOAD, fetched_at=OBSERVED)
    assert " --" not in weather.bottom_line(r, now=OBSERVED + weather.STALE_S - 1)
    assert weather.bottom_line(r, now=OBSERVED + weather.STALE_S) == weather.bottom_line(None, 0)


@pytest.mark.parametrize("state,expected", [
    ({"weather_lat": 41.8, "weather_lon": -87.6}, (41.8, -87.6)),
    ({"weather_lat": "41.8", "weather_lon": "-87.6"}, (41.8, -87.6)),
    ({"weather_lat": None, "weather_lon": -87.6}, None),
    ({}, None),
    ({"weather_lat": "north", "weather_lon": 1}, None),
])
def test_location_from_state(state, expected):
    assert weather.location(state) == expected


def test_weather_glyph_set_uses_the_shared_bitmaps():
    from checkout import glyphs
    assert weather.WEATHER_GLYPHS == {
        weather.SLOT_HIGH: glyphs.LABEL_H, weather.SLOT_LOW: glyphs.LABEL_L,
        weather.SLOT_CURRENT: glyphs.LABEL_C, weather.SLOT_RAIN: glyphs.LABEL_R,
        weather.SLOT_DEGREE: glyphs.DEGREE,
    }
```

- [ ] **Step 2: Run to fail** — ImportError.

- [ ] **Step 3: Implement** — `checkout/weather.py`

```python
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
```

- [ ] **Step 4: Run** — `.venv/bin/python -m pytest tests/test_weather.py -q` → pass.
- [ ] **Step 5: Commit** — `feat: weather reading, request URL and bottom-line layout`

---

### Task 5: `WeatherFetcher` background thread

**Files:**
- Modify: `checkout/weather.py` (append)
- Test: `tests/test_weather.py` (append)

**Interfaces:**
- Consumes: Task 4's `build_url`, `parse`, `next_fetch_at`, `Reading`.
- Produces: `WeatherFetcher(get_json=..., clock=time.time, log=None, autostart=True)` with
  - `set_location(loc: tuple[float, float] | None) -> None` — cheap, called every weather tick; `None` = idle
  - `latest() -> Reading | None`
  - `due_in(now: float) -> float | None` — seconds until the next fetch, `None` when idle
  - `fetch_once() -> None` — one synchronous fetch (the thread's work; tests call it directly)
  - `status() -> dict | None` — for `status.json`
  - `stop() -> None`
  - Retry constants `RETRY_START_S = 60`, `RETRY_MAX_S = 900`.

- [ ] **Step 1: Write failing tests** (append)

```python
class _Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def _fetcher(replies, t=OBSERVED):
    """A fetcher with no thread whose HTTP returns ``replies`` in order
    (an Exception instance is raised instead of returned)."""
    calls = []

    def get_json(url, timeout):
        calls.append(url)
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    clock = _Clock(t)
    f = weather.WeatherFetcher(get_json=get_json, clock=clock, autostart=False)
    return f, clock, calls


def test_idle_without_a_location():
    f, _, calls = _fetcher([])
    assert f.due_in(OBSERVED) is None
    f.fetch_once()
    assert calls == []


def test_fetches_at_once_for_a_new_location_then_waits_for_the_refresh():
    f, clock, calls = _fetcher([PAYLOAD])
    f.set_location((41.88, -87.63))
    assert f.due_in(clock()) == 0
    f.fetch_once()
    assert len(calls) == 1 and "latitude=41.8800" in calls[0]
    assert f.latest().current == 82.4
    assert f.due_in(clock()) == pytest.approx(900 + 60)


def test_failure_keeps_the_last_reading_and_backs_off():
    f, clock, _ = _fetcher([PAYLOAD, OSError("down"), OSError("down"), ValueError("junk")])
    f.set_location((1.0, 2.0))
    f.fetch_once()
    clock.t = weather.next_fetch_at(f.latest())
    f.fetch_once()
    assert f.latest().current == 82.4            # kept
    assert "down" in f.status()["error"]
    assert f.due_in(clock()) == weather.RETRY_START_S
    f.fetch_once()
    assert f.due_in(clock()) == 2 * weather.RETRY_START_S
    f.fetch_once()
    assert f.due_in(clock()) == 4 * weather.RETRY_START_S


def test_backoff_caps_at_fifteen_minutes():
    f, clock, _ = _fetcher([OSError("x")] * 10)
    f.set_location((1.0, 2.0))
    for _ in range(10):
        f.fetch_once()
    assert f.due_in(clock()) == weather.RETRY_MAX_S


def test_success_clears_the_error_and_backoff():
    f, clock, _ = _fetcher([OSError("x"), PAYLOAD])
    f.set_location((1.0, 2.0))
    f.fetch_once()
    f.fetch_once()
    assert f.status()["error"] is None
    assert f.due_in(clock()) > weather.RETRY_START_S


def test_new_location_drops_the_old_reading():
    f, _, _ = _fetcher([PAYLOAD])
    f.set_location((1.0, 2.0))
    f.fetch_once()
    f.set_location((3.0, 4.0))
    assert f.latest() is None
    assert f.due_in(OBSERVED) == 0


def test_reply_for_a_location_changed_mid_fetch_is_dropped():
    f, clock, _ = _fetcher([])

    def get_json(url, timeout):
        f.set_location((9.0, 9.0))     # the user moved while we were waiting
        return PAYLOAD

    f._get_json = get_json
    f.set_location((1.0, 2.0))
    f.fetch_once()
    assert f.latest() is None


def test_leaving_and_returning_keeps_the_reading():
    f, clock, _ = _fetcher([PAYLOAD])
    f.set_location((1.0, 2.0))
    f.fetch_once()
    f.set_location(None)
    assert f.due_in(clock()) is None
    f.set_location((1.0, 2.0))
    assert f.latest() is not None


def test_status_reports_the_reading_and_times():
    f, _, _ = _fetcher([PAYLOAD])
    assert f.status() is None
    f.set_location((1.0, 2.0))
    f.fetch_once()
    s = f.status()
    assert (s["high"], s["low"], s["current"], s["rain"]) == (92.6, 74.2, 82.4, 82.0)
    assert s["observed_at"].startswith("2026-09-24T01:45")
    assert s["error"] is None


def test_thread_fetches_and_stops():
    import threading

    got = threading.Event()

    def get_json(url, timeout):
        got.set()
        return PAYLOAD

    f = weather.WeatherFetcher(get_json=get_json)
    f.set_location((1.0, 2.0))
    assert got.wait(2)
    f.stop()
```

- [ ] **Step 2: Run to fail** — AttributeError `WeatherFetcher`.

- [ ] **Step 3: Implement** (append to `checkout/weather.py`; add imports `http.client`, `json`, `threading`, `time`, `urllib.request` at the top)

```python
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
                self.fetch_once()
```

- [ ] **Step 4: Run** — `.venv/bin/python -m pytest tests/test_weather.py -q` → pass.
- [ ] **Step 5: Commit** — `feat: WeatherFetcher — fetch once per data refresh, backoff, off-thread`

---

### Task 6: State schema

**Files:**
- Modify: `checkout/state.py` (`defaults`, `_backfill`)
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: `weather.COLON_MODES`.
- Produces: state keys `weather_lat: float | None`, `weather_lon: float | None`, `weather_colon: "on" | "tick" | "pulse"`.

- [ ] **Step 1: Write failing tests** (append)

```python
def test_weather_defaults(state_path):
    s = state.load_state()
    assert s["weather_lat"] is None and s["weather_lon"] is None
    assert s["weather_colon"] == "tick"


@pytest.mark.parametrize("lat,lon,expected", [
    (41.88, -87.63, (41.88, -87.63)),
    ("41.88", "-87.63", (41.88, -87.63)),   # the UI may send strings
    ("", "", (None, None)),                  # a cleared input
    (91, -181, (None, None)),                # out of range
    ("north", True, (None, None)),           # junk; bool is not a number here
    (float("nan"), 0, (None, 0.0)),
])
def test_weather_coords_coerce(state_path, lat, lon, expected):
    import json
    state_path.write_text(json.dumps({"weather_lat": lat, "weather_lon": lon}))
    s = state.load_state()
    assert (s["weather_lat"], s["weather_lon"]) == expected


def test_weather_colon_validates(state_path):
    import json
    state_path.write_text(json.dumps({"weather_colon": "pulse"}))
    assert state.load_state()["weather_colon"] == "pulse"
    state_path.write_text(json.dumps({"weather_colon": "wiggle"}))
    assert state.load_state()["weather_colon"] == "tick"
```

(`json.dumps(float("nan"))` writes `NaN`, which Python's `json.load` reads back — that is the case being pinned.)

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: Implement.** In `defaults()` after the spectrum keys:

```python
        # --- weather (mode "weather") ---
        "weather_lat": None,             # decimal degrees, -90..90, or null
        "weather_lon": None,             # decimal degrees, -180..180, or null
        "weather_colon": "tick",         # "on" (steady) | "tick" (cursor) | "pulse"
```

In `_backfill`, before `return merged`:

```python
    # Weather location: a number in range, else null (the UI may send strings or "").
    merged["weather_lat"] = _coord(merged.get("weather_lat"), 90.0)
    merged["weather_lon"] = _coord(merged.get("weather_lon"), 180.0)
    if merged.get("weather_colon") not in COLON_MODES:
        merged["weather_colon"] = "tick"
```

and add:

```python
def _coord(value, limit: float) -> float | None:
    """A coordinate in ``[-limit, limit]`` as a float, else None."""
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and -limit <= v <= limit else None
```

Imports: `import math`; `from .weather import COLON_MODES`. Update the `"mode"` comment in `defaults()` to include `"weather"`.

- [ ] **Step 4: Run** — `tests/test_state.py` passes.
- [ ] **Step 5: Commit** — `feat: weather state keys (lat/lon/colon) with coercion`

---

### Task 7: `WeatherFrame`, the frame cursor hook, and the colon animation

**Files:**
- Modify: `checkout/frames/base.py` (add `cursor`)
- Create: `checkout/frames/weather.py`
- Test: `tests/test_frames.py` (append)

**Interfaces:**
- Consumes: `short_date_time`; `weather.location`, `weather.bottom_line`, `weather.COLON_MODES`; a fetcher with `latest()`.
- Produces:
  - `Frame.cursor(now, state, top, bottom) -> int | None` (default None; `top`/`bottom` are the ALIGNED 20-cell lines)
  - `WeatherFrame(fetcher)`, `name = "weather"`, `NO_LOCATION = "SET LOCATION"`
  - `colon_mode(state) -> str`, `colon_animation(state) -> tuple[str, dict]` (`("pulse", {"period_ms": 1000})` or `("none", {})`)

- [ ] **Step 1: Write failing tests** (append to `tests/test_frames.py`)

```python
from checkout.frames.weather import NO_LOCATION, WeatherFrame, colon_animation
from checkout.renderer import render_lines


class _FakeFetcher:
    def __init__(self, reading=None):
        self.reading = reading

    def latest(self):
        return self.reading


_WX = {"weather_lat": 41.9, "weather_lon": -87.6}
_T = datetime(2026, 9, 23, 20, 33, 12)


def test_weather_top_is_the_short_clock():
    top, _ = WeatherFrame(_FakeFetcher()).render(_T, _WX)
    assert top == "09/23/26 WED 08:33"


def test_weather_without_location_asks_for_one():
    _, bottom = WeatherFrame(_FakeFetcher()).render(_T, {})
    assert bottom == NO_LOCATION


def test_weather_bottom_is_twenty_cells_even_with_no_reading():
    _, bottom = WeatherFrame(_FakeFetcher()).render(_T, _WX)
    assert len(bottom) == 20


def _cursor(state, now, align="center"):
    frame = WeatherFrame(_FakeFetcher())
    top, bottom = render_lines(*frame.render(now, state), top_align=align)
    return frame.cursor(now, state, top, bottom), top


def test_tick_parks_cursor_on_the_colon_in_the_first_half_second():
    state = {**_WX, "weather_colon": "tick"}
    cur, top = _cursor(state, _T.replace(microsecond=100_000))
    assert top[cur] == ":"
    assert _cursor(state, _T.replace(microsecond=600_000))[0] is None


def test_colon_cell_follows_alignment():
    state = {**_WX, "weather_colon": "tick"}
    left, _ = _cursor(state, _T, "left")
    right, _ = _cursor(state, _T, "right")
    assert (left, right) == (15, 17)


def test_on_and_pulse_never_park_the_cursor():
    for colon in ("on", "pulse"):
        assert _cursor({**_WX, "weather_colon": colon}, _T)[0] is None


def test_colon_defaults_to_tick():
    assert _cursor(_WX, _T)[0] is not None


def test_colon_animation():
    assert colon_animation({"weather_colon": "pulse"}) == ("pulse", {"period_ms": 1000})
    assert colon_animation({"weather_colon": "tick"}) == ("none", {})
    assert colon_animation({"weather_colon": "on"}) == ("none", {})
```

(Check the existing imports at the top of `tests/test_frames.py` — `datetime` must be imported.)

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: Implement.** In `checkout/frames/base.py` add to `Frame`:

```python
    def cursor(self, now: datetime, state: dict, top: str, bottom: str) -> int | None:
        """Linear cell (0..39) to park the hardware cursor on this tick, or None.

        ``top``/``bottom`` are the ALIGNED 20-cell lines, so a returned index
        lands on the right cell whatever the justification. Default: no cursor.
        """
        return None
```

`checkout/frames/weather.py`:

```python
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
```

- [ ] **Step 4: Run** — `tests/test_frames.py` passes.
- [ ] **Step 5: Commit** — `feat: WeatherFrame with on/tick/pulse colon`

---

### Task 8: Generic mode glyph sets (spectrum moves onto it)

**Files:**
- Modify: `checkout/daemon.py` (ctx, `_invalidate_caches`, new `mode_glyph_set` + `_sync_glyphs`, spectrum path, `tick_once` section 3)
- Test: `tests/test_daemon.py` (update the spectrum ctx assertions; add round-trip test)

**Interfaces:**
- Consumes: `spectrum.layout_glyphs`, `weather.WEATHER_GLYPHS`.
- Produces: `mode_glyph_set(mode, state) -> tuple[tuple, dict[int, list[int]]] | None`; ctx keys `mode_glyphs_key` (tuple or None) and `mode_glyphs` (dict or None). Removed ctx keys: `spectrum_active`, `spectrum_style`, `spectrum_layout`, `spectrum_glyphs_key`. Removed functions: `_enter_spectrum`, `_define_spectrum_glyphs`.

- [ ] **Step 1: Update/add tests.** In `tests/test_daemon.py`:
  - `assert ctx["spectrum_active"] is True` → `assert ctx["mode_glyphs_key"] == ("spectrum", "full", "bars")`
  - `assert ctx["spectrum_active"] is False` → `assert ctx["mode_glyphs_key"] is None`
  - `assert ctx["spectrum_style"] == "bars"` → `assert ctx["mode_glyphs_key"][2] == "bars"` (and `"line"` likewise)
  - `ctx["spectrum_glyphs_key"] == ("full", "bars")` → `ctx["mode_glyphs_key"] == ("spectrum", "full", "bars")`; same for `("stereo_v", "bars")`.
  - Add:

```python
def test_mode_glyph_sets_round_trip_spectrum_weather_clock(monkeypatch, capsys):
    from checkout import weather
    from checkout.weather import WeatherFetcher

    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    monkeypatch.setattr(daemon.WEATHER_FRAME, "fetcher", WeatherFetcher(autostart=False))
    drv = VFDDriver(dry_run=True)
    ctx = _spectrum_ctx()
    ctx["spectrum_rx"] = _FakeRx([])
    user = {"0": [1, 2, 4, 8, 16, 1, 2]}

    daemon.tick_once(drv, {"mode": "spectrum", "glyphs": user}, ctx, now=NOW)
    assert ctx["mode_glyphs_key"] == ("spectrum", "full", "bars")

    capsys.readouterr()
    daemon.tick_once(drv, {"mode": "weather", "glyphs": user}, ctx,
                     now=datetime(2026, 6, 19, 12, 0, 1))
    defines = _parse_defines(_all_tx_bytes(capsys.readouterr().out))
    assert ctx["mode_glyphs_key"] == ("weather",)
    assert len(defines) == len(weather.WEATHER_GLYPHS)

    capsys.readouterr()
    daemon.tick_once(drv, {"mode": "clock", "glyphs": user}, ctx,
                     now=datetime(2026, 6, 19, 12, 0, 2))
    defines = _parse_defines(_all_tx_bytes(capsys.readouterr().out))
    assert ctx["mode_glyphs_key"] is None
    assert list(defines) == [0x15]                    # the user's slot 0 is back


def test_mode_glyphs_are_redefined_after_a_reset(monkeypatch):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = _CountingDriver()
    ctx = _spectrum_ctx()
    ctx["spectrum_rx"] = _FakeRx([])
    daemon.tick_once(drv, {"mode": "spectrum"}, ctx, now=NOW)
    first = drv.defines
    daemon._invalidate_caches(ctx)                     # what a reset/reconnect does
    daemon.tick_once(drv, {"mode": "spectrum"}, ctx, now=NOW)
    assert drv.defines == 2 * first
```

- [ ] **Step 2: Run** — the updated tests fail (KeyError `mode_glyphs_key`).

- [ ] **Step 3: Implement.**
  - `_new_ctx`: remove `spectrum_active`, `spectrum_style`, `spectrum_layout`, `spectrum_glyphs_key`; add
    ```python
        "mode_glyphs_key": None,   # key of the mode glyph set loaded (None = user glyphs)
        "mode_glyphs": None,       # that set's {slot: rows}, mirrored to status
    ```
  - `_invalidate_caches`: add `ctx["mode_glyphs_key"] = None` (a reset may clear glyph RAM, so the mode set is re-sent too).
  - Delete `_define_spectrum_glyphs` and `_enter_spectrum`. In `_tick_spectrum`, drop the `(layout, style) != ctx.get("spectrum_glyphs_key")` block and call `_ensure_spectrum_rx(ctx)` at its top.
  - Add after `_apply_glyphs`:

```python
# --- mode glyph sets -----------------------------------------------------------
def mode_glyph_set(mode: str, state: dict):
    """The glyph set ``mode`` needs loaded, as ``(key, {slot: rows})``, or None.

    The ONE place a mode claims glyph slots. The key names the exact set, so a
    change of key (mode, or spectrum layout/style) triggers a redefine. A mode
    returning None gets the user's ``state.glyphs``.
    """
    if mode == "spectrum":
        layout, style = _norm_spectrum_layout(state), _norm_spectrum_style(state)
        return ("spectrum", layout, style), spectrum.layout_glyphs(layout, style)
    if mode == "weather":
        return ("weather",), weather.WEATHER_GLYPHS
    return None


def _sync_glyphs(driver: VFDDriver, state: dict, ctx: dict, mode: str) -> None:
    """Load the active mode's glyph set, or the user's glyphs, when it changes.

    Defining characters may reset extended mode / scroll, so every define is
    followed by initialize() + a cache invalidation (settings and the frame are
    then re-sent). Leaving a mode set clears ``last_glyphs`` via the invalidation,
    which makes the user-glyph branch below re-define ``state.glyphs``.
    """
    wanted = mode_glyph_set(mode, state)
    key = wanted[0] if wanted else None
    if key != ctx["mode_glyphs_key"]:
        if wanted:
            log(f"loading glyph set {key} (user glyphs restored on exit)")
            for slot, rows in wanted[1].items():
                driver.define_character(slot, rows)
            driver.initialize()
        _invalidate_caches(ctx)
        ctx["mode_glyphs_key"] = key
        ctx["mode_glyphs"] = dict(wanted[1]) if wanted else None
    if key is None:
        glyphs = state.get("glyphs") or {}
        if glyphs != ctx["last_glyphs"]:
            if glyphs:
                _apply_glyphs(driver, glyphs)
                driver.initialize()
                _invalidate_caches(ctx)
            ctx["last_glyphs"] = dict(glyphs)
```

  - In `tick_once`: delete the "LEAVING spectrum" block and section 3; replace with `_sync_glyphs(driver, state, ctx, mode)`. In the spectrum fast path delete the `_enter_spectrum` call.
  - Import `weather` alongside `spectrum` (`from . import spectrum, weather`).

- [ ] **Step 4: Run** — `.venv/bin/python -m pytest tests/test_daemon.py tests/test_spectrum.py -q` → pass (weather round-trip test passes after Task 9 adds `WEATHER_FRAME`; run it at the end of Task 9 if implementing strictly in order).
- [ ] **Step 5: Commit** — `refactor: generic mode glyph sets (spectrum moves onto them)`

---

### Task 9: Weather in the daemon — fetch, cursor, pulse, status

**Files:**
- Modify: `checkout/daemon.py` (FRAMES, `animation_brightness`, `_apply_emit`, `_write_status`, `tick_once`, `run` shutdown)
- Test: `tests/test_daemon.py` (fake driver `show` gains `cursor=None`; new tests)

**Interfaces:**
- Consumes: `WeatherFrame`, `colon_animation`, `weather.location`, `WeatherFetcher`, `Frame.cursor`, `VFDDriver.show(..., cursor=)`.
- Produces: `daemon.WEATHER_FRAME`; emit tuple `("show", top, bottom)` or `("show", top, bottom, cursor)`; `animation_brightness` honours `params["period_ms"]`; status keys `cursor`, `mode_glyphs`, `weather`.

- [ ] **Step 1: Write failing tests** (append; also change `_CountingDriver.show` to `def show(self, top, bottom, cursor=None):`)

```python
def _weather_setup(monkeypatch, colon="tick"):
    from checkout.weather import WeatherFetcher

    written = []
    monkeypatch.setattr(daemon, "save_status", lambda s: written.append(s))
    fetcher = WeatherFetcher(autostart=False)
    monkeypatch.setattr(daemon.WEATHER_FRAME, "fetcher", fetcher)
    state = {"mode": "weather", "weather_lat": 41.9, "weather_lon": -87.6,
             "weather_colon": colon}
    return written, fetcher, state


def test_weather_tick_toggles_the_cursor_on_the_colon(monkeypatch, capsys):
    written, _, state = _weather_setup(monkeypatch)
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    t = datetime(2026, 9, 23, 20, 33, 12, 100_000)
    daemon.tick_once(drv, state, ctx, now=t)
    capsys.readouterr()
    daemon.tick_once(drv, state, ctx, now=t.replace(microsecond=200_000))
    assert _all_tx_bytes(capsys.readouterr().out) == []      # same frame: no write
    daemon.tick_once(drv, state, ctx, now=t.replace(microsecond=600_000))
    off = _all_tx_bytes(capsys.readouterr().out)
    assert off[-1] == 0x14                                   # cursor hidden
    daemon.tick_once(drv, state, ctx, now=t.replace(second=13, microsecond=0))
    on = _all_tx_bytes(capsys.readouterr().out)
    assert on[-3:] == [0x10, 16, 0x13]                       # centered colon cell
    assert ctx["last_emit"][3] == 16


def test_weather_on_never_writes_a_cursor(monkeypatch, capsys):
    _, _, state = _weather_setup(monkeypatch, colon="on")
    drv = VFDDriver(dry_run=True)
    daemon.tick_once(drv, state, daemon._new_ctx(), now=datetime(2026, 9, 23, 20, 33, 12))
    assert 0x13 not in _all_tx_bytes(capsys.readouterr().out)


def test_weather_blank_has_no_cursor(monkeypatch, capsys):
    _, _, state = _weather_setup(monkeypatch)
    drv = VFDDriver(dry_run=True)
    daemon.tick_once(drv, {**state, "blank": True}, daemon._new_ctx(),
                     now=datetime(2026, 9, 23, 20, 33, 12))
    assert 0x13 not in _all_tx_bytes(capsys.readouterr().out)


def test_weather_pulse_sweeps_brightness_once_a_second(monkeypatch):
    _, _, state = _weather_setup(monkeypatch, colon="pulse")
    levels = []

    class _Drv(_CountingDriver):
        def set_brightness(self, level):
            levels.append(level)

    drv = _Drv()
    ctx = daemon._new_ctx()
    for ms in range(0, 1000, 50):
        daemon.tick_once(drv, state, ctx,
                         now=datetime(2026, 9, 23, 20, 33, 12, ms * 1000))
    assert levels == [0, 1, 2, 3, 2, 1]


def test_weather_ignores_the_global_animation(monkeypatch, capsys):
    _, _, state = _weather_setup(monkeypatch, colon="on")
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    state = {**state, "animation": "flash", "animation_params": {"on_ms": 500, "off_ms": 500}}
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 9, 23, 20, 33, 12, 600_000))
    assert ctx["last_emit"][0] == "show"                    # flash's dark phase ignored


def test_weather_sets_and_clears_the_fetch_location(monkeypatch):
    _, fetcher, state = _weather_setup(monkeypatch)
    drv = _CountingDriver()
    ctx = daemon._new_ctx()
    daemon.tick_once(drv, state, ctx, now=NOW)
    assert fetcher.due_in(0) == 0                            # wants a fetch
    daemon.tick_once(drv, {"mode": "clock"}, ctx, now=NOW)
    assert fetcher.due_in(0) is None                         # idle outside weather


def test_weather_status_reports_cursor_glyphs_and_weather(monkeypatch):
    written, _, state = _weather_setup(monkeypatch)
    drv = _CountingDriver()
    daemon.tick_once(drv, state, daemon._new_ctx(),
                     now=datetime(2026, 9, 23, 20, 33, 12, 100_000))
    s = written[-1]
    assert s["mode"] == "weather"
    assert s["cursor"] == 16
    assert set(s["mode_glyphs"]) == {"0", "1", "2", "3", "4"}
    assert s["weather"]["error"] is None


def test_clock_status_has_no_mode_glyphs_or_cursor(monkeypatch):
    written = []
    monkeypatch.setattr(daemon, "save_status", lambda s: written.append(s))
    daemon.tick_once(_CountingDriver(), {"mode": "clock"}, daemon._new_ctx(), now=NOW)
    assert written[-1]["mode_glyphs"] is None
    assert written[-1]["cursor"] is None
    assert written[-1]["weather"] is None
```

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: Implement.**
  - Imports: `from .frames.weather import WeatherFrame, colon_animation`.
  - Replace the `FRAMES` line:
    ```python
    # Weather's fetcher lives on its frame so tests can swap it for a threadless one.
    WEATHER_FRAME = WeatherFrame(weather.WeatherFetcher(log=lambda m: log(m)))
    FRAMES = {f.name: f for f in (ClockFrame(), MessageFrame(), WEATHER_FRAME)}
    ```
  - `animation_brightness` pulse branch:
    ```python
        if animation == "pulse":
            period = int(params.get("period_ms", 0))
            if period > 0:
                # A fixed period, phase-locked to the wall clock: weather's
                # once-a-second sweep starts dim at the top of each second.
                idx = (now_ms % period) * len(_PULSE_TRIANGLE) // period
            else:
                step_ms = max(1, int(params.get("step_ms", _PULSE_STEP_MS)))
                idx = (now_ms // step_ms) % len(_PULSE_TRIANGLE)
            return _PULSE_TRIANGLE[idx]
    ```
  - `_apply_emit`:
    ```python
    def _apply_emit(driver: VFDDriver, emit: tuple) -> None:
        """("blank",) | ("show", top, bottom) | ("show", top, bottom, cursor)."""
        if emit[0] == "blank":
            driver.blank()
        else:
            driver.show(emit[1], emit[2], cursor=emit[3] if len(emit) > 3 else None)
    ```
  - `_write_status`: add parameter `cursor: int | None = None` and these keys:
    ```python
            # Cell the hardware cursor is parked on (weather's colon tick), else null.
            "cursor": cursor,
            # The glyph set a MODE loaded (weather, spectrum), keyed "0".."8", so the
            # preview draws those cells; null = the user's state.glyphs are loaded.
            "mode_glyphs": ({str(k): v for k, v in ctx["mode_glyphs"].items()}
                            if ctx["mode_glyphs"] else None),
            "weather": (WEATHER_FRAME.fetcher.status()
                        if _norm_mode(state.get("mode")) == "weather" else None),
    ```
  - `tick_once`, right after `mode = _norm_mode(...)`:
    ```python
    # The weather fetcher works only while weather is the active mode.
    WEATHER_FRAME.fetcher.set_location(
        weather.location(state) if mode == "weather" else None)
    ```
  - Animation selection:
    ```python
    if mode in ("marquee", "spectrum"):
        animation, params = "none", state.get("animation_params") or {}
    elif mode == "weather":
        # The colon setting owns the brightness animation here.
        animation, params = colon_animation(state)
    else:
        animation = state.get("animation", "none")
        params = state.get("animation_params") or {}
    ```
  - Normal frame path:
    ```python
            frame = FRAMES.get(mode, FRAMES[DEFAULT_FRAME])
            top, bottom = render_lines(...)            # unchanged
            cursor = frame.cursor(now, state, top, bottom)
        emit = resolve_emit(now_ms, animation, params, top, bottom)
        if cursor is not None and emit[0] == "show":
            emit = (*emit, cursor)
    ```
    (initialise `cursor = None` before the `if state.get("blank")` branch so blank and scroll carry none.)
  - Section 7: `_write_status(state, disp_top, disp_bottom, ctx, now_ms, cursor=emit[3] if len(emit) > 3 else None)`.
  - `run()` `finally`: `WEATHER_FRAME.fetcher.stop()`.

- [ ] **Step 4: Run the whole suite** — `.venv/bin/python -m pytest -q` → all pass.
- [ ] **Step 5: Commit** — `feat: weather mode in the daemon (fetch, colon cursor/pulse, status)`

---

### Task 10: UI — weather controls, preview cursor and mode glyphs

**Files:**
- Modify: `ui/src/lib/types.ts`, `ui/src/App.svelte`, `ui/src/lib/components/ControlPanel.svelte`, `ui/src/lib/components/VfdPreview.svelte`
- Create: `ui/src/lib/cursor.ts`, `ui/src/lib/weather.ts`
- Test: `ui/src/test/cursor.test.ts`, `ui/src/test/weather.test.ts`

**Interfaces:**
- Consumes: status keys `cursor`, `mode_glyphs`, `weather`; state keys `weather_lat`, `weather_lon`, `weather_colon`.
- Produces: `withCursor(top: Cell[], bottom: Cell[], cursor: number | null | undefined): [Cell[], Cell[]]`; `weatherSummary(w: WeatherStatus | null | undefined): string`.

- [ ] **Step 1: Write failing tests**

`ui/src/test/cursor.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { lineToCells } from '../lib/font5x7';
import { withCursor } from '../lib/cursor';

const lit = (cell: boolean[][]) => cell.flat().filter(Boolean).length;

describe('withCursor', () => {
  const top = lineToCells('09/23/26 WED 08:33', {});
  const bottom = lineToCells('', {});

  it('lights the whole cell under the cursor', () => {
    const [t, b] = withCursor(top, bottom, 10);
    expect(lit(t[10])).toBe(35);
    expect(t[9]).toBe(top[9]);
    expect(b).toEqual(bottom);
  });

  it('reaches the bottom line', () => {
    const [, b] = withCursor(top, bottom, 25);
    expect(lit(b[5])).toBe(35);
  });

  it('does nothing without a cursor and never mutates its input', () => {
    expect(withCursor(top, bottom, null)).toEqual([top, bottom]);
    withCursor(top, bottom, 10);
    expect(lit(top[10])).toBeLessThan(35);
  });
});
```

`ui/src/test/weather.test.ts`:

```ts
import { describe, expect, it } from 'vitest';
import { weatherSummary } from '../lib/weather';

const base = {
  high: 92.6, low: 74.2, current: 82.4, rain: 82,
  observed_at: '2026-09-24T01:45:00+00:00',
  fetched_at: '2026-09-24T01:46:00+00:00',
  error: null,
};

describe('weatherSummary', () => {
  it('waits when there is nothing yet', () => {
    expect(weatherSummary(null)).toMatch(/waiting/i);
    expect(weatherSummary({ ...base, observed_at: null, fetched_at: null })).toMatch(/waiting/i);
  });
  it('reports the reading time', () => {
    expect(weatherSummary(base)).toMatch(/^Reading from /);
  });
  it('leads with the error when a fetch failed', () => {
    expect(weatherSummary({ ...base, error: 'OSError: down' })).toMatch(/^Last fetch failed: OSError: down/);
  });
});
```

- [ ] **Step 2: Run to fail** — `cd ui && npx vitest run` → cannot resolve modules.

- [ ] **Step 3: Implement.**

`ui/src/lib/cursor.ts`:

```ts
// The hardware cursor as the preview draws it: a fully lit cell. The daemon
// reports the cell in status.cursor (weather's colon tick); null = hidden.
import { CELL_COLS, CELL_ROWS, LINE_LEN } from './font5x7';
import type { Cell } from './spectrumbars';

const CURSOR_CELL: Cell = Array.from({ length: CELL_ROWS }, () =>
  Array<boolean>(CELL_COLS).fill(true),
);

/** Copies of the two lines with the cell at linear `cursor` (0..39) fully lit. */
export function withCursor(
  top: Cell[],
  bottom: Cell[],
  cursor: number | null | undefined,
): [Cell[], Cell[]] {
  if (cursor == null || cursor < 0 || cursor >= 2 * LINE_LEN) return [top, bottom];
  const lines = [top.slice(), bottom.slice()];
  lines[Math.floor(cursor / LINE_LEN)][cursor % LINE_LEN] = CURSOR_CELL;
  return [lines[0], lines[1]];
}
```

`ui/src/lib/weather.ts`:

```ts
import type { WeatherStatus } from './types';

const time = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

/** One line for the Weather panel: freshness, or what went wrong. */
export function weatherSummary(w: WeatherStatus | null | undefined): string {
  const seen = w?.observed_at ? `showing the ${time(w.observed_at)} reading` : '';
  if (w?.error) return `Last fetch failed: ${w.error}${seen ? ` — ${seen}` : ''}`;
  if (!w?.observed_at) return 'Waiting for the first reading…';
  return `Reading from ${time(w.observed_at)} · refreshes every 15 min`;
}
```

`types.ts`: add `'weather'` to `Mode`; add

```ts
/** Weather colon: steady, cursor tick, or a once-a-second brightness pulse. */
export type WeatherColon = 'on' | 'tick' | 'pulse';

/** status.weather — the latest reading (°F / %) and fetch health. */
export interface WeatherStatus {
  high: number | null;
  low: number | null;
  current: number | null;
  rain: number | null;
  observed_at: string | null;
  fetched_at: string | null;
  error: string | null;
}
```

to `AppState`: `weather_lat: number | null; weather_lon: number | null; weather_colon: WeatherColon;` and to `Status`:

```ts
  /** Cell (0..39) the hardware cursor is parked on, else null. */
  cursor?: number | null;
  /** The glyph set a mode loaded (weather/spectrum); null = state.glyphs. */
  mode_glyphs?: GlyphMap | null;
  /** Weather mode: the latest reading + fetch health; null elsewhere. */
  weather?: WeatherStatus | null;
```

`App.svelte`: glyphs line becomes
```ts
  // Preview glyphs: a mode's own set when one is loaded (weather), else the
  // user's glyphs from the desired state (immediate while editing).
  $: glyphs = $status?.mode_glyphs ?? $appState?.glyphs ?? {};
```
and pass `status={$status}` to `<ControlPanel>`.

`VfdPreview.svelte`: import `withCursor`; add `$: cursor = blank ? null : status?.cursor ?? null;`; pass `cursor` through `redraw(...)` (reactive call and `resize` call) to `drawFrame`, which does
```ts
    const [topCells, bottomCells] = withCursor(
      lineToCells(topLine, glyphMap), lineToCells(bottomLine, glyphMap), cursorCell);
```

`ControlPanel.svelte`:
  - `export let status: Status | null = null;`, import `Status`, `WeatherColon` types and `weatherSummary`.
  - `MODES` gains `'weather'`.
  - Script:
    ```ts
    // weather — location in decimal degrees (south/west negative) + the colon.
    function coord(e: Event): number | null {
      const v = (e.target as HTMLInputElement).value.trim();
      return v === '' ? null : Number(v);
    }
    const setLat = (e: Event) => patch({ weather_lat: coord(e) });
    const setLon = (e: Event) => patch({ weather_lon: coord(e) });
    const COLONS: { value: WeatherColon; label: string }[] = [
      { value: 'on', label: 'ON' },
      { value: 'tick', label: 'TICK' },
      { value: 'pulse', label: 'PULSE' },
    ];
    const setColon = (c: WeatherColon) => patch({ weather_colon: c });
    $: weatherLine = weatherSummary(status?.weather);
    ```
  - Markup after the spectrum block:
    ```svelte
    <!-- WEATHER: date/time top, today's high/low/current/rain bottom. -->
    {#if state.mode === 'weather'}
      <div class="field">
        <span class="field__label">Location</span>
        <div class="row coords">
          <label class="field__hint">lat
            <input type="number" step="0.0001" min="-90" max="90"
              placeholder="41.8781" value={state.weather_lat ?? ''} on:change={setLat} /></label>
          <label class="field__hint">lon
            <input type="number" step="0.0001" min="-180" max="180"
              placeholder="-87.6298" value={state.weather_lon ?? ''} on:change={setLon} /></label>
        </div>
        <span class="field__hint">
          Decimal degrees; south and west are negative. Weather from Open-Meteo,
          fetched once per 15-minute update.
        </span>
      </div>
      <div class="field">
        <span class="field__label">Colon</span>
        <div class="seg">
          {#each COLONS as c}
            <button type="button" aria-pressed={state.weather_colon === c.value}
              on:click={() => setColon(c.value)}>{c.label}</button>
          {/each}
        </div>
        <span class="field__hint">
          <strong>On</strong> = steady. <strong>Tick</strong> = the cursor blinks on
          the colon every second. <strong>Pulse</strong> = the whole display breathes
          once a second (brightness is display-wide on this panel).
        </span>
      </div>
      <p class="tip">{weatherLine}</p>
    {/if}
    ```
  - Hide Animation in weather: `{#if state.mode !== 'marquee' && state.mode !== 'spectrum' && state.mode !== 'weather'}`.
  - Add `.coords { gap: 12px; } .coords input { width: 9ch; }` to the component's `<style>` (use the existing `.timing input` rule as the model).

- [ ] **Step 4: Run** — `cd ui && npm run verify` → svelte-check clean, vitest pass, build OK.
- [ ] **Step 5: Commit** — `feat(ui): weather controls, preview cursor and mode glyphs`

---

### Task 11: Docs, version, live check

**Files:**
- Modify: `CLAUDE.md`, `docs/history.md`, `docs/roadmap.md`, `README.md`, `checkout/__init__.py`, `ui/package.json`

- [ ] **Step 1: Version** — `sed -i 's/__version__ = ".*"/__version__ = "1.4.0"/' checkout/__init__.py`; `sed -i 's/"version": "1.3.1"/"version": "1.4.0"/' ui/package.json`.
- [ ] **Step 2: CLAUDE.md** — add `weather.py`, `glyphs.py`, `frames/weather.py` to the architecture list; a short "Weather mode (v1.4.0)" section (fetcher thread in the daemon, 15-minute cadence, generic mode glyph sets, colon settings); add an unchecked hardware-confirm TODO: "the cursor block shows at a cell that was only positioned (`0x10 pos 0x13`), and how it looks over the colon".
- [ ] **Step 3: history.md / roadmap.md / README.md** — a v1.4.0 entry (what shipped, why a thread not a process, why 15 minutes); README feature bullet for weather.
- [ ] **Step 4: Full verification** — `.venv/bin/python -m pytest -q` and `cd ui && npm run verify`.
- [ ] **Step 5: Live dry-run** — render one weather frame with a real fetch, off the port:

```bash
.venv/bin/python -c "
from datetime import datetime
from checkout import weather
from checkout.frames.weather import WeatherFrame
f = weather.WeatherFetcher(autostart=False)
f.set_location((41.8781, -87.6298)); f.fetch_once()
print(f.status()); print(WeatherFrame(f).render(datetime.now(), {'weather_lat': 41.8781, 'weather_lon': -87.6298}))
"
```
Expected: a status dict with numbers and `error: None`; a 20-cell bottom line.

- [ ] **Step 6: Ship to the running services** — `cd ui && npm run build`; `systemctl --user restart checkout-daemon checkout-web`; confirm both `active` and that `journalctl --user -u checkout-daemon -n 20` shows the loop running.
- [ ] **Step 7: Commit** — `docs: weather mode (v1.4.0)`; push after verification.
