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


# --- message rows: per-row source, scroll and direction (merged scroll mode) ---
from datetime import timedelta  # noqa: E402

from checkout.frames.message import SCROLL_FLOOR_MS  # noqa: E402

EPOCH = datetime.fromtimestamp(0)


def _msg(state, ms=0, now=None):
    """Render like the daemon does: the frame, then fit/align to 20 cells."""
    now = (now or EPOCH) + timedelta(milliseconds=ms)
    return render_lines(*MessageFrame().render(now, state),
                        top_align=state.get("align_top", "center"),
                        bottom_align=state.get("align_bottom", "center"))


def test_scroll_top_only_left():
    state = {
        "message": "A LONG MESSAGE THAT SCROLLS ACROSS THE TOP ROW",
        "scroll_top": True, "scroll_bottom": False,
        "scroll_dir_top": "left", "scroll_speed_ms": 100,
    }
    top0, bottom0 = _msg(state, 0)
    top1, _ = _msg(state, 300)  # +3 steps
    assert len(top0) == 20 and top0 != top1   # top scrolls
    assert bottom0 == " " * 20                  # bottom static + empty


def test_scroll_direction_reverses_offset():
    state = {"message": "0123456789ABCDEFGHIJKLMNOPQRST", "scroll_top": True,
             "scroll_dir_top": "left", "scroll_speed_ms": 100}
    left = _msg({**state, "scroll_dir_top": "left"}, 300)[0]
    right = _msg({**state, "scroll_dir_top": "right"}, 300)[0]
    base = _msg(state, 0)[0]
    assert left != right          # opposite directions diverge
    assert left != base and right != base


def test_scroll_both_rows_independent():
    state = {
        "message": "TOP LINE IS LONG ENOUGH TO SCROLL\nBOTTOM LINE ALSO LONG ENOUGH",
        "scroll_top": True, "scroll_bottom": True,
        "scroll_dir_top": "left", "scroll_dir_bottom": "right", "scroll_speed_ms": 100,
    }
    top, bottom = _msg(state, 500)
    assert len(top) == 20 and len(bottom) == 20
    assert top.strip() and bottom.strip()


def test_scroll_speed_clamped_to_floor():
    # A 1ms request can't outrun the floor: it advances at SCROLL_FLOOR_MS.
    state = {"message": "X" * 40 + "Y", "scroll_top": True, "scroll_dir_top": "left",
             "scroll_speed_ms": 1}
    assert _msg(state, SCROLL_FLOOR_MS - 1)[0] == _msg(state, 0)[0]


def test_clock_source_row_shows_time_and_ticks():
    state = {"message": "IGNORED TOP\nIGNORED BOTTOM",
             "scroll_top_source": "clock", "scroll_bottom_source": "message"}
    top0, bottom0 = _msg(state, now=datetime(2026, 6, 19, 12, 0, 0))
    top1, _ = _msg(state, now=datetime(2026, 6, 19, 12, 0, 1))
    assert top0.strip() == "12:00:00 PM"   # clock TIME line, not the message
    assert top1.strip() == "12:00:01 PM"   # ticks each second
    assert bottom0.strip() == "IGNORED BOTTOM"


def test_clock_top_scrolling_message_bottom():
    state = {
        "message": "\nA LONG BOTTOM MESSAGE THAT SCROLLS ACROSS THE ROW",
        "scroll_top_source": "clock", "scroll_bottom_source": "message",
        "scroll_bottom": True, "scroll_dir_bottom": "left", "scroll_speed_ms": 100,
    }
    now = datetime(2026, 6, 19, 12, 0, 0)
    top, b0 = _msg(state, 0, now)
    b1 = _msg(state, 300, now)[1]
    assert top.strip() == "12:00:00 PM"
    assert len(b0) == 20 and b0 != b1  # bottom message scrolls


def test_static_single_line_still_word_wraps():
    # Neither row scrolls, no line break: the old message-mode wrap is kept.
    state = {"message": "the quick brown fox jumps over"}
    assert [r.strip() for r in _msg(state)] == ["the quick brown fox", "jumps over"]


def test_scrolling_single_line_stays_on_the_top_row():
    state = {"message": "the quick brown fox jumps over", "scroll_top": True,
             "scroll_speed_ms": 100}
    top, bottom = _msg(state)
    assert top.startswith("the quick brown fox ")
    assert bottom.strip() == ""


def test_single_line_under_a_clock_top_goes_to_the_bottom_row():
    state = {"message": "HELLO", "scroll_top_source": "clock"}
    top, bottom = _msg(state, now=datetime(2026, 6, 19, 12, 0, 0))
    assert top.strip() == "12:00:00 PM"
    assert bottom.strip() == "HELLO"


