"""Web-owned library of saved messages and glyphs (``library.json``).

This store is read/written by the FastAPI side ONLY. The daemon never reads it —
recalling a library item writes ``state.json`` through the normal path, which the
daemon already consumes. Writes are atomic (reusing ``checkout.state``).

Schema::

    {
      "messages": [
        { "id", "name", "message", "mode", "align_top", "align_bottom",
          "brightness", "glyphs": { "<slot>": [7 ints], ... } },
        ...
      ],
      "glyphs": [ { "id", "name", "rows": [7 ints] }, ... ]
    }
"""

from __future__ import annotations

import json
import uuid

from checkout import config
from checkout.driver import normalize_brightness
from checkout.state import atomic_write_json

# Reasonable caps so the file can't grow unbounded.
MAX_ITEMS = 200
GLYPH_ROWS = 7
_MODES = ("message", "ticker")
_ALIGNS = ("left", "center", "right")


class LibraryError(ValueError):
    """Raised on invalid input to a library mutation (mapped to HTTP 400/404)."""


# --- storage ----------------------------------------------------------------
def load_library() -> dict:
    """Load library.json, returning an empty library if missing or corrupt."""
    try:
        with open(config.LIBRARY_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("library root is not an object")
    except (FileNotFoundError, json.JSONDecodeError, ValueError, OSError):
        return {"messages": [], "glyphs": []}
    return {
        "messages": data.get("messages") or [],
        "glyphs": data.get("glyphs") or [],
    }


def save_library(library: dict) -> None:
    atomic_write_json(config.LIBRARY_PATH, library, prefix=".library-")


# --- validation -------------------------------------------------------------
def _clean_name(name) -> str:
    if not isinstance(name, str) or not name.strip():
        raise LibraryError("name must be a non-empty string")
    return name.strip()[:80]


def _clean_rows(rows) -> list[int]:
    if not isinstance(rows, (list, tuple)) or len(rows) != GLYPH_ROWS:
        raise LibraryError(f"rows must be {GLYPH_ROWS} ints")
    try:
        return [int(r) & 0x1F for r in rows]
    except (TypeError, ValueError):
        raise LibraryError("rows must be ints") from None


def _clean_glyph_map(glyphs) -> dict:
    """Validate a {slot: rows} map (the glyph defs a message carries)."""
    out: dict[str, list[int]] = {}
    if not glyphs:
        return out
    if not isinstance(glyphs, dict):
        raise LibraryError("glyphs must be an object")
    for slot, rows in glyphs.items():
        if str(slot) not in {str(i) for i in range(9)}:
            raise LibraryError(f"bad glyph slot {slot!r}")
        out[str(slot)] = _clean_rows(rows)
    return out


# --- messages ---------------------------------------------------------------
def add_message(payload: dict) -> dict:
    """Save the current composable state as a named message; returns the item."""
    library = load_library()
    if len(library["messages"]) >= MAX_ITEMS:
        raise LibraryError(f"message library is full (max {MAX_ITEMS})")
    mode = payload.get("mode", "message")
    if mode not in _MODES:
        mode = "message"
    item = {
        "id": uuid.uuid4().hex,
        "name": _clean_name(payload.get("name")),
        "message": str(payload.get("message") or ""),
        "mode": mode,
        "align_top": payload.get("align_top")
        if payload.get("align_top") in _ALIGNS else "center",
        "align_bottom": payload.get("align_bottom")
        if payload.get("align_bottom") in _ALIGNS else "center",
        "brightness": _safe_brightness(payload.get("brightness")),
        "glyphs": _clean_glyph_map(payload.get("glyphs")),
    }
    library["messages"].append(item)
    save_library(library)
    return item


def delete_message(item_id: str) -> None:
    library = load_library()
    kept = [m for m in library["messages"] if m.get("id") != item_id]
    if len(kept) == len(library["messages"]):
        raise KeyError(item_id)
    library["messages"] = kept
    save_library(library)


def get_message(item_id: str) -> dict:
    for m in load_library()["messages"]:
        if m.get("id") == item_id:
            return m
    raise KeyError(item_id)


def message_to_state_patch(item: dict) -> dict:
    """The state.json patch that recalls a saved message onto the glass.

    Includes the message's glyphs so the daemon (re)defines them and the {gN}
    refs light up — this is the one bridge from library to live state.
    """
    return {
        "mode": item.get("mode", "message"),
        "message": item.get("message", ""),
        "align_top": item.get("align_top", "center"),
        "align_bottom": item.get("align_bottom", "center"),
        "brightness": _safe_brightness(item.get("brightness")),
        "glyphs": item.get("glyphs") or {},
    }


# --- glyphs -----------------------------------------------------------------
def add_glyph(payload: dict) -> dict:
    library = load_library()
    if len(library["glyphs"]) >= MAX_ITEMS:
        raise LibraryError(f"glyph library is full (max {MAX_ITEMS})")
    item = {
        "id": uuid.uuid4().hex,
        "name": _clean_name(payload.get("name")),
        "rows": _clean_rows(payload.get("rows")),
    }
    library["glyphs"].append(item)
    save_library(library)
    return item


def delete_glyph(item_id: str) -> None:
    library = load_library()
    kept = [g for g in library["glyphs"] if g.get("id") != item_id]
    if len(kept) == len(library["glyphs"]):
        raise KeyError(item_id)
    library["glyphs"] = kept
    save_library(library)


def _safe_brightness(value) -> int:
    try:
        return normalize_brightness(value if value is not None else 3)
    except ValueError:
        return 3
