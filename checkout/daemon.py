"""check-out daemon — the sole owner of the serial port.

Each tick it reads ``state.json`` (written by the web UI), drives the display to
match, and writes ``status.json`` (a mirror of what is on the glass plus daemon
health). The daemon is the ONLY writer of the serial port and of status.json;
the web UI is the only writer of state.json. That one-directional ownership is
what keeps the two from racing.

A tick:
  1. load_state()
  2. process a one-shot command (self_test / reset / redefine_glyphs) if its
     nonce id is new (idempotent, so re-running once on restart is safe)
  3. (re)define user glyphs if they changed
  4. apply brightness / scroll-mode / code-page if changed (no redundant writes)
  5. render the active frame (mode), or blank
  6. apply the animation (none / flash / blink)
  7. write status.json (on change)

The display is initialized once on open (extended mode + scroll off), so a full
40-cell frame holds with no scroll. The daemon reconnects with backoff if the
USB adapter drops (re-initializing on reopen) and blanks the display on a clean
shutdown.

Entrypoint::

    python -m checkout.daemon [--dry-run] [--once]
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
from .frames.message import MessageFrame
from .frames.ticker import TickerFrame
from .renderer import WIDTH, render_lines
from .state import load_state, save_status

# Registry of available frames, keyed by name. New frames drop in here.
FRAMES = {f.name: f for f in (ClockFrame(), MessageFrame(), TickerFrame())}
DEFAULT_FRAME = "clock"

# Boot banner shown briefly at startup.
BANNER_TOP = "CHECK-OUT"
BANNER_BOTTOM = "BOOTING"
BANNER_SECONDS = 1.0

_BLANK_LINE = " " * WIDTH

# Set by signal handlers to request a clean shutdown.
_stop = False


def log(msg: str) -> None:
    """Timestamped line to stdout (container-friendly)."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _handle_signal(signum, frame) -> None:
    global _stop
    _stop = True


# --- per-run mutable context -------------------------------------------------
def _new_ctx() -> dict:
    """In-memory state carried across ticks (never persisted)."""
    return {
        "last_command_id": None,   # nonce of the last processed command
        "last_glyphs": None,       # last applied glyph map (to detect changes)
        "last_brightness": None,   # last applied display settings (avoid re-writes)
        "last_scroll": None,
        "last_code_page": None,
        "last_emit": None,         # last thing shown (avoid redundant frames)
        "last_status": None,       # last status.json payload (avoid redundant writes)
    }


def _invalidate_caches(ctx: dict) -> None:
    """Force display settings + the frame to be re-applied on this tick.

    Used after any operation that may reset the display (self_test, reset,
    define_character, reconnect): the cached "already applied" values are
    cleared so brightness/scroll/code-page and the frame are written again.
    """
    ctx["last_brightness"] = None
    ctx["last_scroll"] = None
    ctx["last_code_page"] = None
    ctx["last_emit"] = None


# --- command processing ------------------------------------------------------
def _apply_glyphs(driver: VFDDriver, glyphs: dict) -> None:
    """Define each user glyph on the display (skipping malformed entries)."""
    for key in sorted(glyphs, key=lambda k: int(k)):
        try:
            driver.define_character(int(key), glyphs[key])
        except (ValueError, TypeError) as exc:
            log(f"skipping bad glyph {key!r}: {exc}")


def _run_command(driver: VFDDriver, command: dict, state: dict, ctx: dict) -> None:
    """Execute a one-shot command. All actions are idempotent."""
    action = command.get("action")
    if action == "self_test":
        log("command: self_test")
        driver.self_test()       # re-initializes the display itself
        _invalidate_caches(ctx)
    elif action == "reset":
        log("command: reset")
        driver.reset()           # re-initializes the display itself
        _invalidate_caches(ctx)
    elif action == "redefine_glyphs":
        log("command: redefine_glyphs")
        glyphs = state.get("glyphs") or {}
        _apply_glyphs(driver, glyphs)
        ctx["last_glyphs"] = dict(glyphs)
        driver.initialize()      # defining glyphs may reset the display
        _invalidate_caches(ctx)
    else:
        log(f"command: unknown action {action!r}, ignoring")


# --- animation ---------------------------------------------------------------
def _phase_on(now_ms: int, params: dict) -> bool:
    """True during the ON part of an on/off animation cycle."""
    on_ms = int(params.get("on_ms", 500))
    off_ms = int(params.get("off_ms", 500))
    cycle = on_ms + off_ms
    if cycle <= 0:
        return True
    return (now_ms % cycle) < on_ms


