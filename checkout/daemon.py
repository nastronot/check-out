"""check-out daemon — the sole owner of the serial port.

Each tick it reads ``state.json``, renders the active frame, and emits EXACTLY
ONE ``show()`` frame (the known-good byte sequence). The display is initialized
once on open (extended mode + vertical scroll off), so a full 40-cell frame
holds in place with no scroll. It reconnects with backoff if the USB adapter
drops (re-running the init sequence on reopen), and blanks the display on a
clean shutdown.

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
    # show() overwrites all 40 cells in place; the display was initialized
    # (extended mode + scroll off) on open, so a full frame holds without scroll.
    top, bottom = render_lines(BANNER_TOP, BANNER_BOTTOM)
    driver.show(top, bottom)
    time.sleep(BANNER_SECONDS)


def render_active(state: dict) -> tuple[str, str] | None:
    """Render the active frame for ``state``, or None if the display is blank."""
    if state.get("blank"):
        return None
    frame = FRAMES.get(state.get("mode"), FRAMES[DEFAULT_FRAME])
    top, bottom = frame.render(datetime.now(), state)
    return render_lines(top, bottom)


def run(dry_run: bool = False, once: bool = False) -> int:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    driver = open_driver(dry_run)
    if driver is None:
        return 0

    if once:
        # Single-frame mode for hardware testing: emit exactly one frame and
        # exit WITHOUT blanking, so the frame stays on screen for inspection.
        try:
            lines = render_active(load_state())
            if lines is None:
                driver.blank()
            else:
                driver.show(*lines)
            log("emitted one frame (--once)")
        except VFDError as exc:
            log(f"serial error: {exc}")
        finally:
            driver.close()
        return 0

    tick = config.TICK_MS / 1000.0
    blanked = False

    try:
        show_banner(driver)
        log("entering loop")
        while not _stop:
            state = load_state()
            try:
                lines = render_active(state)
                if lines is None:
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
                    # Exactly ONE complete frame per tick. The frame is the full
                    # known-good sequence and is idempotent (each show()
                    # repositions to 0x00), so redrawing every tick is safe.
                    driver.show(*lines)
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
    parser.add_argument(
        "--once",
        action="store_true",
        help="emit exactly one frame then exit (no banner/loop); leaves it on screen",
    )
    args = parser.parse_args(argv)
    return run(dry_run=args.dry_run, once=args.once)


if __name__ == "__main__":
    sys.exit(main())
