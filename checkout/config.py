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
TICK_MS: int = int(os.environ.get("CHECKOUT_TICK_MS", "250"))

# Reconnect backoff (seconds): start small, grow to a cap.
RECONNECT_BACKOFF_START: float = 1.0
RECONNECT_BACKOFF_MAX: float = 5.0

# --- State -------------------------------------------------------------------
STATE_PATH: str = os.environ.get("CHECKOUT_STATE_PATH", "./state.json")

# --- Frame rotation ----------------------------------------------------------
# Single frame this phase; rotation lands in Phase 3.
ROTATE: bool = False

# --- Debug -------------------------------------------------------------------
# CHECKOUT_DEBUG_TX=1 logs every actual serial write as hex (live or dry-run),
# so the on-the-wire byte stream can be verified against the known-good frame.
DEBUG_TX: bool = os.environ.get("CHECKOUT_DEBUG_TX") == "1"