def test_static_rows_keep_their_alignment():
    state = {"message": "HI\nTHERE", "align_top": "left", "align_bottom": "right"}
    assert _msg(state) == ("HI".ljust(20), "THERE".rjust(20))


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
_DOT = chr(GLYPH_CODES[_weather.SLOT_COLON_DOT])
_THIN = chr(GLYPH_CODES[_weather.SLOT_COLON_THIN])
_PKA = chr(GLYPH_CODES[_weather.SLOT_COLON_PEAK_A])
_PKB = chr(GLYPH_CODES[_weather.SLOT_COLON_PEAK_B])
_WIGGLE = [" ", _DOT, _THIN, _PKA, _THIN, _DOT, " ", _DOT, _THIN, _PKB, _THIN, _DOT]
_TWINKLE = [" ", _DOT, _THIN, _PKA, _PKB, _PKA, _THIN, _DOT]


def _top(colon, us, second=12, half=False):
    state = {**_WX, "weather_colon": colon, "weather_colon_half": half}
    now = _T.replace(second=second, microsecond=us)
    return WeatherFrame(_FakeFetcher()).render(now, state)[0]


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


def _loop(colon, frames, half=False):
    """Sample the middle of each of ``frames`` equal steps across the loop."""
    seconds = 2 if half else 1
    out = []
    for k in range(frames):
        at_us = (2 * k + 1) * seconds * 1_000_000 // (2 * frames)
        out.append(_top(colon, at_us % 1_000_000, second=12 + at_us // 1_000_000,
                        half=half)[15])
    return out


def test_wiggle_alternates_twists_once_a_second():
    assert _loop("wiggle", 12) == _WIGGLE


def test_twinkle_goes_straight_up_and_down_once_a_second():
    assert _loop("twinkle", 8) == _TWINKLE


def test_half_speed_doubles_every_loop():
    assert _loop("tick", 2, half=True) == [_THIN, " "]       # 1 s on, 1 s off
    assert _loop("wiggle", 12, half=True) == _WIGGLE
    assert _loop("twinkle", 8, half=True) == _TWINKLE


def test_half_speed_leaves_on_steady():
    assert {_top("on", us, half=True)[15] for us in range(0, 1_000_000, 100_000)} == {_THIN}


def test_colon_defaults_to_tick():
    state = dict(_WX)
    frame = WeatherFrame(_FakeFetcher())
    assert frame.render(_T.replace(microsecond=600_000), state)[0][15] == " "


def _draw(rows):
    return ["".join("#" if r >> c & 1 else "." for c in range(5)) for r in rows]


def test_wiggle_glyphs_match_the_drawn_frames():
    assert _draw(_glyphs.COLON_DOT) == [".....", ".....", "..#..", ".....", "..#..", ".....", "....."]
    assert _draw(_glyphs.COLON_TWIST_R) == [".....", "..##.", "..#..", ".....", "..#..", ".##..", "....."]
    assert _draw(_glyphs.COLON_TWIST_L) == [".....", ".##..", "..#..", ".....", "..#..", "..##.", "....."]


def test_twinkle_glyphs_match_the_drawn_frames():
    assert _draw(_glyphs.COLON_TWINKLE_SMALL) == [".....", ".###.", "..#..", ".....", "..#..", ".###.", "....."]
    assert _draw(_glyphs.COLON_TWINKLE_BIG) == ["..#..", ".###.", "..#..", ".....", "..#..", ".###.", "..#.."]


# --- pacman colon mode ----------------------------------------------------------
# Slots 5/6 hold the chosen sprite's two frames (a mirrored pacman in duo), 7/8
# hold pacman in duo. Which bitmaps sit there depends on the cast (glyph_set).
_SA = chr(GLYPH_CODES[_weather.SLOT_SPRITE_A])
_SB = chr(GLYPH_CODES[_weather.SLOT_SPRITE_B])
_PA = chr(GLYPH_CODES[_weather.SLOT_PAC_A])
_PB = chr(GLYPH_CODES[_weather.SLOT_PAC_B])


def _pac(us, second=12, half=False, sprite="ghost", solo=False):
    state = {**_WX, "weather_colon": "pacman", "weather_colon_half": half,
             "weather_pacman_solo": solo, "weather_pacman_sprite": sprite}
    return WeatherFrame(_FakeFetcher()).render(_T.replace(second=second, microsecond=us), state)[0]


def test_pacman_is_compact_text_left_sprites_far_right():
    top = _pac(100_000)
    assert top == "9/23/26 WED 8:33".ljust(18) + _SA + _PA   # one space, any hour