def resolve_emit(
    now_ms: int, animation: str, params: dict, top: str, bottom: str
) -> tuple:
    """Decide what to put on the glass given the animation phase.

    Returns an emit tuple: ``("show", top, bottom)`` or ``("blank",)``.
      - none  -> always show the frame.
      - flash -> alternate the frame with a real blank (display goes dark).
      - blink -> alternate the frame with blank LINES (display stays on).
    """
    if animation == "flash":
        return ("show", top, bottom) if _phase_on(now_ms, params) else ("blank",)
    if animation == "blink":
        if _phase_on(now_ms, params):
            return ("show", top, bottom)
        return ("show", _BLANK_LINE, _BLANK_LINE)
    return ("show", top, bottom)


def _apply_emit(driver: VFDDriver, emit: tuple) -> None:
    if emit[0] == "blank":
        driver.blank()
    else:
        driver.show(emit[1], emit[2])


# --- the tick ----------------------------------------------------------------
def _write_status(state: dict, top: str, bottom: str, ctx: dict) -> None:
    """Mirror the current display state to status.json (only when it changes)."""
    status = {
        "alive": True,
        "mode": state.get("mode"),
        "top": top,
        "bottom": bottom,
        "brightness": state.get("brightness"),
        "blank": bool(state.get("blank")),
        "scroll": bool(state.get("scroll")),
        "last_command_id": ctx["last_command_id"],
    }
    if status != ctx["last_status"]:
        save_status(status)
        ctx["last_status"] = status


def tick_once(driver: VFDDriver, state: dict, ctx: dict, now: datetime | None = None) -> None:
    """Drive the display one step toward ``state`` and mirror status.json."""
    now = now or datetime.now()
    now_ms = int(now.timestamp() * 1000)

    # 1/2. one-shot command (nonce processed exactly once).
    command = state.get("command") or {}
    command_id = command.get("id")
    if command_id is not None and command_id != ctx["last_command_id"]:
        _run_command(driver, command, state, ctx)
        ctx["last_command_id"] = command_id

    # 3. user glyphs (re-define on change; defining may reset the display, so
    # re-init + re-apply afterward — but only when there are glyphs to define).
    glyphs = state.get("glyphs") or {}
    if glyphs != ctx["last_glyphs"]:
        if glyphs:
            _apply_glyphs(driver, glyphs)
            driver.initialize()
            _invalidate_caches(ctx)
        ctx["last_glyphs"] = dict(glyphs)

    # 4. display settings (avoid redundant writes).
    brightness = state.get("brightness", "dim")
    if brightness != ctx["last_brightness"]:
        try:
            driver.set_brightness(brightness)
        except ValueError as exc:
            log(f"bad brightness {brightness!r}: {exc}")
        ctx["last_brightness"] = brightness

    scroll = bool(state.get("scroll", False))
    if scroll != ctx["last_scroll"]:
        driver.set_vertical_scroll(scroll)
        ctx["last_scroll"] = scroll

    code_page = state.get("code_page", 0)
    if code_page != ctx["last_code_page"]:
        try:
            driver.select_code_page(int(code_page))
        except (ValueError, TypeError) as exc:
            log(f"bad code_page {code_page!r}: {exc}")
        ctx["last_code_page"] = code_page

    # 5/6. frame + animation.
    if state.get("blank"):
        top, bottom = _BLANK_LINE, _BLANK_LINE
        emit: tuple = ("blank",)
    else:
        frame = FRAMES.get(state.get("mode"), FRAMES[DEFAULT_FRAME])
        top, bottom = render_lines(*frame.render(now, state))
        emit = resolve_emit(
            now_ms,
            state.get("animation", "none"),
            state.get("animation_params") or {},
            top,
            bottom,
        )

    if emit != ctx["last_emit"]:
        _apply_emit(driver, emit)
        ctx["last_emit"] = emit

    # 7. mirror status.
    _write_status(state, top, bottom, ctx)


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


def run(dry_run: bool = False, once: bool = False) -> int:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    driver = open_driver(dry_run)
    if driver is None:
        return 0

    ctx = _new_ctx()

    if once:
        # Single-frame mode for hardware testing: emit exactly one tick and exit
        # WITHOUT blanking, so the frame stays on screen for inspection.
        try:
            tick_once(driver, load_state(), ctx)
            log("emitted one frame (--once)")
        except VFDError as exc:
            log(f"serial error: {exc}")
        finally:
            driver.close()
        return 0

    tick = config.TICK_MS / 1000.0

    try:
        show_banner(driver)
        log("entering loop")
        while not _stop:
            state = load_state()
            try:
                tick_once(driver, state, ctx)
            except VFDError as exc:
                log(f"serial error: {exc}; reconnecting")
                driver.close()
                reconnected = open_driver(dry_run)
                if reconnected is None:
                    break
                driver = reconnected
                # Fresh display: re-apply everything (glyphs included) next tick.
                ctx["last_glyphs"] = None
                _invalidate_caches(ctx)
                continue
            time.sleep(tick)
    finally:
        log("shutting down: blanking display")
        try:
            # blank() = init sequence + cursor-off, so the exit screen is dark
            # with no lingering cursor block and never left in scroll mode.
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
