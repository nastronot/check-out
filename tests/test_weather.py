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
