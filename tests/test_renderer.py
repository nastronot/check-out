"""Unit tests for the pure renderer."""

from checkout.renderer import fit_line, ticker_window


def test_fit_line_pads_to_width():
    assert fit_line("hi", align="left") == "hi" + " " * 18
    assert len(fit_line("hi")) == 20


def test_fit_line_center():
    # "abcd" centered in 20 -> 8 left, 8 right.
    out = fit_line("abcd", align="center")
    assert out == "        abcd        "
    assert len(out) == 20


def test_fit_line_right():
    out = fit_line("end", align="right")
    assert out == " " * 17 + "end"
    assert len(out) == 20


def test_fit_line_truncates():
    long = "x" * 30
    out = fit_line(long, align="center")
    assert out == "x" * 20
    assert len(out) == 20


def test_fit_line_unknown_align():
    import pytest

    with pytest.raises(ValueError):
        fit_line("x", align="middle")


def test_ticker_short_text_no_scroll():
    # Text that fits is left-justified and ignores the offset.
    assert ticker_window("short", 0) == "short".ljust(20)
    assert ticker_window("short", 7) == "short".ljust(20)


def test_ticker_window_offset_zero():
    text = "A" * 25  # longer than width
    assert ticker_window(text, 0) == "A" * 20
    assert len(ticker_window(text, 0)) == 20


def test_ticker_window_full_cycle_wraps_with_gap():
    text = "0123456789ABCDEFGHIJKLMNO"  # 25 chars, > 20
    gap = 4
    cycle = text + " " * gap
    n = len(cycle)  # 29
    # Every window is exactly 20 chars across a full cycle.
    for offset in range(n):
        assert len(ticker_window(text, offset, gap=gap)) == 20
    # Offset n wraps back to offset 0.
    assert ticker_window(text, n, gap=gap) == ticker_window(text, 0, gap=gap)
    # A window near the end spans the gap then wraps to the start.
    win = ticker_window(text, n - 2, gap=gap)
    assert win == "  " + text[:18]  # 2 trailing gap spaces, then wrap


def test_ticker_window_advances():
    text = "abcdefghijklmnopqrstuvwxyz"  # 26 chars
    assert ticker_window(text, 0)[0] == "a"
    assert ticker_window(text, 1)[0] == "b"
    assert ticker_window(text, 2)[0] == "c"