def test_pacman_longest_date_and_time_still_fit():
    state = {**_WX, "weather_colon": "pacman"}
    top = WeatherFrame(_FakeFetcher()).render(datetime(2026, 12, 31, 23, 59), state)[0]
    assert top[:18] == "12/31/26 THU 11:59" and len(top) == 20   # exactly fills 18


def test_pacman_two_digit_hour_has_one_space():
    state = {**_WX, "weather_colon": "pacman"}
    top = WeatherFrame(_FakeFetcher()).render(datetime(2026, 9, 23, 22, 5), state)[0]
    assert top[:18] == "9/23/26 WED 10:05 "


def test_pacman_keeps_the_minute_and_year_zeros():
    state = {**_WX, "weather_colon": "pacman"}
    top = WeatherFrame(_FakeFetcher()).render(datetime(2027, 1, 5, 0, 7), state)[0]
    assert top.startswith("1/5/27 TUE 12:07")


def test_duo_pacman_eats_the_chosen_sprite_in_step():
    for sprite in ("ghost", "heart"):
        assert _pac(100_000, sprite=sprite)[18:] == _SA + _PA
        assert _pac(600_000, sprite=sprite)[18:] == _SB + _PB


def test_duo_pacman_faces_a_mirror_on_the_opposite_frame():
    assert _pac(100_000, sprite="pacman")[18:] == _SB + _PA   # one open, one closed
    assert _pac(600_000, sprite="pacman")[18:] == _SA + _PB


def test_pacman_half_speed_swaps_each_second():
    assert _pac(600_000, second=12, half=True)[18:] == _SA + _PA
    assert _pac(100_000, second=13, half=True)[18:] == _SB + _PB


def test_solo_puts_the_chosen_sprite_alone_in_the_far_right_cell():
    for sprite in ("ghost", "heart", "pacman"):
        assert _pac(100_000, sprite=sprite, solo=True)[18:] == " " + _SA
        assert _pac(600_000, sprite=sprite, solo=True)[18:] == " " + _SB


def test_pacman_colon_is_steady():
    assert {_pac(us)[13] for us in range(0, 1_000_000, 100_000)} == {":"}


def test_pacman_glyphs_match_the_drawn_frames():
    assert _draw(_glyphs.GHOST_A) == [".....", ".###.", "#####", "##.#.", "#####", "#.#.#", "....."]
    assert _draw(_glyphs.GHOST_B) == [".....", ".###.", "#####", "#.#.#", "#####", "#.#.#", "....."]
    assert _draw(_glyphs.GHOST_C) == [".....", ".###.", "#####", ".#.##", "#####", "#.#.#", "....."]
    assert _draw(_glyphs.PACMAN_CLOSED) == [".....", ".###.", "#####", "...##", "#####", ".###.", "....."]
    assert _draw(_glyphs.PACMAN_OPEN) == [".....", ".###.", "..###", "...##", "..###", ".###.", "....."]
    assert _draw(_glyphs.HEART_FULL) == [".....", ".#.#.", "#####", "#####", ".###.", "..#..", "....."]
    assert _draw(_glyphs.HEART_EMPTY) == [".....", ".#.#.", "#.#.#", "#...#", ".#.#.", "..#..", "....."]


def test_mirror_flips_the_columns():
    assert _draw(_glyphs.mirror(_glyphs.PACMAN_OPEN)) == [
        ".....", ".###.", "###..", "##...", "###..", ".###.", "....."]
    assert _glyphs.mirror(_glyphs.mirror(_glyphs.GHOST_A)) == _glyphs.GHOST_A


def test_widest_line_forces_the_last_solo_sprite():
    from checkout.frames.weather import pacman_cast
    widest = datetime(2026, 12, 31, 12, 33)          # 12/31/26 THU 12:33 = 18 cells
    narrower = datetime(2026, 12, 31, 1, 33)         # 17 cells: duo still fits
    for sprite in ("ghost", "heart", "pacman"):
        state = {**_WX, "weather_colon": "pacman", "weather_pacman_solo": False,
                 "weather_pacman_sprite": sprite}
        assert pacman_cast(state, widest) == sprite
        assert pacman_cast(state, narrower) == f"duo-{sprite}"
        top = WeatherFrame(_FakeFetcher()).render(widest, state)[0]
        assert top[:19] == "12/31/26 THU 12:33 "   # the gap duo had no room for
        assert top[19] in (_SA, _SB)


def test_solo_switch_wins_whatever_the_width():
    from checkout.frames.weather import pacman_cast
    state = {"weather_pacman_solo": True, "weather_pacman_sprite": "heart"}
    assert pacman_cast(state, datetime(2026, 9, 23, 8, 33)) == "heart"
