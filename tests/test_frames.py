"""Tests for the message and ticker frames."""

from datetime import datetime

from checkout.driver import GLYPH_CODES
from checkout.frames.message import MessageFrame, _wrap_two_lines
from checkout.frames.ticker import TickerFrame
from checkout.renderer import render_lines, ticker_window

NOW = datetime(2026, 6, 19, 12, 0, 0)

ALL_GLYPHS = "".join(f"{{g{n}}}" for n in range(9))  # {g0}..{g8}


def test_message_newline_splits_top_bottom():
    top, bottom = MessageFrame().render(NOW, {"message": "HELLO\nWORLD"})
    assert top == "HELLO"
    assert bottom == "WORLD"


def test_message_word_wraps_across_two_lines():
    top, bottom = _wrap_two_lines("the quick brown fox jumps over", width=20)
    assert len(top) <= 20
    assert len(bottom) <= 20
    # Greedy fill: as many whole words as fit on the top line.
    assert top == "the quick brown fox"
    assert bottom == "jumps over"


def test_message_long_single_word_goes_on_top():
    top, bottom = _wrap_two_lines("supercalifragilisticexpialidocious", width=20)
    # Unbreakable word longer than the line lands on top (renderer truncates).
    assert top == "supercalifragilisticexpialidocious"
    assert bottom == ""


def test_message_empty():
    assert MessageFrame().render(NOW, {"message": ""}) == ("", "")


def test_ticker_short_message_does_not_scroll():
    top, bottom = TickerFrame().render(NOW, {"message": "hi", "scroll_speed_ms": 300})
    assert top == "hi".ljust(20)
    assert bottom == ""


def test_ticker_newline_is_treated_as_space():
    # A two-line message in ticker mode shouldn't crash or carry a literal '\n';
    # the newline becomes a space so it scrolls as one line.
    top, bottom = TickerFrame().render(NOW, {"message": "AB\nCD", "scroll_speed_ms": 300})
    assert "\n" not in top
    assert top == "AB CD".ljust(20)
    assert bottom == ""


def test_ticker_advances_with_time():
    msg = "this is a long scrolling message that exceeds twenty chars"
    state = {"message": msg, "scroll_speed_ms": 100}
    t0 = datetime(2026, 6, 19, 12, 0, 0)
    t1 = datetime(2026, 6, 19, 12, 0, 1)  # +1s = +10 steps at 100ms
    top0, _ = TickerFrame().render(t0, state)
    top1, _ = TickerFrame().render(t1, state)
    assert top0 != top1
    assert len(top0) == 20 and len(top1) == 20


def test_ticker_window_cycle_is_consistent():
    text = "0123456789ABCDEFGHIJKLMNO"  # 25 chars, > 20
    gap = 4
    n = len(text) + gap
    assert ticker_window(text, n) == ticker_window(text, 0)


def test_message_glyph_placeholder_substitution():
    top, bottom = MessageFrame().render(NOW, {"message": "HI {g0}"})
    # {g0} becomes the single glyph code char for slot 0 (0x15).
    assert chr(GLYPH_CODES[0]) in top
    assert "{g0}" not in top
    # The placeholder collapses to ONE column (4 source chars -> 1 glyph).
    assert top == "HI " + chr(GLYPH_CODES[0])


def test_message_glyph_placeholder_newline_split():
    top, bottom = MessageFrame().render(NOW, {"message": "{g8}\n{g6}"})
    assert top == chr(GLYPH_CODES[8])   # slot 8 -> 0x1E
    assert bottom == chr(GLYPH_CODES[6])  # slot 6 -> 0x1C (0x1B skipped)


def test_ticker_glyph_placeholder_substitution():
    msg = "scrolling status with a glyph {g3} mixed into the long text here"
    top, _ = TickerFrame().render(NOW, {"message": msg, "scroll_speed_ms": 100})
    assert "{g3}" not in top
    assert len(top) == 20


def test_message_per_line_alignment():
    # align_top=right + align_bottom=left, applied via render_lines (the daemon
    # path), pad each line independently on its own side.
    logical = MessageFrame().render(NOW, {"message": "HI\nYO"})
    top, bottom = render_lines(*logical, top_align="right", bottom_align="left")
    assert top == " " * 18 + "HI"
    assert bottom == "YO" + " " * 18


