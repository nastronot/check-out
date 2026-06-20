"""Atomic JSON state shared between the daemon and the web UI.

Two files, one-directional ownership (no races):

- ``state.json`` (:data:`config.STATE_PATH`) — the **web UI writes**, the daemon
  reads each tick. The desired display state (mode, message, animation, …).
- ``status.json`` (:data:`config.STATUS_PATH`) — the **daemon writes** (sole
  writer), the web UI reads. A mirror of what is actually on the glass plus
  daemon health.

Writes are atomic (temp file in the same dir + ``os.replace``) so a reader never
sees a half-written file. Missing or corrupt state falls back to defaults, and
partial writes are backfilled key-by-key so the daemon never breaks on a state
file that only sets some fields.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone

from . import config
from .driver import normalize_brightness

# Default brightness index (3 = Maximum) — bright out of the box.
_DEFAULT_BRIGHTNESS = 3


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def defaults() -> dict:
    """A fresh state dict with every key at its default value."""
    return {
        "mode": "clock",                 # "clock" | "message" | "ticker"
        "message": "",                   # text for message / ticker modes
        "align_top": "center",           # "left" | "center" | "right" — line 1
        "align_bottom": "center",        # "left" | "center" | "right" — line 2
        "brightness": _DEFAULT_BRIGHTNESS,  # int 0..3 (0 Min..3 Max)
        "blank": False,                  # blank the display entirely
        "scroll": False,                 # hardware vertical-scroll MODE (0x11/0x12)
        "code_page": 0,                  # 0..11
        "scroll_speed_ms": 300,          # ticker software-scroll step
        "animation": "none",             # "none" | "flash" | "blink"
        "animation_params": {"on_ms": 500, "off_ms": 500},
        # {"0": [r0..r6], ... "8": [...]} optional 5x7 user glyphs. Each row is an
        # int whose LOW 5 bits are columns 1..5 (bit0=col1 ... bit4=col5) — the
        # editor-natural convention; the driver translates to the wire format
        # (<<3). Place a glyph in a message with the {gN} placeholder.
        "glyphs": {},
        "command": {"id": None, "action": None, "args": {}},
        "updated_at": _now_iso(),
    }


# Keys whose defaults are dicts: a partial write of these should be MERGED with
# the default (so e.g. {"command": {"id": "x"}} keeps a default action/args)
# rather than wholesale-replaced. ``glyphs`` is intentionally NOT here — it is a
# user-owned map and a write replaces it entirely.
_NESTED_DEFAULTS = ("animation_params", "command")


def _backfill(data: dict) -> dict:
    """Return ``data`` with every default key present (recursively for nested)."""
    base = defaults()
    merged = {**base, **data}
    for key in _NESTED_DEFAULTS:
        if isinstance(data.get(key), dict):
            merged[key] = {**base[key], **data[key]}
        else:
            merged[key] = base[key]
    # Brightness is the canonical int 0..3; migrate legacy "dim"/"bright" strings
    # (and any junk) to it. Unrecognized values fall back to the default.
    try:
        merged["brightness"] = normalize_brightness(merged["brightness"])
    except ValueError:
        merged["brightness"] = _DEFAULT_BRIGHTNESS
    return merged


def status_defaults() -> dict:
    """A fresh status dict (what the daemon mirrors out)."""
    return {
        "alive": True,
        "mode": "clock",
        "top": "",
        "bottom": "",
        "brightness": _DEFAULT_BRIGHTNESS,  # int 0..3
        "blank": False,
        "scroll": False,
        "last_command_id": None,
        "updated_at": _now_iso(),
    }


def _atomic_write_json(path: str, data: dict, prefix: str) -> None:
    """Serialize ``data`` to ``path`` atomically (temp file + ``os.replace``)."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=directory, prefix=prefix, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
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


def save_state(state: dict) -> None:
    """Atomically write ``state`` to the state file, stamping ``updated_at``."""
    state = {**state, "updated_at": _now_iso()}
    _atomic_write_json(config.STATE_PATH, state, prefix=".state-")


def save_status(status: dict) -> None:
    """Atomically write ``status`` to the status file, stamping ``updated_at``."""
    status = {**status, "updated_at": _now_iso()}
    _atomic_write_json(config.STATUS_PATH, status, prefix=".status-")


def load_state() -> dict:
    """Load state from disk, repairing to defaults if missing or corrupt.

    The returned dict always contains every default key (missing keys are
    backfilled, nested dicts merged), so callers can index without guarding.
    """
    path = config.STATE_PATH
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("state root is not an object")
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        state = defaults()
        save_state(state)
        return state
    state = _backfill(data)
    # Self-heal a legacy brightness string (e.g. "bright") into its int form by
    # writing the migrated state back, so the file converges to the new schema.
    if data.get("brightness") != state["brightness"]:
        save_state(state)
    return state


def load_status() -> dict:
    """Load status.json (daemon-written). Returns ``{}`` if missing or corrupt.

    The daemon is the sole writer; readers (the web API) never repair it.
    """
    try:
        with open(config.STATUS_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def merge_patch(base: dict, patch: dict) -> dict:
    """Deep-merge a partial ``patch`` into ``base`` (one level into nested dicts).

    Top-level keys in ``patch`` override ``base``; for dict-valued keys both
    sides are merged so PATCHing one nested field (e.g. a single ``command`` key
    or one ``glyphs`` slot) keeps its siblings. Used by the web API's
    ``PUT /api/state`` so the desired-state file stays consistent with the same
    nested-merge convention :func:`_backfill` uses.
    """
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged
