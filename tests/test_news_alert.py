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
         "dynamic_colon": "on", "news_enabled": True, "news_topics": ["politics"],
         "news_interval_min": 5, "news_gap_min": 10, "news_repeat": 1, "news_speed_ms": 250,
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


def test_text_starts_off_screen_and_enters_from_the_right():
    assert na.window("ABC", 0, 0, 100) == " " * 20                 # nothing yet
    assert na.window("ABC", 100, 0, 100) == " " * 19 + "A"         # first char at the edge
    assert na.window("ABC", 300, 0, 100) == " " * 17 + "ABC"


def test_passes_are_separated_by_a_six_space_gap():
    # repeat=1: ABC, 6 spaces, ABC — step 12 puts both copies in view
    assert na.window("ABC", 1200, 1, 100) == " " * 8 + "ABC" + " " * 6 + "ABC"


def test_it_ends_once_the_last_character_has_left_the_screen():
    speed, repeat, text = 100, 1, "X" * 30
    end = na.duration_ms(text, repeat, speed)
    assert end == (20 + 30 + 6 + 30) * speed                       # in, 2 passes + gap, out
    assert na.window(text, end - speed, repeat, speed) == "X" + " " * 19   # last char at the left
    assert na.window(text, end, repeat, speed) == " " * 20                  # gone


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
    assert top == na.banner() and bottom == " " * 20              # starts off screen
    assert f.render(_at(250 * 20), STATE)[1] == "BBC: A headline that"   # cites the source
    end = na.duration_ms("BBC: " + HEAD.title, 1, 250)
    f.tick(_at(end), STATE)
    assert not f.alerting(_at(end))
    assert f.render(_at(end), STATE)[0].startswith("09/24/26")


def test_news_off_means_no_polling_and_no_alert():
    f = _frame(alert=HEAD)
    f.tick(T0, {**STATE, "news_enabled": False})
    assert f.news.config[0] is None and not f.alerting(T0)


def test_polling_follows_the_settings():
    f = _frame()
    f.tick(T0, {**STATE, "news_topics": ["mississippi", "tech"], "news_interval_min": 2})
    assert f.news.config == (["mt", "nyt_tech", "bbc_tech", "linux"], 120)


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


def test_the_ticker_cites_each_source_by_its_label():
    f = _frame(alert=Headline("linux", "Kernel 7.0 lands", "l1", 1.0))
    f.tick(T0, STATE)
    assert f.render(_at(250 * 20), STATE)[1] == "PHORONIX: Kernel 7.0"   # the outlet


# --- the gap between alerts ---------------------------------------------------------
def test_a_new_lead_inside_the_gap_waits_for_it_then_plays():
    f = _frame(alert=HEAD)
    f.tick(T0, STATE)                                  # alert 1 at 12:00
    second = Headline("nyt_politics", "Second story", "n2", 2.0)
    f.news.alert = second
    f.tick(T0 + timedelta(minutes=3), STATE)
    assert not f.alerting(T0 + timedelta(minutes=3))   # inside the 10-minute gap: held
    assert f.news.alert is second                      # ...and not consumed
    f.tick(T0 + timedelta(minutes=10), STATE)
    assert f.alerting(T0 + timedelta(minutes=10))
    assert f.render(T0 + timedelta(minutes=10, seconds=5), STATE)[1].startswith("NYT: Second")


def test_no_gap_means_back_to_back_is_allowed():
    f = _frame(alert=HEAD)
    f.tick(T0, {**STATE, "news_gap_min": 0})
    end = T0 + timedelta(milliseconds=na.duration_ms("BBC: " + HEAD.title, 1, 250))
    f.news.alert = Headline("mt", "Local", "m1", 3.0)
    f.tick(end, {**STATE, "news_gap_min": 0})
    assert f.alerting(end)


def test_show_latest_ignores_the_gap():
    f = _frame(alert=HEAD, latest=Headline("mt", "Local", "m1", 3.0))
    f.tick(T0, STATE)
    later = T0 + timedelta(minutes=1)
    f.tick(later, STATE)
    assert f.show_latest(later, STATE) and f.alerting(later)

