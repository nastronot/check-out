"""Tests for the ClockFrame format: 'DD MON YYYY' / 'HH:MM:SS AM/PM'."""

from datetime import datetime

from checkout.frames.clock import ClockFrame

frame = ClockFrame()


def render(dt: datetime):
    return frame.render(dt, {})


def test_top_is_dd_mon_yyyy():
    top, _ = render(datetime(2026, 6, 5, 20, 47, 3))
    assert top == "05 JUN 2026"  # zero-padded day, 3-letter UPPER month, 4-digit year


def test_top_day_zero_padded_and_two_digit():
    top, _ = render(datetime(2026, 12, 25, 0, 0, 0))
    assert top == "25 DEC 2026"


def test_bottom_pm_afternoon():
    _, bottom = render(datetime(2026, 6, 5, 13, 5, 9))
    assert bottom == "01:05:09 PM"


def test_bottom_midnight_is_12_am():
    _, bottom = render(datetime(2026, 6, 5, 0, 0, 0))
    assert bottom == "12:00:00 AM"


def test_bottom_noon_is_12_pm():
    _, bottom = render(datetime(2026, 6, 5, 12, 0, 0))
    assert bottom == "12:00:00 PM"


def test_bottom_morning_am_zero_padded_hour():
    _, bottom = render(datetime(2026, 6, 5, 8, 47, 3))
    assert bottom == "08:47:03 AM"


def test_month_abbrevs_cover_all_twelve_deterministically():
    expected = [
        "JAN", "FEB", "MAR", "APR", "MAY", "JUN",
        "JUL", "AUG", "SEP", "OCT", "NOV", "DEC",
    ]
    for month, mon in enumerate(expected, start=1):
        top, _ = render(datetime(2026, month, 1, 0, 0, 0))
        assert top == f"01 {mon} 2026"


def test_lines_fit_in_20_cells():
    top, bottom = render(datetime(2026, 11, 30, 23, 59, 59))
    assert len(top) <= 20
    assert len(bottom) <= 20
    assert bottom == "11:59:59 PM"


# --- short_date_time (weather mode's top line) --------------------------------
from checkout.frames.clock import short_date_time  # noqa: E402


def test_short_date_time_matches_mockup():
    assert short_date_time(datetime(2026, 9, 23, 20, 33, 59)) == "09/23/26 WED 08:33"


def test_short_date_time_midnight_and_noon_are_12():
    assert short_date_time(datetime(2026, 9, 27, 0, 5)) == "09/27/26 SUN 12:05"
    assert short_date_time(datetime(2026, 9, 28, 12, 0)) == "09/28/26 MON 12:00"


def test_short_date_time_is_18_chars_and_fits():
    assert len(short_date_time(datetime(2026, 12, 31, 23, 59))) == 18
