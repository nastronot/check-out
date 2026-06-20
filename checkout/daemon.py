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
from .driver import VFDDriver, VFDError, normalize_brightness

# Invalid/unknown brightness values are coerced to this index once (one warning).
_DEFAULT_BRIGHTNESS = 3  # Maximum
_MIN_BRIGHTNESS = 0      # blink's off-phase pulses down to this
from .frames.clock import ClockFrame
from .frames.message import MessageFrame
from .frames.ticker import TickerFrame
from .renderer import WIDTH, render_lines
from .state import load_state, save_status

# Registry of available frames, keyed by name. New frames drop in here.
FRAMES = {f.name: f for f in (ClockFrame(), MessageFrame(), TickerFrame())}
DEFAULT_FRAME = "clock"

_ALIGNMENTS = ("left", "center", "right")


def _align(value) -> str:
    """Coerce a per-line alignment to a valid value (default 'center')."""
    return value if value in _ALIGNMENTS else "center"

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
        "last_emit": None,         # last thing shown to the DISPLAY (gates serial writes)
        "heartbeat": 0,            # monotonic per-tick counter (liveness, not content)
        "bad_brightness": None,    # last invalid brightness warned about (dedupe)
    }


def _invalidate_caches(ctx: dict) -> None:
    """Force display settings + glyphs + the frame to be re-applied.

    Used after any operation that may reset the display's internal state
    (self_test, reset, define_character, reconnect, initialize): the cached
    "already applied" values are cleared so brightness, vertical-scroll mode,
    code-page, user glyphs and the frame are all re-sent from state.json on the
    next tick. Without this the daemon's cache desyncs from the hardware — e.g.
    a self-test silently turns vertical scroll back ON, but the cache still says
    "scroll disabled", so 0x11 is never re-sent and the display keeps scrolling.
    """
    ctx["last_brightness"] = None
    ctx["last_scroll"] = None
    ctx["last_code_page"] = None
    ctx["last_glyphs"] = None
    ctx["last_emit"] = None


# --- command processing ------------------------------------------------------
def _apply_glyphs(driver: VFDDriver, glyphs: dict) -> None:
    """Define each user glyph on the display (skipping malformed entries)."""
    for key in sorted(glyphs, key=lambda k: int(k)):
        try:
            driver.define_character(int(key), glyphs[key])
        except (ValueError, TypeError) as exc:
            log(f"skipping bad glyph {key!r}: {exc}")


def _run_command(driver: VFDDriver, command: dict, state: dict, ctx: dict) -> bool:
    """Execute a one-shot command. All actions are idempotent.

    Returns True if the command reset the display's internal state (so the
    caller skips the rest of this tick and re-applies settings next tick).
    """
    action = command.get("action")
    if action == "self_test":
        log("command: self_test")
        driver.self_test()       # re-initializes the display itself
        _invalidate_caches(ctx)
        return True
    elif action == "reset":
        log("command: reset")
        driver.reset()           # re-initializes the display itself
        _invalidate_caches(ctx)
        return True
    elif action == "redefine_glyphs":
        log("command: redefine_glyphs")
        glyphs = state.get("glyphs") or {}
        _apply_glyphs(driver, glyphs)
        driver.initialize()      # defining glyphs may reset the display
        _invalidate_caches(ctx)
        ctx["last_glyphs"] = dict(glyphs)  # just defined them; don't re-define
        return True
    else:
        log(f"command: unknown action {action!r}, ignoring")
        return False


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
    """Decide what frame to put on the glass given the animation phase.

    Returns an emit tuple: ``("show", top, bottom)`` or ``("blank",)``.
      - none  -> always show the frame.
      - flash -> alternate the frame with a real blank (display goes fully DARK).
      - blink -> always shows the frame; it PULSES via brightness instead of
                 blanking (see :func:`animation_brightness`), so the text stays
                 readable and it reads clearly different from flash.
    """
    if animation == "flash":
        return ("show", top, bottom) if _phase_on(now_ms, params) else ("blank",)
    return ("show", top, bottom)


def animation_brightness(
    now_ms: int, animation: str, params: dict, base: int
) -> int:
    """Effective brightness index for this tick.

    ``blink`` pulses the frame between the chosen level (on-phase) and MIN
    (off-phase), so the display dims and brightens rather than disappearing —
    visually distinct from ``flash``'s hard dark blank. Every other animation
    just uses the base level.
    """
    if animation == "blink" and not _phase_on(now_ms, params):
        return _MIN_BRIGHTNESS
    return base


def _apply_emit(driver: VFDDriver, emit: tuple) -> None:
    if emit[0] == "blank":
        driver.blank()
    else:
        driver.show(emit[1], emit[2])


