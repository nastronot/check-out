"""DynamicFrame — ``MM/DD/YY DAY HH:MM`` on top, today's weather on the bottom.

The fetch happens elsewhere (``checkout.weather.WeatherFetcher``, a background
thread); this frame only reads the latest reading, so rendering never waits on
the network.

The colon stands in for the hidden seconds, per ``dynamic_colon``, by changing
the colon CHARACTER — never the hardware cursor (an underline on this glass that
stays on across writes) and never brightness (display-wide, so the whole panel
would change):

- ``on``      — the font's standard ``:``, steady, then a space and an AM/PM
  marker glyph (the line is exactly 20 cells).
- ``tick``    — the same, with the ``:`` blanking for half of each loop.
  (twinkle and pulse also end with the marker.)
- ``twinkle`` — 6 frames straight up and down: blank, a dot, a diamond, four
  corner dots, the diamond, the dot.
- ``pulse``   — 2 frames: the colon's two dots, then a taller column.

- ``pacman``  — ``9/23/26 WED 8:33`` (no leading zeros, one space between
  fields) left-aligned, and in the last two cells pacman eating the chosen
  sprite (``dynamic_pacman_sprite``: ghost | heart | pacman — a pacman faces
  its mirror image, one frame out of step), each swapping between two frames.
  The time colon is the steady font ``:`` (the sprites need the colon's glyph
  slots). Solo
  (``dynamic_pacman_solo`` + ``dynamic_pacman_sprite``) shows just one, in the
  far-right cell — and is FORCED when the date/time fills all 18 cells, since
  duo would then touch the text (``pacman_cast``); the solo ghost glances
  the other way (its own two frames, loaded by ``weather.glyph_set``).

Each loop takes 1 second, or 2 with ``dynamic_colon_half`` (half speed), and is
locked to the wall clock (a 2 s loop starts on even seconds). Each time feature
loads its own glyphs (``weather.glyph_set``).

Only the colon cell changes, so the daemon's cell-diff writes one cell.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .. import weather
from ..config import COLS
from ..driver import GLYPH_CODES
from ..news import SOURCES, Headline
from ..news import sources_for as news_sources_for
from . import news_alert
from .base import Frame
from .clock import compact_date_time, short_date_time

NO_LOCATION = "SET LOCATION"
_US_PER_S = 1_000_000

_BLANK = " "
_MARK = chr(GLYPH_CODES[weather.SLOT_MERIDIEM])   # AM or PM, per the loaded glyph
_ANIM_1 = chr(GLYPH_CODES[weather.SLOT_ANIM_1])
_ANIM_2 = chr(GLYPH_CODES[weather.SLOT_ANIM_2])
_ANIM_3 = chr(GLYPH_CODES[weather.SLOT_ANIM_3])

# The frames of each animated colon, spread evenly across the loop. Each loop
# wraps back to its first frame, so every frame is the same length.
_LOOPS = {
    "tick": (":", _BLANK),
    "twinkle": (_BLANK, _ANIM_1, _ANIM_2, _ANIM_3, _ANIM_2, _ANIM_1),
    "pulse": (_ANIM_1, _ANIM_2),
}


def meridiem(now: datetime) -> str:
    """"am" before noon, else "pm" — picks which marker bitmap is loaded."""
    return "am" if now.hour < 12 else "pm"


def colon_mode(state: dict) -> str:
    """The colon behaviour, coerced to one of ``weather.COLON_MODES``."""
    mode = state.get("dynamic_colon")
    return mode if mode in weather.COLON_MODES else "tick"


def colon_char(state: dict, now: datetime) -> str:
    """The character in the colon's cell at ``now``."""
    frames = _LOOPS.get(colon_mode(state))
    if frames is None:
        return ":"  # on
    return frames[_loop_index(state, now, len(frames))]


# pacman: each sprite's two frames, swapped once per half loop.
_SPRITE = (chr(GLYPH_CODES[weather.SLOT_SPRITE_A]), chr(GLYPH_CODES[weather.SLOT_SPRITE_B]))
_PACMAN = (chr(GLYPH_CODES[weather.SLOT_PAC_A]), chr(GLYPH_CODES[weather.SLOT_PAC_B]))


def _loop_index(state: dict, now: datetime, frames: int) -> int:
    """Which of ``frames`` evenly spaced frames is showing at ``now``, for a loop
    of 1 s (2 s at half speed) locked to the wall clock."""
    seconds = 2 if state.get("dynamic_colon_half") else 1
    phase_us = (now.second % seconds) * _US_PER_S + now.microsecond
    return phase_us * frames // (seconds * _US_PER_S)


def pacman_cast(state: dict, now: datetime) -> str:
    """Who is on screen: "duo-<sprite>" (pacman eating the chosen sprite) or
    "<sprite>" alone (solo), where sprite is ghost | heart | pacman.

    Solo when the switch is on, AND automatically when the date/time is as wide
    as it gets (a 2-digit month and day and a 2-digit hour: 18 cells) — duo's
    two cells would then touch the text. Either way the sprite is the remembered
    ``dynamic_pacman_sprite``. The daemon loads glyphs from this too, so what is
    drawn and what is defined always agree.
    """
    sprite = state.get("dynamic_pacman_sprite")
    if sprite not in weather.PACMAN_SPRITES:
        sprite = "ghost"
    if state.get("dynamic_pacman_solo") or len(compact_date_time(now)) > COLS - 3:
        return sprite
    return f"duo-{sprite}"


