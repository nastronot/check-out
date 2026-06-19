"""Atomic JSON state shared between the daemon and (later) the web UI.

The daemon reads this file every tick; the Phase 2 web UI will be the writer.
Writes are atomic (temp file in the same dir + ``os.replace``) so a reader never
sees a half-written file. Missing or corrupt files fall back to defaults.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone

from . import config


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def defaults() -> dict:
    """A fresh state dict with default values."""
    return {
        "mode": "clock",
        "message": "",
        "brightness": 3,
        "blank": False,
        "updated_at": _now_iso(),
    }


def _path() -> str:
    # Read from config at call time so env overrides / tests take effect.
    return config.STATE_PATH


def save_state(state: dict) -> None:
    """Atomically write ``state`` to the state file.

    Stamps ``updated_at`` at write time, serializes to a temp file in the same
    directory, then ``os.replace``s it over the target so the swap is atomic and
    no partial file is ever observable.
    """
    path = _path()
    state = {**state, "updated_at": _now_iso()}
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        # Never leave the temp file behind on failure.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_state() -> dict:
    """Load state from disk, repairing to defaults if missing or corrupt.

    Returned dict always contains every default key (missing keys are filled),
    so callers can index without guarding.
    """
    path = _path()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("state root is not an object")
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        state = defaults()
        save_state(state)
        return state
    # Fill any missing keys from defaults without clobbering present values.
    return {**defaults(), **data}