# --- the tick ----------------------------------------------------------------
def _write_status(state: dict, top: str, bottom: str, ctx: dict) -> None:
    """Mirror the current display state to status.json — a HEARTBEAT every tick.

    Written unconditionally (with a fresh ``updated_at`` and a monotonic
    ``heartbeat``) even when top/bottom are unchanged, so the UI's liveness check
    (status freshness < 5s) reads ALIVE in static modes like a fixed message.
    This is independent of the serial-port emit-diffing — the DISPLAY is only
    re-written when the frame actually changes (see ``last_emit``); only this
    small status file is refreshed each tick.
    """
    ctx["heartbeat"] += 1
    save_status(
        {
            "alive": True,
            "mode": state.get("mode"),
            "top": top,
            "bottom": bottom,
            # The APPLIED brightness index 0..3 (set in section 4 this tick), so
            # the preview reflects the real level, not a raw/legacy state value.
            "brightness": ctx["last_brightness"],
            "blank": bool(state.get("blank")),
            "scroll": bool(state.get("scroll")),
            "last_command_id": ctx["last_command_id"],
            "heartbeat": ctx["heartbeat"],
        }
    )


def tick_once(driver: VFDDriver, state: dict, ctx: dict, now: datetime | None = None) -> None:
    """Drive the display one step toward ``state`` and mirror status.json."""
    now = now or datetime.now()
    now_ms = int(now.timestamp() * 1000)

    # 1/2. one-shot command (nonce processed exactly once).
    command = state.get("command") or {}
    command_id = command.get("id")
    if command_id is not None and command_id != ctx["last_command_id"]:
        did_reset = _run_command(driver, command, state, ctx)
        ctx["last_command_id"] = command_id
        if did_reset:
            # A self-test/reset can swallow writes sent immediately after it
            # (the panel is still re-initializing). Skip the rest of this tick;
            # caches were invalidated, so the NEXT tick re-applies scroll mode,
            # brightness, code-page and glyphs from state.json — the display
            # can't stay stuck in vertical-scroll (or any stale mode) afterward.
            return

    # 3. user glyphs (re-define on change; defining may reset the display, so
    # re-init + re-apply afterward — but only when there are glyphs to define).
    glyphs = state.get("glyphs") or {}
    if glyphs != ctx["last_glyphs"]:
        if glyphs:
            _apply_glyphs(driver, glyphs)
            driver.initialize()
            _invalidate_caches(ctx)
        ctx["last_glyphs"] = dict(glyphs)

    animation = state.get("animation", "none")
    params = state.get("animation_params") or {}

    # 4. frame + animation. Compute the frame first, so the brightness step below
    # can apply blink's brightness PULSE for this tick.
    if state.get("blank"):
        top, bottom = _BLANK_LINE, _BLANK_LINE
        emit: tuple = ("blank",)
    else:
        frame = FRAMES.get(state.get("mode"), FRAMES[DEFAULT_FRAME])
        ltop, lbottom = frame.render(now, state)
        top, bottom = render_lines(
            ltop,
            lbottom,
            top_align=_align(state.get("align_top")),
            bottom_align=_align(state.get("align_bottom")),
        )
        emit = resolve_emit(now_ms, animation, params, top, bottom)

    # 5. display settings (avoid redundant writes). Brightness is normalized to
    # the canonical index 0..3 (legacy "dim"/"bright" still accepted); an invalid
    # value is coerced to a safe default ONCE (single warning per distinct value).
    # blink folds in here as a per-tick brightness pulse (no frame re-draw needed).
    raw_brightness = state.get("brightness", _DEFAULT_BRIGHTNESS)
    try:
        base_brightness = normalize_brightness(raw_brightness)
        ctx["bad_brightness"] = None
    except ValueError:
        base_brightness = _DEFAULT_BRIGHTNESS
        if ctx["bad_brightness"] != raw_brightness:
            log(f"invalid brightness {raw_brightness!r}; using {base_brightness}")
            ctx["bad_brightness"] = raw_brightness
    brightness = animation_brightness(now_ms, animation, params, base_brightness)
    if brightness != ctx["last_brightness"]:
        driver.set_brightness(brightness)
        ctx["last_brightness"] = brightness

    scroll = bool(state.get("scroll", False))
    if scroll != ctx["last_scroll"]:
        driver.set_vertical_scroll(scroll)
        ctx["last_scroll"] = scroll

    code_page = state.get("code_page", 0)
    if code_page != ctx["last_code_page"]:
        try:
            driver.select_code_page(code_page)  # name or int 0..11
        except (ValueError, TypeError) as exc:
            log(f"bad code_page {code_page!r}: {exc}")
        ctx["last_code_page"] = code_page

    # 6. push the frame to the glass (only when it changes).
    if emit != ctx["last_emit"]:
        _apply_emit(driver, emit)
        ctx["last_emit"] = emit

    # 7. mirror status — report what's ACTUALLY on the glass this tick (blank
    # during flash's dark phase) so the preview animates; brightness already
    # reflects blink's pulse via ctx["last_brightness"].
    if emit[0] == "blank":
        disp_top, disp_bottom = _BLANK_LINE, _BLANK_LINE
    else:
        disp_top, disp_bottom = emit[1], emit[2]
    _write_status(state, disp_top, disp_bottom, ctx)


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
                # Fresh display (open() re-initialized it): re-apply everything —
                # settings AND glyphs — on the next tick.
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
