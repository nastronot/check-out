"""check-out bump bar service: the TG3 M4220's ten keys drive check-out + desktop.

    python -m checkout.bumpbar            # run (grabs the bar; keys stop typing)
    python -m checkout.bumpbar --capture  # bench: print key codes, run nothing

It GRABS the bar's input nodes (EVIOCGRAB: exclusive, so no key reaches
Hyprland or a focused window), maps each press through the two-layer key map
(``bumpbar.json``, written by the web; the grey key is a one-shot shift: tap
it, then a key) and runs the action. It writes
``bumpbar-status.json`` for the page. Missing bar = idle and retry every 2 s, so
the service is harmless on a machine without one — but it is only installed
where a bar lives (install.sh --bumpbar).
"""

from __future__ import annotations

import argparse
import glob
import os
import select
import signal
import sys
import time
from datetime import datetime, timezone

from checkout import config
from checkout.bumpbar_actions import BY_ID, ActionError, ApiClient, Runner
from checkout.bumpbar_map import SHIFT, MapError, button_for, default_map, load_map
from checkout.state import atomic_write_json

RETRY_S = 2.0
HEARTBEAT_S = 2.0
# How long a tap on the grey key keeps the shift layer armed.
SHIFT_WINDOW_S = 3.0
# select() timeout: short enough that an expired shift clears on the page promptly.
POLL_S = 0.5
EV_KEY = 1  # linux input-event-codes.h


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] bumpbar: {msg}", flush=True)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Keypad:
    """Layer logic. ``feed`` takes one key event (value 1 down, 2 auto-repeat,
    0 up) and returns ``(button, layer, action)`` when an action should run.

    The grey key is a ONE-SHOT shift. The M4220 sends every key as an instant
    tap — down and up within ~40 ms however long it is held (bench 2026-09-28) —
    so a held modifier can't be seen. Tap grey, then tap a key within
    SHIFT_WINDOW_S: that key uses the shift layer. Grey twice cancels.
    """

    def __init__(self, clock=time.monotonic) -> None:
        self.clock = clock
        self._armed_until: float | None = None

    @property
    def layer(self) -> str:
        if self._armed_until is not None and self.clock() <= self._armed_until:
            return "shift"
        self._armed_until = None
        return "tap"

    def feed(self, code: int, value: int, keymap: dict):
        button = button_for(code)
        if button is None or value == 0:
            return None
        if button == SHIFT:
            if value == 1:
                self._armed_until = (None if self.layer == "shift"
                                     else self.clock() + SHIFT_WINDOW_S)
            return None
        layer = self.layer
        action = keymap[layer][button]
        if value == 2 and not BY_ID[action].repeat:
            return None
        if value == 1:
            self._armed_until = None
        return button, layer, action


