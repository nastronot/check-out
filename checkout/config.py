"""Runtime configuration for check-out.

All values default to bench-verified hardware settings and can be overridden via
environment variables so the dev machine and the deployment host (arda) can
differ without code changes.

Env overrides:
  CHECKOUT_PORT        serial device          (default /dev/ttyUSB0)
  CHECKOUT_BAUD        serial baud rate        (default 9600)
  CHECKOUT_TICK_MS     daemon loop period ms   (default 250)
  CHECKOUT_STATE_PATH  path to state.json      (default ./state.json)
"""

from __future__ import annotations

import os

# --- Serial / display --------------------------------------------------------
# WRITE-ONLY port. 9600 8N1. Never read from it.
PORT: str = os.environ.get("CHECKOUT_PORT", "/dev/ttyUSB0")
BAUD: int = int(os.environ.get("CHECKOUT_BAUD", "9600"))

# Physical display geometry (2 lines x 20 chars).
COLS: int = 20
ROWS: int = 2

# --- Daemon timing -----------------------------------------------------------
# Legacy per-tick sleep (kept for --once / back-compat). The main loop now runs
# at a single FAST rate (LOOP_HZ) and emit-diffs to the serial port, so looping
# fast is free for static modes and gives spectrum its frame rate (see daemon).
TICK_MS: int = int(os.environ.get("CHECKOUT_TICK_MS", "250"))

# Single fast loop rate. ~30Hz (target ~33ms/iter): emit-diffing decouples loop
# rate from serial-write rate, so normal modes only touch the port on change
# while spectrum can render ~21fps (the 9600-baud full-frame ceiling).
LOOP_HZ: float = float(os.environ.get("CHECKOUT_LOOP_HZ", "30"))

# status.json is THROTTLED to this rate (not every loop iteration) so the mirror
# file isn't churned 30x/s — still well under the 5s liveness staleness window.
STATUS_HZ: float = float(os.environ.get("CHECKOUT_STATUS_HZ", "6"))

# The unix datagram socket the audioviz process streams bar heights to. The
# daemon binds/receives; audioviz connects/sends (newest-frame-wins). Defaults
# under $XDG_RUNTIME_DIR when set, else /tmp.
SPECTRUM_SOCKET: str = os.environ.get(
    "CHECKOUT_SPECTRUM_SOCK",
    os.path.join(
        os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "checkout-spectrum.sock"
    ),
)

# Where audioviz writes the enumerated capture devices for the UI selector.
DEVICES_PATH: str = os.environ.get("CHECKOUT_DEVICES_PATH", "./devices.json")

# Reconnect backoff (seconds): start small, grow to a cap.
RECONNECT_BACKOFF_START: float = 1.0
RECONNECT_BACKOFF_MAX: float = 5.0

# --- State -------------------------------------------------------------------
# STATE_PATH: web UI (Phase 2) WRITES this; daemon reads it each tick.
# STATUS_PATH: daemon WRITES this each tick (sole writer); web UI reads it to
# mirror the real display + daemon health. The two files keep the write
# ownership one-directional, so there are no races between daemon and web.
STATE_PATH: str = os.environ.get("CHECKOUT_STATE_PATH", "./state.json")
STATUS_PATH: str = os.environ.get("CHECKOUT_STATUS_PATH", "./status.json")
# LIBRARY_PATH: web-owned store of saved messages + glyphs. The daemon NEVER
# reads it; recalling a library item writes state.json via the existing path.
LIBRARY_PATH: str = os.environ.get("CHECKOUT_LIBRARY_PATH", "./library.json")

# --- Frame rotation ----------------------------------------------------------
# Single frame this phase; rotation lands in Phase 3.
ROTATE: bool = False

# --- Debug -------------------------------------------------------------------
# CHECKOUT_DEBUG_TX=1 logs every actual serial write as hex (live or dry-run),
# so the on-the-wire byte stream can be verified against the known-good frame.
DEBUG_TX: bool = os.environ.get("CHECKOUT_DEBUG_TX") == "1"
