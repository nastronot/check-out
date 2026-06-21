"""TickerFrame — horizontally scroll a long message across the top line.

This is a SOFTWARE scroll (a moving window over the text). NOTE: as of v0.7.3 the
daemon drives software scrolling via ``daemon.render_scroll`` (mode "scroll" —
2-line, per-row direction, speed floor), not this single-line frame. TickerFrame
is retained as a small pure component (and its tests document the window
behaviour the scroll mode reuses through ``renderer.ticker_window``).

The window advances one column every ``scroll_speed_ms`` of wall-clock time,
looping with a gap. Stateless: the offset is derived from ``now`` and the speed.
"""

from __future__ import annotations

from datetime import datetime

from .. import config
from ..driver import apply_glyph_placeholders
from ..renderer import ticker_window
from .base import Frame

WIDTH = config.COLS  # 20


class TickerFrame(Frame):
    name = "ticker"

    def render(self, now: datetime, state: dict) -> tuple[str, str]:
        # Substitute {gN} glyph placeholders before windowing so each glyph is one
        # column wide in the scroll.
        message = apply_glyph_placeholders(
            (state.get("message") or "").replace("\n", " ")
        )
        step_ms = state.get("scroll_speed_ms") or config.TICK_MS
        step_ms = max(1, int(step_ms))
        # Derive the scroll offset from wall-clock time so each tick advances.
        offset = int(now.timestamp() * 1000) // step_ms
        top = ticker_window(message, offset, width=WIDTH)
        # Single-line ticker: the message scrolls on the top line, bottom blank.
        return top, ""
