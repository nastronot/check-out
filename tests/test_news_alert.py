"""The NEWS ALERT screen in dynamic mode: banner, scrolling headline, timing,
brightness effects, and how DynamicFrame starts and ends an alert."""

from datetime import datetime, timedelta

from checkout import glyphs
from checkout.driver import GLYPH_CODES
from checkout.frames import news_alert as na
from checkout.frames.dynamic import DynamicFrame
from checkout.news import Headline

T0 = datetime(2026, 9, 24, 12, 0, 0)
HEAD = Headline("bbc", "A headline that is long enough to scroll", "b1", 1.0)


class _Weather:
    def latest(self):
        return None

    def set_location(self, loc):
        self.loc = loc


class _News:
    def __init__(self, alert=None, latest=None):
        self.alert, self._latest, self.config = alert, latest, "unset"

    def set_config(self, sources, interval_s):
        self.config = (sources, interval_s)

    def take_alert(self):
        a, self.alert = self.alert, None
        return a

    def latest(self):
        return self._latest


STATE = {"mode": "dynamic", "weather_lat": 41.9, "weather_lon": -87.6,
         "dynamic_colon": "on", "news_enabled": True, "news_sources": ["bbc"],
         "news_interval_min": 5, "news_repeat": 1, "news_speed_ms": 250,
         "news_effect": "none"}


def _frame(**news):
    return DynamicFrame(_Weather(), _News(**news))


def _at(ms):
    return T0 + timedelta(milliseconds=ms)


# --- the banner and the headline window ---------------------------------------------
def test_banner_is_twenty_cells_with_bars_around_news_alert():
    banner = na.banner()
    assert len(banner) == 20 and banner[4:16] == " NEWS ALERT "
    codes = {ord(c) for c in banner[:4] + banner[16:]}
    assert codes <= set(GLYPH_CODES) and len(codes) == 7          # g3's bar is used twice


def test_alert_glyphs_are_the_seven_distinct_bars():
    g = na.alert_glyphs()
    assert len(g) == 7
    banner = na.banner()
    slot = {chr(GLYPH_CODES[s]): rows for s, rows in g.items()}
    assert [slot[c] for c in banner[:4]] == glyphs.NEWS_BANNER_LEFT
    assert [slot[c] for c in banner[16:]] == glyphs.NEWS_BANNER_RIGHT


def test_window_scrolls_one_cell_per_step_with_a_six_space_gap():
    title = "X" * 30
    assert na.window(title, 0, 250) == "X" * 20
    assert na.window(title, 250 * 25, 250) == "X" * 5 + " " * 6 + "X" * 9


def test_duration_is_passes_times_cycle_times_speed():
    assert na.duration_ms("X" * 30, repeat=1, speed_ms=250) == 2 * 36 * 250
    assert na.duration_ms("X" * 30, repeat=0, speed_ms=100) == 36 * 100


# --- brightness effects -------------------------------------------------------------------
def test_flash_is_three_full_sweeps_then_steps_back_to_base():
    levels = [na.flash_level(ms, base=2) for ms in range(60, 3000, 120)]
    assert levels[:18] == [0, 1, 2, 3, 2, 1] * 3
    assert levels[18:21] == [0, 1, 2]
    assert set(levels[21:]) == {2}


def test_throb_repeats_for_as_long_as_it_runs():
    levels = [na.throb_level(ms) for ms in range(75, 150 * 12, 150)]
    assert levels == [0, 1, 2, 3, 2, 1] * 2


# --- DynamicFrame: starting, drawing, ending --------------------------------------------
def test_a_pending_alert_takes_over_the_screen_then_the_clock_returns():
    f = _frame(alert=HEAD)
    f.tick(T0, STATE)
    assert f.alerting(T0)
    top, bottom = f.render(_at(0), STATE)
    assert top == na.banner() and bottom == HEAD.title[:20]
    end = na.duration_ms(HEAD.title, 1, 250)
    f.tick(_at(end), STATE)
    assert not f.alerting(_at(end))
    assert f.render(_at(end), STATE)[0].startswith("09/24/26")


def test_news_off_means_no_polling_and_no_alert():
    f = _frame(alert=HEAD)
    f.tick(T0, {**STATE, "news_enabled": False})
    assert f.news.config == (None, 300) and not f.alerting(T0)


def test_polling_follows_the_settings():
    f = _frame()
    f.tick(T0, {**STATE, "news_sources": ["ap", "nyt"], "news_interval_min": 2})
    assert f.news.config == (["ap", "nyt"], 120)


def test_leaving_dynamic_or_turning_news_off_ends_an_alert():
    for change in ({"news_enabled": False}, {"mode": "clock"}):
        f = _frame(alert=HEAD)
        f.tick(T0, STATE)
        f.tick(_at(100), {**STATE, **change}, active=change.get("mode", "dynamic") == "dynamic")
        assert not f.alerting(_at(100)), change


def test_show_latest_plays_the_newest_headline_or_does_nothing():
    f = _frame(latest=HEAD)
    f.tick(T0, STATE)
    assert f.show_latest(T0) is True and f.alerting(T0)
    empty = _frame()
    empty.tick(T0, STATE)
    assert empty.show_latest(T0) is False and not empty.alerting(T0)


def test_brightness_hook_follows_the_effect_only_during_an_alert():
    f = _frame(alert=HEAD)
    assert f.brightness(T0, {**STATE, "news_effect": "throb"}, 3) is None     # no alert yet
    f.tick(T0, STATE)
    assert f.brightness(_at(75), {**STATE, "news_effect": "throb"}, 3) == 0
    assert f.brightness(_at(75), {**STATE, "news_effect": "none"}, 3) is None
    assert f.brightness(_at(60), {**STATE, "news_effect": "flash"}, 3) == 0
