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
        "mode": "clock",                 # "clock"|"message"|"scroll"|"marquee"|"spectrum"
        "message": "",                   # text for message / scroll modes
        "align_top": "center",           # "left" | "center" | "right" — line 1
        "align_bottom": "center",        # "left" | "center" | "right" — line 2
        # --- marquee (hardware ticker, top row autonomous + FIXED speed) ---
        "marquee_text": "",              # scrolls on the top row (hardware ticker)
        # Bottom row is STATIC TEXT ONLY. A live clock there is impossible: a
        # bottom write that lands after the hardware scroll resumes STOPS it
        # (bench-confirmed), so clock-bottom was removed. The field is kept for
        # back-compat but always normalized to "static".
        "marquee_bottom": "static",      # "static" only (legacy "clock" -> "static")
        "marquee_bottom_text": "",       # the static bottom text
        # --- software scroll (mode "scroll"): per-row source + scroll + dir ---
        # Each row independently selects a CONTENT SOURCE and (for "message")
        # whether it scrolls and in which direction. "clock" shows the live time
        # line. This is the flexible, news-ready mode (a "news" source slots into
        # _SCROLL_SOURCES later without reshaping the schema).
        "scroll_top_source": "message",     # "message" | "clock" (future: "news")
        "scroll_bottom_source": "message",  # "message" | "clock" (future: "news")
        "scroll_top": True,              # scroll the top row (when source "message")
        "scroll_bottom": False,          # scroll the bottom row (when source "message")
        "scroll_dir_top": "left",        # "left" | "right"
        "scroll_dir_bottom": "left",     # "left" | "right"
        "brightness": _DEFAULT_BRIGHTNESS,  # int 0..3 (0 Min..3 Max)
        "blank": False,                  # blank the display entirely
        "scroll": False,                 # hardware vertical-scroll MODE (0x11/0x12)
        "code_page": 0,                  # 0..11
        "scroll_speed_ms": 300,          # ticker software-scroll step
        "animation": "none",             # "none" | "flash" | "blink" | "pulse"
        # on_ms/off_ms time flash + blink; step_ms is the pulse triangle step.
        "animation_params": {"on_ms": 500, "off_ms": 500, "step_ms": 200},
        # {"0": [r0..r6], ... "8": [...]} optional 5x7 user glyphs. Each row is an
        # int whose LOW 5 bits are columns 1..5 (bit0=col1 ... bit4=col5) — the
        # editor-natural convention; the driver translates to the wire format
        # (<<3). Place a glyph in a message with the {gN} placeholder.
        "glyphs": {},
        # --- spectrum analyzer (mode "spectrum"). The HEAVY per-frame bar data
        # goes over a unix socket, NOT here; only these settings live in state. ---
        "audio_source": "system",        # "mic" | "system" (PipeWire/Pulse monitor)
        "audio_device": None,            # device name/index, or null = default/auto
        "audio_gain": 1.0,               # sensitivity multiplier
        "audio_decay": 0.85,             # bar release factor (attack-fast/release-slow)
        "command": {"id": None, "action": None, "args": {}},
        "updated_at": _now_iso(),
    }


# Keys whose defaults are dicts: a partial write of these should be MERGED with
# the default (so e.g. {"command": {"id": "x"}} keeps a default action/args)
# rather than wholesale-replaced. ``glyphs`` is intentionally NOT here — it is a
# user-owned map and a write replaces it entirely.
_NESTED_DEFAULTS = ("animation_params", "command")

# Per-row content sources for software scroll. EXTENSION POINT: add "news" here
# (and wire a news renderer in the daemon) to give a row a live news feed — the
# schema/UI shape already accommodate a third option.
_SCROLL_SOURCES = ("message", "clock")
_DEFAULT_SCROLL_SOURCE = "message"


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
    # Legacy mode "ticker" is the old single-line top scroll — now "scroll".
    if merged.get("mode") == "ticker":
        merged["mode"] = "scroll"
    # Marquee bottom is static-only now (live clock-bottom stops the hardware
    # scroll). Normalize any value (incl. legacy "clock") to "static".
    if merged.get("marquee_bottom") != "static":
        merged["marquee_bottom"] = "static"
    # Per-row scroll sources: coerce anything unknown back to the default.
    for key in ("scroll_top_source", "scroll_bottom_source"):
        if merged.get(key) not in _SCROLL_SOURCES:
            merged[key] = _DEFAULT_SCROLL_SOURCE
    # Spectrum audio settings: source is mic|system; gain/decay are clamped floats.
    if merged.get("audio_source") not in ("mic", "system"):
        merged["audio_source"] = "system"
    merged["audio_gain"] = _clamp_float(merged.get("audio_gain"), 1.0, 0.05, 20.0)
    merged["audio_decay"] = _clamp_float(merged.get("audio_decay"), 0.85, 0.0, 0.999)
    return merged


def _clamp_float(value, default: float, lo: float, hi: float) -> float:
    """Coerce ``value`` to a float in ``[lo, hi]``, falling back to ``default``."""
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return default


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


def atomic_write_json(path: str, data, prefix: str = ".tmp-") -> None:
    """Public atomic JSON writer (temp file + ``os.replace``), reused by the
    web library store so it gets the same crash-safe write as state/status."""
    _atomic_write_json(path, data, prefix)


def _atomic_write_json(path: str, data, prefix: str) -> None:
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
    # Self-heal a migrated legacy value (brightness "dim"/"bright" -> int, or
    # mode "ticker" -> "scroll") by writing it back so the file converges.
    if (data.get("brightness") != state["brightness"]
            or data.get("mode") != state["mode"]):
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
