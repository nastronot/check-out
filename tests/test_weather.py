"""Weather: reply parsing, URL, schedule and the fixed-width bottom line."""

from datetime import datetime, timezone

import pytest

from checkout import weather
from checkout.driver import GLYPH_CODES

# The reply shape probed live on 2026-09-23 (Chicago): current + 25 hourly values
# starting at the current hour. The FIRST is dropped (its value covers the hour
# that already passed), leaving exactly the next 24. Values chosen for the test.
_PAST = 999.0   # the dropped first hour: must never show up in a result
_TEMPS = [_PAST, 82.0, 85.5, 92.6, 90.1] + [80.0] * 19 + [74.2]
_RAIN = [_PAST, 0.0, 0.1, 0.25, 0.05] + [0.0] * 20      # inches per hour -> 0.40 total
PAYLOAD = {
    "utc_offset_seconds": -18000,
    "current": {"time": "2026-09-23T20:45", "interval": 900, "temperature_2m": 82.4},
    "hourly": {
        "time": [f"2026-09-2{3 + (20 + h) // 24}T{(20 + h) % 24:02d}:00" for h in range(25)],
        "temperature_2m": _TEMPS,
        "precipitation": _RAIN,
    },
}
# 20:45 local at UTC-5 is 01:45 UTC the next day.
OBSERVED = datetime(2026, 9, 24, 1, 45, tzinfo=timezone.utc).timestamp()

H, L, C, R, DEG = (chr(GLYPH_CODES[s]) for s in range(5))


def test_parse_takes_the_next_24_hours_and_drops_the_past_one():
    r = weather.parse(PAYLOAD, fetched_at=OBSERVED + 30)
    assert (r.high, r.low, r.current) == (92.6, 74.2, 82.4)
    assert r.rain == pytest.approx(0.40)          # total inches, not a max
    assert r.observed_at == OBSERVED
    assert r.interval_s == 900
    assert r.fetched_at == OBSERVED + 30


@pytest.mark.parametrize("bad", [{}, {"current": {}}, {**PAYLOAD, "hourly": {}}, [] ])
def test_parse_rejects_malformed_replies(bad):
    with pytest.raises(ValueError):
        weather.parse(bad, fetched_at=0)


def test_parse_skips_null_hours_and_is_none_when_all_are_null():
    some = {**PAYLOAD, "hourly": {**PAYLOAD["hourly"],
                                  "precipitation": [None, 0.3] + [None] * 23}}
    assert weather.parse(some, 0).rain == pytest.approx(0.3)
    none = {**PAYLOAD, "hourly": {**PAYLOAD["hourly"], "precipitation": [0.5] + [None] * 24}}
    assert weather.parse(none, 0).rain is None


def test_build_url_asks_only_for_the_used_fields():
    url = weather.build_url(41.8781, -87.6298)
    assert url.startswith("https://api.open-meteo.com/v1/forecast?")
    for part in ("latitude=41.8781", "longitude=-87.6298", "current=temperature_2m",
                 "hourly=temperature_2m,precipitation", "forecast_hours=25",
                 "temperature_unit=fahrenheit", "precipitation_unit=inch", "timezone=auto"):
        assert part in url
    assert "daily=" not in url and "forecast_days" not in url


def test_next_fetch_follows_the_data_refresh():
    r = weather.parse(PAYLOAD, fetched_at=OBSERVED + 30)
    assert weather.next_fetch_at(r) == OBSERVED + 900 + 60


def test_next_fetch_is_never_sooner_than_a_minute_after_fetching():
    # The API handed back an old reading: don't hammer it.
    r = weather.parse(PAYLOAD, fetched_at=OBSERVED + 5000)
    assert weather.next_fetch_at(r) == OBSERVED + 5000 + 60


def test_bottom_line_shows_rain_in_inches():
    r = weather.parse(PAYLOAD, fetched_at=OBSERVED)
    line = weather.bottom_line(r, now=OBSERVED + 60)
    assert line == f'{H} 93{DEG}{L} 74{DEG}{C} 82{DEG}{R}.40"'
    assert len(line) == 20


@pytest.mark.parametrize("value,text", [(100, "100"), (-10, "-10"), (-4.6, " -5"),
                                        (0.4, "  0"), (1000, " --"), (None, " --")])
def test_temperature_fields_stay_three_wide(value, text):
    r = weather.Reading(high=value, low=value, current=value, rain=0.0,
                        observed_at=OBSERVED, interval_s=900, fetched_at=OBSERVED)
    line = weather.bottom_line(r, now=OBSERVED)
    assert len(line) == 20
    assert line[1:4] == text


@pytest.mark.parametrize("inches,text", [
    (0.0, "  0"), (0.004, "  0"), (0.04, ".04"), (0.75, ".75"), (0.996, "1.0"),
    (1.24, "1.2"), (9.94, "9.9"), (9.96, " 10"), (42.0, " 42"), (99.6, "100"),
    (999.6, " --"), (None, " --"),
])
def test_rain_field_uses_the_fewest_digits_that_fit(inches, text):
    r = weather.Reading(high=70, low=60, current=65, rain=inches,
                        observed_at=OBSERVED, interval_s=900, fetched_at=OBSERVED)
    line = weather.bottom_line(r, now=OBSERVED)
    assert len(line) == 20
    assert line[16:] == text + '"'


