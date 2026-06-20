"""Tests for the message and ticker frames."""

from datetime import datetime

from checkout.frames.message import MessageFrame, _wrap_two_lines
from checkout.frames.ticker import TickerFrame
from checkout.renderer import ticker_window

NOW = datetime(2026, 6, 19, 12, 0, 0)


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
