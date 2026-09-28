"""Which driver class drives this machine's display (config.DISPLAY)."""

from __future__ import annotations

from . import config
from .driver import VFDDriver
from .driver_epson import EpsonDriver

DRIVERS = {"ibm": VFDDriver, "hp": EpsonDriver}


def driver_class(name: str | None = None) -> type:
    raw = config.DISPLAY if name is None else name
    try:
        return DRIVERS[raw.strip().lower()]
    except KeyError:
        raise ValueError(
            f"unknown CHECKOUT_DISPLAY {raw!r}; valid: {', '.join(sorted(DRIVERS))}"
        ) from None


def make_driver(dry_run: bool):
    return driver_class()(dry_run=dry_run)
