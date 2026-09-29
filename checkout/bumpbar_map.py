"""The bump bar's buttons, key codes and key map (``bumpbar.json``).

Pure data + file I/O; no evdev import, so it loads on machines without a bar.
The map has two layers: ``tap`` (a plain press) and ``shift`` (while the grey
key was tapped: a one-shot shift). The grey key itself is the layer key and is
never in the map.
"""

from __future__ import annotations

import copy
import json

from checkout.bumpbar_actions import ACTION_IDS
from checkout.state import atomic_write_json

SHIFT = "shift"
LAYERS = ("tap", "shift")

# Grid order, row by row (col 1, col 2), with each key's legend and cap colour.
_BUTTONS: tuple[tuple[str, str, str], ...] = (
    ("decrease", "DECREASE", "red"),
    ("increase", "INCREASE", "green"),
    ("previous", "PREVIOUS", "grey"),
    ("next", "NEXT", "grey"),
    ("print", "PRINT", "blue"),
    ("shift", "", "dark"),
    ("rotate", "ROTATE PAGES", "blue"),
    ("toggle", "TOGGLE SCREENS", "blue"),
    ("recall", "RECALL", "blue"),
    ("serve", "SERVE", "green"),
)
BUTTONS: tuple[str, ...] = tuple(b[0] for b in _BUTTONS)

# evdev key codes the firmware sends (column 1 = a-e, column 2 = f-j). Plain
# ints (linux input-event-codes.h) so this module needs no evdev.
KEYCODES: dict[int, str] = {
    30: "decrease", 48: "previous", 46: "print", 32: "rotate", 18: "recall",  # a b c d e
    33: "increase", 34: "next", 35: "shift", 23: "toggle", 36: "serve",       # f g h i j
}

_DEFAULT = {
    "tap": {
        "decrease": "brightness_down", "increase": "brightness_up",
        "previous": "mode_prev", "next": "mode_next",
        "print": "screenshot", "rotate": "message_next",
        "toggle": "blank_toggle", "recall": "show_news", "serve": "open_headline",
    },
    "shift": {
        "decrease": "volume_down", "increase": "volume_up",
        "previous": "media_prev", "next": "media_next",
        "print": "none", "rotate": "audio_output_next",
        "toggle": "mic_mute", "recall": "lock", "serve": "media_play_pause",
    },
}


class MapError(ValueError):
    """The map is malformed; the message says why."""


def button_info() -> list[dict]:
    return [{"id": i, "legend": legend, "color": color} for i, legend, color in _BUTTONS]


def button_for(code: int) -> str | None:
    return KEYCODES.get(code)


def default_map() -> dict:
    return copy.deepcopy(_DEFAULT)


def validate_map(data) -> dict:
    """Return a complete map: ``data``'s entries over the defaults. Raises
    MapError on an unknown layer, button or action, or on remapping shift."""
    if not isinstance(data, dict):
        raise MapError("map must be an object")
    out = default_map()
    for layer, keys in data.items():
        if layer not in LAYERS:
            raise MapError(f"unknown layer {layer!r}")
        if not isinstance(keys, dict):
            raise MapError(f"layer {layer!r} must be an object")
        for button, action in keys.items():
            if button == SHIFT:
                raise MapError("the grey key is the shift key and cannot be remapped")
            if button not in BUTTONS:
                raise MapError(f"unknown button {button!r}")
            if action not in ACTION_IDS:
                raise MapError(f"unknown action {action!r}")
            out[layer][button] = action
    return out


def load_map(path: str) -> dict:
    """The map on disk, completed from defaults; defaults when the file is absent."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return default_map()
    except (OSError, ValueError) as exc:
        raise MapError(f"cannot read {path}: {exc}") from None
    return validate_map(data)


def save_map(path: str, data) -> dict:
    """Validate, write atomically, return the stored map."""
    full = validate_map(data)
    atomic_write_json(path, full, prefix=".bumpbar-")
    return full
