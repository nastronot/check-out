"""TickerFrame — horizontally scroll a long message across the top line.

This is a SOFTWARE scroll (a moving window over the text), independent of the
display's hardware vertical-scroll mode (0x11/0x12). The window advances one
column every ``scroll_speed_ms`` of wall-clock time, looping with a gap so the
end and start of the message don't run together. The frame is stateless: the
offset is derived from ``now`` and the speed, so it advances on its own each tick.
"""

from __future__ import annotations

from datetime import datetime

from .. import config
from ..renderer import ticker_window
from .base import Frame

WIDTH = config.COLS  # 20


class TickerFrame(Frame):
    name = "ticker"

    def render(self, now: datetime, state: dict) -> tuple[str, str]:
        message = (state.get("message") or "").replace("\n", " ")
        step_ms = state.get("scroll_speed_ms") or config.TICK_MS
        step_ms = max(1, int(step_ms))
        # Derive the scroll offset from wall-clock time so each tick advances.
        offset = int(now.timestamp() * 1000) // step_ms
        top = ticker_window(message, offset, width=WIDTH)
        # Single-line ticker: the message scrolls on the top line, bottom blank.
        return top, ""