def test_bottom_line_without_a_reading_shows_dashes():
    assert weather.bottom_line(None, now=0) == f'{H} --{DEG}{L} --{DEG}{C} --{DEG}{R} --"'


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


def test_weather_glyph_sets_swap_only_the_peak_frames():
    from checkout import glyphs
    base = {
        weather.SLOT_HIGH: glyphs.LABEL_H, weather.SLOT_LOW: glyphs.LABEL_L,
        weather.SLOT_CURRENT: glyphs.LABEL_C, weather.SLOT_RAIN: glyphs.LABEL_R,
        weather.SLOT_DEGREE: glyphs.DEGREE,
        weather.SLOT_COLON_DOT: glyphs.COLON_DOT, weather.SLOT_COLON_THIN: glyphs.COLON_THIN,
    }
    wiggle = {**base, weather.SLOT_COLON_PEAK_A: glyphs.COLON_TWIST_R,
              weather.SLOT_COLON_PEAK_B: glyphs.COLON_TWIST_L}
    labels5 = {k: v for k, v in base.items() if k <= weather.SLOT_DEGREE}
    twinkle = {**labels5, weather.SLOT_TWINKLE_1: glyphs.TWINKLE_DOT,
               weather.SLOT_TWINKLE_2: glyphs.TWINKLE_DIAMOND,
               weather.SLOT_TWINKLE_3: glyphs.TWINKLE_CORNERS}
    assert weather.glyph_set("wiggle") == ("wiggle", wiggle)
    labels5 = {k: v for k, v in base.items() if k <= weather.SLOT_DEGREE}
    for colon in ("on", "tick"):
        assert weather.glyph_set(colon, meridiem="am") == (
            "clock-am", {**labels5, weather.SLOT_MERIDIEM: glyphs.AM}), colon
        assert weather.glyph_set(colon, meridiem="pm") == (
            "clock-pm", {**labels5, weather.SLOT_MERIDIEM: glyphs.PM}), colon
    assert weather.glyph_set("twinkle", meridiem="pm") == (
        "twinkle-pm", {**twinkle, weather.SLOT_MERIDIEM: glyphs.PM})
    assert len(weather.glyph_set("twinkle")[1]) == 9      # exactly full
    labels = {k: v for k, v in base.items() if k <= weather.SLOT_DEGREE}
    pacs = {weather.SLOT_PAC_A: glyphs.PACMAN_CLOSED, weather.SLOT_PAC_B: glyphs.PACMAN_OPEN}

    def sprite(a, b):
        return {weather.SLOT_SPRITE_A: a, weather.SLOT_SPRITE_B: b}

    cases = {
        # duo: pacman (7/8) eats the chosen sprite (5/6)
        "duo-ghost": {**labels, **sprite(glyphs.GHOST_A, glyphs.GHOST_B), **pacs},
        "duo-heart": {**labels, **sprite(glyphs.HEART_FULL, glyphs.HEART_EMPTY), **pacs},
        "duo-pacman": {**labels, **sprite(glyphs.mirror(glyphs.PACMAN_CLOSED),
                                          glyphs.mirror(glyphs.PACMAN_OPEN)), **pacs},
        # solo: the chosen sprite alone (5/6); the solo ghost glances the other way
        "ghost": {**labels, **sprite(glyphs.GHOST_B, glyphs.GHOST_C)},
        "heart": {**labels, **sprite(glyphs.HEART_FULL, glyphs.HEART_EMPTY)},
        "pacman": {**labels, **sprite(glyphs.PACMAN_CLOSED, glyphs.PACMAN_OPEN)},
    }
    for cast, expected in cases.items():
        assert weather.glyph_set("pacman", cast) == (f"pacman-{cast}", expected), cast
    assert weather.glyph_set("pacman") == ("pacman-duo-ghost", cases["duo-ghost"])


# --- WeatherFetcher ------------------------------------------------------------
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
    assert (s["high"], s["low"], s["current"]) == (92.6, 74.2, 82.4)
    assert s["rain"] == pytest.approx(0.40)
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


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_become_none(bad):
    p = {**PAYLOAD, "current": {**PAYLOAD["current"], "temperature_2m": bad}}
    r = weather.parse(p, OBSERVED)
    assert r.current is None
    assert len(weather.bottom_line(r, OBSERVED)) == 20


def test_thread_survives_an_unexpected_error_and_logs_it():
    import threading

    logged, first, second = [], threading.Event(), threading.Event()

    def get_json(url, timeout):
        if not first.is_set():
            first.set()
            raise RuntimeError("bug")
        second.set()
        return PAYLOAD

    f = weather.WeatherFetcher(get_json=get_json, log=logged.append)
    f.set_location((1.0, 2.0))
    assert first.wait(2)
    for _ in range(200):           # wait for the thread to finish handling the error
        if logged:
            break
        threading.Event().wait(0.01)
    f.set_location((3.0, 4.0))     # new location -> due now -> the thread fetches again
    assert second.wait(2)
    f.stop()
    assert any("bug" in m for m in logged)


def test_non_finite_hours_are_skipped():
    temps = [_PAST, float("nan"), 70.0, float("inf"), 60.0] + [65.0] * 20
    p = {**PAYLOAD, "hourly": {**PAYLOAD["hourly"], "temperature_2m": temps}}
    r = weather.parse(p, OBSERVED)
    assert (r.high, r.low) == (70.0, 60.0)
