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

# evdev key codes the firmware sends, by the bar's OWN key positions: column 1
# top→bottom a-e, column 2 f-j, with the ports along the bottom edge. Plain ints
# (linux input-event-codes.h) so this module needs no evdev.
# The bottom switch picks the bar's identity: toward the RJ45 it sends a-j,
# toward the RJ11 the letter 10 further on, k-t (bench: g→q, b→l, f→p) — most
# likely so two chained bars can be told apart. Both map to the same buttons.
_WIRE_COLS = (
    ((30, 48, 46, 32, 18), (33, 34, 35, 23, 36)),   # a b c d e | f g h i j
    ((37, 38, 50, 49, 24), (25, 16, 19, 31, 20)),   # k l m n o | p q r s t
)

# The bar is mounted ROTATED 180° (ports on top) with every cap moved so the
# legends read upright in the usual layout. Each position now holds the switch
# that used to sit diagonally opposite: top-left DECREASE sends j, bottom-right
# SERVE sends a. Set False for a bar mounted ports-down.
ROTATED = True


def _keycodes(rotated: bool) -> dict[int, str]:
    out: dict[int, str] = {}
    for col1, col2 in _WIRE_COLS:
        wire = [code for pair in zip(col1, col2) for code in pair]   # grid order
        if rotated:
            wire.reverse()
        out.update(zip(wire, BUTTONS))
    return out


KEYCODES: dict[int, str] = _keycodes(ROTATED)

_DEFAULT = {
    "tap": {
        "decrease": "brightness_down", "increase": "brightness_up",
        "previous": "mode_prev", "next": "mode_next",
        "print": "mode_cycle", "rotate": "mode_option",
        "toggle": "blank_toggle", "recall": "news_toggle", "serve": "open_headline",
    },
    "shift": {
        "decrease": "volume_down", "increase": "volume_up",
        "previous": "media_prev", "next": "media_next",
        "print": "screenshot", "rotate": "audio_output_next",
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
            if not isinstance(action, str) or action not in ACTION_IDS:
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