class MapWatcher:
    """Re-reads the map only when its mtime changes; keeps the last good map."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._mtime: float | None = None
        self._map = default_map()
        self.error: str | None = None

    def current(self) -> dict:
        try:
            mtime = os.stat(self.path).st_mtime
        except FileNotFoundError:
            mtime = None
        if mtime != self._mtime:
            self._mtime = mtime
            try:
                self._map = load_map(self.path)
                self.error = None
            except MapError as exc:
                self.error = str(exc)
                _log(f"map: {exc} (keeping the last good map)")
        return self._map


class StatusWriter:
    """bumpbar-status.json: written on change, plus a heartbeat for liveness."""

    def __init__(self, path: str, clock=time.monotonic) -> None:
        self.path = path
        self.clock = clock
        self.fields = {"alive": True, "connected": False, "device": None,
                       "layer": "tap", "last_press": None, "error": None}
        self._written: float | None = None

    def _write(self) -> None:
        atomic_write_json(self.path, {**self.fields, "updated_at": _now_iso()},
                          prefix=".bumpbar-status-")
        self._written = self.clock()

    def update(self, **fields) -> None:
        if any(self.fields.get(k) != v for k, v in fields.items()):
            self.fields.update(fields)
            self._write()

    def tick(self) -> None:
        if self._written is None or self.clock() - self._written >= HEARTBEAT_S:
            self._write()

    def close(self) -> None:
        self.fields.update(alive=False, connected=False)
        self._write()


def device_nodes(kbd_path: str) -> list[str]:
    """The keyboard node plus its sibling event nodes (the "System Control"
    interface), so a stray Power/Sleep code is grabbed too. Keyboard first."""
    base = kbd_path.rsplit("-event", 1)[0]
    others = sorted(p for p in glob.glob(glob.escape(base) + "*-event*") if p != kbd_path)
    return [kbd_path, *others]


def open_devices(kbd_path: str):
    """Open + grab every node of the bar; None when the bar is absent."""
    if not os.path.exists(kbd_path):
        return None
    import evdev  # only machines with a bar install it (requirements-bumpbar.txt)

    devices = []
    try:
        for path in device_nodes(kbd_path):
            dev = evdev.InputDevice(path)
            devices.append(dev)
            dev.grab()
    except OSError:
        for dev in devices:
            dev.close()
        raise
    return devices


def _close_all(devices, ungrab: bool = False) -> None:
    for dev in devices:
        try:
            if ungrab:
                dev.ungrab()
        except OSError:
            pass
        try:
            dev.close()
        except OSError:
            pass


class Service:
    def __init__(self, runner, watcher: MapWatcher, status: StatusWriter,
                 opener=None, sleep=time.sleep) -> None:
        self.runner = runner
        self.watcher = watcher
        self.status = status
        self.opener = opener or (lambda: open_devices(config.BUMPBAR_DEVICE))
        self.sleep = sleep
        self.keypad = Keypad()

    def handle(self, code: int, value: int) -> None:
        if value == 1 and button_for(code) is None:
            _log(f"unmapped key code {code} (not in bumpbar_map.KEYCODES)")
        hit = self.keypad.feed(code, value, self.watcher.current())
        self.status.update(layer=self.keypad.layer)
        if hit is None:
            return
        button, layer, action = hit
        error = self.watcher.error
        mark = "⇧ " if layer == "shift" else ""
        try:
            self.runner.do(action)
            _log(f"{mark}{button} → {action}")
        except ActionError as exc:
            error = str(exc)
            _log(f"{mark}{button} → {action}: {exc}")
        self.status.update(error=error, last_press={
            "button": button, "layer": layer, "action": action, "at": _now_iso()})

    def run(self, stop) -> None:
        devices = None
        while not stop():
            if devices is None:
                try:
                    devices = self.opener()
                except OSError as exc:
                    self.status.update(error=f"cannot open the bar: {exc}")
                    devices = None
                if devices is None:
                    self.status.update(connected=False)
                    self.status.tick()
                    self.sleep(RETRY_S)
                    continue
                _log(f"grabbed {len(devices)} node(s) at {devices[0].path}")
                self.keypad = Keypad()
                self.status.update(connected=True, device=devices[0].path,
                                   layer="tap", error=None)
            try:
                ready, _, _ = select.select(devices, [], [], POLL_S)
                for dev in ready:
                    for ev in dev.read():
                        # Keys come from the keyboard node only; the System
                        # Control node is grabbed just so its codes go nowhere.
                        if dev is devices[0] and ev.type == EV_KEY:
                            self.handle(ev.code, ev.value)
            except OSError:
                _log("bar disconnected")
                _close_all(devices)
                devices = None
                self.status.update(connected=False, layer="tap")
            self.status.update(layer=self.keypad.layer)  # an armed shift expiring
            self.status.tick()
        _close_all(devices or [], ungrab=True)


def capture(kbd_path: str) -> int:
    """Bench mode: grab and print every key event, run nothing. Ctrl-C to stop."""
    import evdev

    devices = open_devices(kbd_path)
    if devices is None:
        print(f"no bar at {kbd_path}", file=sys.stderr)
        return 1
    print("press keys (Ctrl-C stops):", flush=True)
    try:
        while True:
            ready, _, _ = select.select(devices, [], [])
            for dev in ready:
                for ev in dev.read():
                    if ev.type == EV_KEY:
                        name = evdev.ecodes.KEY.get(ev.code, ev.code)
                        print(f"{os.path.basename(dev.path)}  code={ev.code} {name} "
                              f"value={ev.value} → {button_for(ev.code)}", flush=True)
    except KeyboardInterrupt:
        return 0
    finally:
        _close_all(devices, ungrab=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m checkout.bumpbar")
    parser.add_argument("--capture", action="store_true",
                        help="print key codes instead of running actions")
    args = parser.parse_args(argv)
    if args.capture:
        return capture(config.BUMPBAR_DEVICE)

    stopping = False

    def _stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    status = StatusWriter(config.BUMPBAR_STATUS_PATH)
    service = Service(Runner(ApiClient(config.API_URL)), MapWatcher(config.BUMPBAR_PATH), status)
    _log(f"watching {config.BUMPBAR_DEVICE}")
    try:
        service.run(stop=lambda: stopping)
    finally:
        status.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
