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
from .driver import (
    VFDDriver,
    VFDError,
    apply_glyph_placeholders,
    normalize_brightness,
)

# Invalid/unknown brightness values are coerced to this index once (one warning).
_DEFAULT_BRIGHTNESS = 3  # Maximum
_MIN_BRIGHTNESS = 0      # blink's off-phase pulses down to this
from .frames.clock import ClockFrame, clock_time
from .frames.message import MessageFrame
from .renderer import WIDTH, fit_line, render_line, render_lines, ticker_window
from .state import load_state, save_status

# Software scroll: each step redraws ~40 bytes at 9600 baud (~40ms on the wire),
# so a step faster than this floor can't keep up — clamp scroll_speed_ms to it.
SCROLL_FLOOR_MS = 60

# Static frames, keyed by name. "scroll" + "marquee" are handled specially in
# the tick (they need per-row offsets / the hardware ticker), not via a Frame.
FRAMES = {f.name: f for f in (ClockFrame(), MessageFrame())}
DEFAULT_FRAME = "clock"


def _norm_mode(mode) -> str:
    """Legacy mode "ticker" is the old single-line top scroll — now "scroll"."""
    return "scroll" if mode == "ticker" else mode

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
        "last_marquee_text": None,  # last text kicked into the hardware ticker
        "last_marquee_bottom": None,  # last bottom row written in marquee mode
        "marquee_preview_offset": 0,  # software-scroll offset for the status preview
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
    # Force marquee mode to re-init the hardware ticker + re-write the bottom.
    ctx["last_marquee_text"] = None
    ctx["last_marquee_bottom"] = None


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
      - none         -> always show the frame.
      - flash        -> alternate the frame with a real blank (display goes DARK).
      - blink, pulse -> always show the frame; brightness does the animation
                        (see :func:`animation_brightness`), so the text stays up.
    """
    if animation == "flash":
        return ("show", top, bottom) if _phase_on(now_ms, params) else ("blank",)
    return ("show", top, bottom)


# pulse sweeps brightness as a triangle wave through the four levels: each step
# advances one index, so the full up-and-down is 6 steps (0→3→back).
_PULSE_TRIANGLE = (0, 1, 2, 3, 2, 1)
_PULSE_STEP_MS = 200  # default per-step interval -> ~1.2s full triangle


def animation_brightness(
    now_ms: int, animation: str, params: dict, base: int
) -> int:
    """Effective brightness index for this tick.

    - ``blink`` pulses the frame between the chosen level (on-phase) and MIN
      (off-phase) — a 2-state snap, visually distinct from ``flash``'s dark blank.
    - ``pulse`` sweeps the full 0..3 range as a stepped triangle wave (a breathing
      effect); it OVERRIDES the static brightness while active.
    Every other animation just uses the base level.
    """
    if animation == "blink" and not _phase_on(now_ms, params):
        return _MIN_BRIGHTNESS
    if animation == "pulse":
        step_ms = max(1, int(params.get("step_ms", _PULSE_STEP_MS)))
        idx = (now_ms // step_ms) % len(_PULSE_TRIANGLE)
        return _PULSE_TRIANGLE[idx]
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


def _apply_settings(
    driver: VFDDriver,
    state: dict,
    ctx: dict,
    now_ms: int,
    animation: str,
    params: dict,
) -> None:
    """Apply brightness (incl. blink/pulse), hardware-scroll mode, code page.

    Each is change-gated (no redundant writes). An invalid brightness is coerced
    to the default ONCE with a single warning per distinct bad value.
    """
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


def _scroll_offset(now_ms: int, speed_ms, scroll: bool, direction) -> int | None:
    """Per-row software-scroll offset, or None for a static (non-scrolling) row.

    Direction reverses the stepping: "left" advances the offset (text moves left,
    new chars enter from the right); "right" decrements it (text moves right).
    """
    if not scroll:
        return None
    step = max(SCROLL_FLOOR_MS, int(speed_ms or 300))
    raw = now_ms // step
    return -raw if direction == "right" else raw


def _scroll_row(
    state: dict, now: datetime, now_ms: int, which: str, text: str, speed
) -> str:
    """Render one row of mode "scroll" per its content source.

    ``source`` (``scroll_{which}_source``) selects what the row shows:
      - "clock"   -> the live TIME line (HH:MM:SS AM/PM), refreshed each second,
                     statically aligned (no software scroll). (TODO: a date-vs-time
                     sub-choice; defaults to time.)
      - "message" -> ``text`` (this row of the message), which scrolls left/right
                     per ``scroll_{which}`` + ``scroll_dir_{which}`` or sits aligned.
    EXTENSION POINT: a future "news" source renders here the same way.
    """
    source = state.get(f"scroll_{which}_source", "message")
    align = _align(state.get(f"align_{which}"))
    if source == "clock":
        return render_line(clock_time(now), align=align)
    offset = _scroll_offset(
        now_ms, speed, bool(state.get(f"scroll_{which}")),
        state.get(f"scroll_dir_{which}"),
    )
    return render_line(text, align=align, offset=offset)


def render_scroll(state: dict, now_ms: int, now: datetime | None = None) -> tuple[str, str]:
    """Render mode "scroll": each row picks a content SOURCE (message|clock) and,
    for "message", independently scrolls left/right or sits aligned. The flexible,
    news-ready mode. Glyph cells count as one. ``now`` is needed for a clock row."""
    now = now or datetime.now()
    msg = apply_glyph_placeholders(state.get("message") or "")
    if "\n" in msg:
        ltop, _, lbottom = msg.partition("\n")
    else:
        ltop, lbottom = msg, ""
    speed = state.get("scroll_speed_ms", 300)
    return (
        _scroll_row(state, now, now_ms, "top", ltop, speed),
        _scroll_row(state, now, now_ms, "bottom", lbottom, speed),
    )


def _tick_marquee(driver: VFDDriver, state: dict, ctx: dict, now, now_ms: int) -> None:
    """Drive marquee mode: hardware ticker on the top, STATIC bottom row.

    The top is the autonomous hardware ticker (re-kicked only when the text
    changes / after a reset). The bottom is static text only, written with
    ``show_bottom`` (which does NOT disturb a running top scroll) and only when it
    changes. A live clock bottom is impossible here: a bottom write arriving after
    the hardware scroll resumes STOPS the scroll, so clock-bottom was removed —
    SCROLL is the home for a live clock/news ticker. ``marquee_bottom`` is kept
    in the schema for back-compat but ignored (state.py normalizes it to static).

    status.json's top is a SOFTWARE-scrolled approximation that ADVANCES every
    tick (via a per-tick offset counter), so the preview animates even though the
    real hardware speed is fixed and unreadable.
    """
    # Substitute {gN} -> glyph-code byte BEFORE kicking the ticker: the hardware
    # ticker renders user glyphs (codes 0x15-0x1E) in its buffer (bench-confirmed),
    # so the substituted code must reach start_ticker, not the literal "{gN}". The
    # glyphs are already defined this tick (section 3 of tick_once runs first, and
    # a glyph change invalidates last_marquee_text so the ticker re-kicks). The
    # 45-char buffer limit is counted post-substitution (start_ticker truncates
    # after _sanitize, where each glyph code is one byte) — consistent with v0.5.3.
    marquee_text = apply_glyph_placeholders(state.get("marquee_text") or "")
    if marquee_text != ctx["last_marquee_text"]:
        driver.start_ticker(marquee_text)
        ctx["last_marquee_text"] = marquee_text

    # Bottom is static-only (see docstring). marquee_bottom_text, fit + aligned.
    lbottom = apply_glyph_placeholders(state.get("marquee_bottom_text") or "")
    bottom = fit_line(lbottom, align=_align(state.get("align_bottom")))
    if bottom != ctx["last_marquee_bottom"]:
        driver.show_bottom(bottom)
        ctx["last_marquee_bottom"] = bottom

    # Preview approximation: advance a per-tick offset so the windowed top scrolls
    # in the UI regardless of wall-clock timing (it won't match the hardware
    # speed — it just has to MOVE). Uses the SUBSTITUTED text so the preview
    # (which decodes glyph codes via state.glyphs) shows the glyph, not "{gN}".
    ctx["marquee_preview_offset"] += 1
    offset = ctx["marquee_preview_offset"]
    disp_top = ticker_window(marquee_text, offset) if marquee_text else _BLANK_LINE
    _write_status(state, disp_top, bottom, ctx)


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
            # brightness, code-page, glyphs and the marquee ticker from state.json.
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

    mode = _norm_mode(state.get("mode"))
    # Animation is N/A in marquee: the hardware ticker owns the top row, so
    # flash/blink/pulse don't apply meaningfully. Force "none" here so a leftover
    # animation setting carried over from another mode can't affect marquee — one
    # clean behavior, not a special-case scattered through the marquee path.
    animation = "none" if mode == "marquee" else state.get("animation", "none")
    params = state.get("animation_params") or {}

    # MARQUEE: hardware ticker on the top + independent bottom — its own path.
    # (When blank, fall through to the normal blank handling below.)
    if mode == "marquee" and not state.get("blank"):
        _apply_settings(driver, state, ctx, now_ms, animation, params)  # forced none
        _tick_marquee(driver, state, ctx, now, now_ms)
        return

    # Not in marquee this tick: clear the marquee caches so re-entering it
    # re-kicks the hardware ticker and re-writes the bottom.
    ctx["last_marquee_text"] = None
    ctx["last_marquee_bottom"] = None

    # 4. frame + animation. Compute the frame first, so the brightness step below
    # can apply blink's brightness PULSE for this tick.
    if state.get("blank"):
        top, bottom = _BLANK_LINE, _BLANK_LINE
        emit: tuple = ("blank",)
    else:
        if mode == "scroll":
            top, bottom = render_scroll(state, now_ms, now)
        else:
            frame = FRAMES.get(mode, FRAMES[DEFAULT_FRAME])
            top, bottom = render_lines(
                *frame.render(now, state),
                top_align=_align(state.get("align_top")),
                bottom_align=_align(state.get("align_bottom")),
            )
        emit = resolve_emit(now_ms, animation, params, top, bottom)

    # 5. display settings (brightness incl. blink/pulse, scroll mode, code page).
    _apply_settings(driver, state, ctx, now_ms, animation, params)

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