def pacman_top(state: dict, now: datetime) -> str:
    """Compact date/time on the left + two sprite cells on the right (20 cells)."""
    i = _loop_index(state, now, 2)
    cast = pacman_cast(state, now)
    if not cast.startswith("duo-"):
        cells = " " + _SPRITE[i]       # solo: the one sprite sits in the last cell
    elif cast == "duo-pacman":
        cells = _SPRITE[1 - i] + _PACMAN[i]   # a mirror pacman, on the opposite frame
    else:
        cells = _SPRITE[i] + _PACMAN[i]       # pacman eating the ghost / heart
    return compact_date_time(now).ljust(COLS - 2) + cells


@dataclass
class _Alert:
    headline: Headline
    text: str            # what scrolls: "AP: <title>"
    started_ms: int
    speed_ms: int
    repeat: int
    ends_ms: int


def _ms(now: datetime) -> int:
    return int(now.timestamp() * 1000)


class DynamicFrame(Frame):
    """Time + weather, interrupted by NEWS ALERTs.

    ``fetcher`` is the weather fetcher, ``news`` the news fetcher (both run on
    background threads). :meth:`tick` — called by the daemon every loop —
    points them at what to fetch and starts / ends alerts; :meth:`render` and
    :meth:`brightness` then draw whichever screen is current.
    """

    name = "dynamic"
    align = "center"  # always centered; the bottom line fills all 20 cells anyway

    def __init__(self, fetcher, news=None) -> None:
        self.fetcher = fetcher
        self.news = news
        self._alert: _Alert | None = None
        self._last_start_ms: int | None = None   # when the last alert started (the gap)
        self._shown: _Alert | None = None        # the last alert played (kept after it ends)

    # --- driving the fetchers and alerts ------------------------------------------
    def tick(self, now: datetime, state: dict, active: bool = True) -> None:
        """Configure the fetchers; end a finished alert, start a pending one.

        ``active`` is whether dynamic is the mode on screen: outside it nothing
        is fetched and any alert ends.
        """
        self.fetcher.set_location(weather.location(state) if active else None)
        if self.news is None:
            return
        enabled = active and bool(state.get("news_enabled"))
        interval_s = int(state.get("news_interval_min", 2)) * 60
        sources = news_sources_for(state.get("news_topics")) if enabled else None
        self.news.set_config(sources, interval_s)
        if not enabled:
            self._alert = None
            return
        if self._alert is not None and _ms(now) >= self._alert.ends_ms:
            self._alert = None
        # Nothing new -> nothing shown. A new lead inside the gap WAITS (it isn't
        # taken), so when the gap ends the newest one plays — a burst of changes
        # collapses into one alert.
        gap_ms = int(state.get("news_gap_min", 10)) * 60_000
        gap_over = self._last_start_ms is None or _ms(now) - self._last_start_ms >= gap_ms
        if self._alert is None and gap_over:
            pending = self.news.take_alert()
            if pending is not None:
                self._start(pending, now, state)

    def show_latest(self, now: datetime, state: dict | None = None) -> bool:
        """Play the alert for the newest headline now; False if there is none."""
        latest = self.news.latest() if self.news is not None else None
        if latest is None:
            return False
        self._start(latest, now, state or {})
        return True

    def alerting(self, now: datetime) -> bool:
        return self._alert is not None and _ms(now) < self._alert.ends_ms

    def _start(self, headline: Headline, now: datetime, state: dict) -> None:
        speed = int(state.get("news_speed_ms", 250))
        repeat = int(state.get("news_repeat", 1))
        started = _ms(now)
        self._last_start_ms = started
        source = SOURCES.get(headline.source)
        text = f"{source.name if source else headline.source.upper()}: {headline.title}"
        self._alert = _Alert(headline, text, started, speed, repeat,
                             started + news_alert.duration_ms(text, repeat, speed))
        self._shown = self._alert

    def shown(self) -> dict | None:
        """The last headline played on the glass, with its link, for status.json
        (the waybar panel opens it). Kept after the alert ends and outside dynamic;
        None until the first alert since the daemon started."""
        if self._shown is None:
            return None
        h = self._shown.headline
        source = SOURCES.get(h.source)
        return {
            "source": h.source,
            "outlet": source.name if source else h.source.upper(),
            "title": h.title,
            "link": h.link if h.link.startswith(("https://", "http://")) else None,
            "shown_at": datetime.fromtimestamp(self._shown.started_ms / 1000).astimezone().isoformat(),
        }

    # --- drawing ---------------------------------------------------------------------
    def brightness(self, now: datetime, state: dict, base: int) -> int | None:
        if not self.alerting(now):
            return None
        elapsed = _ms(now) - self._alert.started_ms
        effect = state.get("news_effect")
        if effect == "flash":
            return news_alert.flash_level(elapsed, base)
        if effect == "throb":
            return news_alert.throb_level(elapsed)
        return None

    def render(self, now: datetime, state: dict) -> tuple[str, str]:
        if self.alerting(now):
            a = self._alert
            return news_alert.banner(), news_alert.window(
                a.text, _ms(now) - a.started_ms, a.repeat, a.speed_ms)
        if colon_mode(state) == "pacman":
            top = pacman_top(state, now)
        else:
            top = short_date_time(now, colon=colon_char(state, now))
            if colon_mode(state) in weather.MERIDIEM_FEATURES:
                top += " " + _MARK
        if weather.location(state) is None:
            return top, NO_LOCATION
        return top, weather.bottom_line(self.fetcher.latest(), now.timestamp())
