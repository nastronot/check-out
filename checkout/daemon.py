"""check-out daemon — the sole owner of the serial port.

Each tick it reads ``state.json``, renders the active frame, and emits EXACTLY
ONE ``show()`` frame (the known-good byte sequence) — never zero, never two. A
single self-contained frame per tick is what keeps the display from scrolling:
two writes in a tick, or a partial write, would advance past the 40th cell and
scroll. It reconnects with backoff if the USB adapter drops, and blanks the
display on a clean shutdown.

Entrypoint::

    python -m checkout.daemon [--dry-run]
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime

from . import config
from .driver import VFDDriver, VFDError
from .frames.clock import ClockFrame
from .renderer import render_lines
from .state import load_state

# Registry of available frames, keyed by name. New frames drop in here.
FRAMES = {f.name: f for f in (ClockFrame(),)}
DEFAULT_FRAME = "clock"

# Boot banner shown briefly at startup.
BANNER_TOP = "CHECK-OUT"
BANNER_BOTTOM = "BOOTING"
BANNER_SECONDS = 1.0

# Set by signal handlers to request a clean shutdown.
_stop = False


def log(msg: str) -> None:
    """Timestamped line to stdout (container-friendly)."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _handle_signal(signum, frame) -> None:
    global _stop
    _stop = True


def open_driver(dry_run: bool) -> VFDDriver | None:
    """Open the driver, retrying with growing backoff until it succeeds.

    Returns None if a shutdown is requested before a connection is made.
    """
    backoff = config.RECONNECT_BACKOFF_START
    while not _stop:
        try:
            driver = VFDDriver(dry_run=dry_run)
            log(f"serial open on {driver.port} @ {driver.baud}")
            return driver
        except VFDError as exc:
            log(f"open failed: {exc}; retrying in {backoff:.0f}s")
            time.sleep(backoff)
            backoff = min(backoff * 2, config.RECONNECT_BACKOFF_MAX)
    return None


def show_banner(driver: VFDDriver) -> None:
    top, bottom = render_lines(BANNER_TOP, BANNER_BOTTOM)
    driver.clear()
    driver.show(top, bottom)
    time.sleep(BANNER_SECONDS)


def run(dry_run: bool = False) -> int:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    driver = open_driver(dry_run)
    if driver is None:
        return 0

    tick = config.TICK_MS / 1000.0
    blanked = False

    try:
        show_banner(driver)
        log("entering loop")
        while not _stop:
            state = load_state()
            try:
                if state.get("blank"):
                    # Blank is latched: blank once, then emit nothing until the
                    # state changes (re-clearing every tick would flicker).
                    if not blanked:
                        driver.blank()
                        blanked = True
                        log("display blanked")
                else:
                    if blanked:
                        blanked = False
                        log("display resumed")
                    frame = FRAMES.get(state.get("mode"), FRAMES[DEFAULT_FRAME])
                    top, bottom = frame.render(datetime.now(), state)
                    top, bottom = render_lines(top, bottom)
                    # Exactly ONE complete frame per tick. The frame is the full
                    # known-good sequence and is idempotent, so redrawing every
                    # tick is safe; emitting a second write here would scroll.
                    driver.show(top, bottom)
            except VFDError as exc:
                log(f"serial error: {exc}; reconnecting")
                driver.close()
                reconnected = open_driver(dry_run)
                if reconnected is None:
                    break
                driver = reconnected
                blanked = False
                continue
            time.sleep(tick)
    finally:
        log("shutting down: blanking display")
        try:
            # blank() = 0x1F then 0x14, so the exit screen is dark with no
            # lingering cursor block (a bare clear() would re-enable the cursor).
            driver.blank()
        except VFDError:
            pass
        driver.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="checkout.daemon", description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print outgoing bytes as hex instead of opening the serial port",
    )
    args = parser.parse_args(argv)
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