def test_message_all_nine_glyphs_render_as_cells():
    # Regression: glyph codes 0x1C-0x1E (slots 6-8) are Python whitespace, so the
    # old str.split() word-wrap silently dropped them (a 9-glyph line showed ~6).
    top, bottom = MessageFrame().render(NOW, {"message": ALL_GLYPHS})
    assert top == "".join(chr(c) for c in GLYPH_CODES)  # all 9, in order
    assert len(top) == 9
    assert bottom == ""


def test_message_glyph_line_fits_20_truncates_21():
    # Each {gN} is one cell; up to 20 fit a line, 21 truncates to 20 (renderer).
    top20, _ = render_lines(*MessageFrame().render(NOW, {"message": "{g8}" * 20}))
    assert top20 == chr(GLYPH_CODES[8]) * 20
    top21, _ = render_lines(*MessageFrame().render(NOW, {"message": "{g8}" * 21}))
    assert len(top21) == 20
    assert top21 == chr(GLYPH_CODES[8]) * 20


def test_ticker_advances_one_cell_per_glyph():
    # All 9 glyph cells survive in the ticker window (no whitespace-drop), and the
    # window is exactly one display line wide.
    top, _ = TickerFrame().render(NOW, {"message": ALL_GLYPHS, "scroll_speed_ms": 300})
    for code in GLYPH_CODES:
        assert chr(code) in top
    assert len(top) == 20


# --- WeatherFrame ------------------------------------------------------------
from checkout import glyphs as _glyphs  # noqa: E402
from checkout import weather as _weather  # noqa: E402
from checkout.frames.weather import NO_LOCATION, WeatherFrame  # noqa: E402


class _FakeFetcher:
    def __init__(self, reading=None):
        self.reading = reading

    def latest(self):
        return self.reading


_WX = {"weather_lat": 41.9, "weather_lon": -87.6}
_T = datetime(2026, 9, 23, 20, 33, 12)
_MID = chr(GLYPH_CODES[_weather.SLOT_COLON_MID])
_LOW = chr(GLYPH_CODES[_weather.SLOT_COLON_LOW])
_THIN = chr(GLYPH_CODES[_weather.SLOT_COLON_THIN])


def _top(colon, us):
    state = {**_WX, "weather_colon": colon}
    return WeatherFrame(_FakeFetcher()).render(_T.replace(microsecond=us), state)[0]


def test_weather_top_is_the_short_clock():
    assert _top("on", 0) == f"09/23/26 WED 08{_THIN}33"


def test_weather_without_location_asks_for_one():
    _, bottom = WeatherFrame(_FakeFetcher()).render(_T, {})
    assert bottom == NO_LOCATION


def test_weather_bottom_is_twenty_cells_even_with_no_reading():
    _, bottom = WeatherFrame(_FakeFetcher()).render(_T, _WX)
    assert len(bottom) == 20


def test_on_is_a_steady_colon():
    assert {_top("on", us)[15] for us in range(0, 1_000_000, 100_000)} == {_THIN}


def test_tick_shows_the_colon_for_the_first_half_second_only():
    assert _top("tick", 0)[15] == _THIN
    assert _top("tick", 499_999)[15] == _THIN
    assert _top("tick", 500_000)[15] == " "
    assert _top("tick", 999_999)[15] == " "


def test_tick_changes_only_the_colon_cell():
    on, off = _top("tick", 0), _top("tick", 600_000)
    assert [i for i in range(len(on)) if on[i] != off[i]] == [15]


def test_pulse_fades_the_colon_through_four_steps_once_a_second():
    steps = [_top("pulse", (2 * k + 1) * 1_000_000 // 12)[15] for k in range(6)]  # mid-step
    assert steps == [" ", _LOW, _MID, ":", _MID, _LOW]


def test_colon_defaults_to_tick():
    state = dict(_WX)
    frame = WeatherFrame(_FakeFetcher())
    assert frame.render(_T.replace(microsecond=600_000), state)[0][15] == " "


def test_colon_fade_glyphs_thin_the_real_colon():
    # The font's ':' is two 2x2 blocks (8 dots); the fade steps light 4, then 2,
    # always a subset of the real colon so the fade reads as the same colon.
    real = [0, 6, 6, 0, 6, 6, 0]
    for rows, dots in ((_glyphs.COLON_MID, 4), (_glyphs.COLON_LOW, 2)):
        assert sum(bin(r).count("1") for r in rows) == dots
        assert all(r & ~full == 0 for r, full in zip(rows, real))


def test_thin_colon_is_the_centre_column():
    rows = ["".join("#" if r >> c & 1 else "." for c in range(5)) for r in _glyphs.COLON_THIN]
    assert rows == [".....", "..#..", "..#..", ".....", "..#..", "..#..", "....."]
