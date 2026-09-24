"""The Frame interface.

A frame is a small, stateless renderer: given the current time and the shared
state dict, it returns *logical* (top, bottom) strings. These may be shorter
than 20 chars — the renderer fits/centers them before they reach the driver.
New frames just subclass this and register in ``daemon.FRAMES``.
"""

from __future__ import annotations

import abc
from datetime import datetime


class Frame(abc.ABC):
    """Base class for display frames."""

    #: Stable identifier matched against ``state["mode"]``.
    name: str = "frame"

    #: A fixed alignment for both lines, or None to use the state's
    #: ``align_top`` / ``align_bottom`` (the Justify control).
    align: str | None = None

    @abc.abstractmethod
    def render(self, now: datetime, state: dict) -> tuple[str, str]:
        """Return logical (top, bottom) strings for the given time/state."""
        raise NotImplementedError

    def brightness(self, now: datetime, state: dict, base: int) -> int | None:
        """A brightness level (0..3) this frame wants right now, overriding the
        animation; None = no opinion (the default). ``base`` is the level the
        user set, for effects that return to it."""
        return None
