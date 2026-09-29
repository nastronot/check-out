"""The bump bar's action catalogue and the runner that carries actions out.

The catalogue is the ONLY list of actions. The web page offers exactly these, and
the service runs exactly these — no free-form command is ever stored or run,
because the web UI is reachable by any local process — and, with its open CORS,
by any web page in the browser — so a stored shell line would let any of them
run programs as the user.

check-out actions go through the web API, like the UI's own buttons, so the web
stays the only writer of state.json. Desktop actions are fixed argv lists that
mirror dad's Hyprland binds; the runner gets its HTTP client and process hooks
injected so tests never touch the network or start a program.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Callable

from checkout.state import ANIMATIONS, SPECTRUM_LAYOUTS, SPECTRUM_STYLES
from checkout.weather import COLON_MODES

# The UI's visible modes, in its button order (marquee is hidden, see CLAUDE.md).
MODES = ("clock", "message", "spectrum", "dynamic")

CMD_TIMEOUT_S = 5.0


class ActionError(Exception):
    """An action could not be carried out; the message is shown on the page."""


@dataclass(frozen=True)
class Action:
    id: str
    label: str
    group: str  # "checkout" | "system"
    hint: str
    repeat: bool = False


ACTIONS: tuple[Action, ...] = (
    Action("none", "nothing", "checkout", "The key does nothing."),
    Action("brightness_down", "brightness −", "checkout", "One step dimmer (4 levels).", True),
    Action("brightness_up", "brightness +", "checkout", "One step brighter (4 levels).", True),
    Action("mode_prev", "previous mode", "checkout", "clock ← message ← spectrum ← dynamic."),
    Action("mode_next", "next mode", "checkout", "clock → message → spectrum → dynamic."),
    Action("blank_toggle", "blank / unblank", "checkout", "Turn the glass off and on."),
    Action("message_next", "next saved message", "checkout", "Show the next saved message, wrapping."),
    Action("show_news", "replay news alert", "checkout", "Play the latest headline again."),
    Action("news_toggle", "news alert on / off", "checkout",
           "Play the latest headline; while any alert runs, cancel it."),
    Action("mode_cycle", "cycle style", "checkout",
           "Clock, message: animation · spectrum: layout · dynamic: time feature."),
    Action("mode_option", "mode option", "checkout",
           "Message: next saved message · spectrum: bars/line · dynamic: half speed."),
    Action("open_headline", "open last headline", "checkout", "Open the last headline shown in the browser."),
    Action("volume_down", "volume −", "system", "Output volume down 5%.", True),
    Action("volume_up", "volume +", "system", "Output volume up 5% (caps at 100%).", True),
    Action("mic_mute", "mic mute", "system", "Mute or unmute the microphone."),
    Action("media_prev", "previous track", "system", "Previous track in the active player."),
    Action("media_next", "next track", "system", "Next track in the active player."),
    Action("media_play_pause", "play / pause", "system", "Play or pause the active player."),
    Action("screenshot", "screenshot", "system", "Focused monitor to the clipboard."),
    Action("lock", "lock screen", "system", "Lock the session (hyprlock)."),
    Action("audio_output_next", "next audio output", "system", "Switch the default output device."),
)

BY_ID: dict[str, Action] = {a.id: a for a in ACTIONS}
ACTION_IDS: frozenset[str] = frozenset(BY_ID)

_SYSTEM_ARGV: dict[str, list[str]] = {
    "volume_down": ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"],
    "volume_up": ["wpctl", "set-volume", "-l", "1", "@DEFAULT_AUDIO_SINK@", "5%+"],
    "mic_mute": ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"],
    "media_prev": ["playerctl", "previous"],
    "media_next": ["playerctl", "next"],
    "media_play_pause": ["playerctl", "play-pause"],
}


def catalogue() -> list[dict]:
    """The catalogue as plain dicts, for the API."""
    return [asdict(a) for a in ACTIONS]


# --- process hooks -----------------------------------------------------------
# The session variables a desktop command needs. The service starts at login,
# BEFORE Hyprland shares these with the systemd user manager, and a process's
# environment is fixed at start — so each command reads them fresh instead.
_SESSION_KEYS = ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "DISPLAY",
                 "DBUS_SESSION_BUS_ADDRESS", "XDG_CURRENT_DESKTOP")

# How long a spawned program must survive to count as started (hyprlock with no
# display dies at once; without this check "locked" would be claimed falsely).
SPAWN_CHECK_S = 0.3


def _show_environment() -> str:
    try:
        proc = subprocess.run(["systemctl", "--user", "show-environment"],
                              capture_output=True, timeout=2, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return proc.stdout.decode(errors="replace")


def parse_session_env(text: str) -> dict[str, str]:
    """The session keys from ``systemctl --user show-environment`` output."""
    env = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in _SESSION_KEYS and value:
            env[key] = value
    return env


def session_env() -> dict[str, str]:
    """This process's environment with the live desktop session laid over it."""
    return {**os.environ, **parse_session_env(_show_environment())}


def real_run(argv: list[str], input: bytes | None = None, capture: bool = False) -> bytes:
    """Run a short command (no shell, 5 s timeout); return stdout when captured.

    Uncaptured commands get /dev/null for stdout AND stderr. That matters for
    wl-copy: it forks a child that keeps serving the clipboard, and a child holding
    our pipe open would make this call wait until the clipboard changes.
    """
    out = subprocess.PIPE if capture else subprocess.DEVNULL
    try:
        proc = subprocess.run(argv, input=input, stdout=out, stderr=out,
                              timeout=CMD_TIMEOUT_S, check=False, env=session_env())
    except FileNotFoundError:
        raise ActionError(f"{argv[0]} is not installed") from None
    except subprocess.TimeoutExpired:
        raise ActionError(f"{argv[0]} timed out") from None
    except OSError as exc:
        raise ActionError(f"{argv[0]}: {exc.strerror or exc}") from None
    if proc.returncode != 0:
        detail = (proc.stderr or b"").decode(errors="replace").strip()
        raise ActionError(f"{argv[0]} failed ({proc.returncode}) {detail}".strip())
    return proc.stdout or b""


def real_spawn(argv: list[str]) -> None:
    """Start a long-lived program (hyprlock, xdg-open) detached — never under a
    timeout, which would kill a lock screen after 5 s. A program that exits
    non-zero within SPAWN_CHECK_S is reported, not assumed started."""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True,
                                env=session_env())
    except FileNotFoundError:
        raise ActionError(f"{argv[0]} is not installed") from None
    except OSError as exc:
        raise ActionError(f"{argv[0]}: {exc.strerror or exc}") from None
    try:
        code = proc.wait(timeout=SPAWN_CHECK_S)
    except subprocess.TimeoutExpired:
        return  # still running: started
    if code != 0:
        raise ActionError(f"{argv[0]} exited at once ({code})")


# --- web API client ----------------------------------------------------------
class ApiClient:
    """Minimal stdlib client for the check-out web API."""

    def __init__(self, base_url: str, timeout: float = 2.0) -> None:
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def _call(self, method: str, path: str, body: dict | None = None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read() or b"null")
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ActionError(f"web API: {exc}") from None

    def get_state(self) -> dict:
        return self._call("GET", "/api/state")

    def put_state(self, patch: dict) -> None:
        self._call("PUT", "/api/state", patch)

    def command(self, action: str) -> None:
        self._call("POST", "/api/command", {"action": action, "args": {}})

    def get_status(self) -> dict:
        return self._call("GET", "/api/status")

    def get_library(self) -> dict:
        return self._call("GET", "/api/library")

    def recall(self, item_id: str) -> None:
        self._call("POST", f"/api/library/messages/{item_id}/recall")


# --- runner --------------------------------------------------------------------
class Runner:
    """Carries out one action id. Raises ActionError on any failure."""

    def __init__(self, api, run: Callable = real_run, spawn: Callable = real_spawn) -> None:
        self.api = api
        self.run = run
        self.spawn = spawn
        self._last_message: str | None = None

    def do(self, action_id: str) -> None:
        if action_id not in ACTION_IDS:
            raise ActionError(f"unknown action {action_id!r}")
        if action_id == "none":
            return
        if action_id in _SYSTEM_ARGV:
            self.run(_SYSTEM_ARGV[action_id])
            return
        getattr(self, "_" + action_id)()

    # check-out
    def _step_brightness(self, delta: int) -> None:
        level = int(self.api.get_state().get("brightness", 3))
        new = max(0, min(3, level + delta))
        if new != level:
            self.api.put_state({"brightness": new})

    def _brightness_down(self) -> None:
        self._step_brightness(-1)

    def _brightness_up(self) -> None:
        self._step_brightness(+1)

    def _step_mode(self, delta: int) -> None:
        mode = self.api.get_state().get("mode")
        # A hidden mode (marquee) counts as "before clock", so next lands on clock.
        i = MODES.index(mode) if mode in MODES else (-1 if delta > 0 else 0)
        self.api.put_state({"mode": MODES[(i + delta) % len(MODES)]})

    def _mode_prev(self) -> None:
        self._step_mode(-1)

    def _mode_next(self) -> None:
        self._step_mode(+1)

    def _blank_toggle(self) -> None:
        self.api.put_state({"blank": not self.api.get_state().get("blank", False)})

    def _message_next(self) -> None:
        ids = [m["id"] for m in self.api.get_library().get("messages", []) if "id" in m]
        if not ids:
            raise ActionError("no saved messages")
        i = ids.index(self._last_message) + 1 if self._last_message in ids else 0
        self._last_message = ids[i % len(ids)]
        self.api.recall(self._last_message)

    def _show_news(self) -> None:
        self.api.command("show_news")

    def _news_toggle(self) -> None:
        # The daemon decides: it knows whether ANY alert (pressed or live) runs.
        self.api.command("toggle_news")

    # Keys that act on the mode live on the glass.
    def _mode_cycle(self) -> None:
        state = self.api.get_state()
        mode = state.get("mode")
        if mode == "spectrum":
            key, values = "spectrum_layout", SPECTRUM_LAYOUTS
        elif mode == "dynamic":
            key, values = "dynamic_colon", COLON_MODES
        else:  # clock, message (and hidden marquee): the animation
            key, values = "animation", ANIMATIONS
        current = state.get(key)
        i = values.index(current) + 1 if current in values else 0
        self.api.put_state({key: values[i % len(values)]})

    def _mode_option(self) -> None:
        state = self.api.get_state()
        mode = state.get("mode")
        if mode == "message":
            self._message_next()
        elif mode == "spectrum":
            style = state.get("spectrum_style")
            self.api.put_state({"spectrum_style": "line" if style == "bars" else "bars"})
        elif mode == "dynamic":
            self.api.put_state({"dynamic_colon_half": not state.get("dynamic_colon_half", False)})
        # clock: no function

    def _open_headline(self) -> None:
        shown = self.api.get_status().get("news_shown") or {}
        link = shown.get("link") if isinstance(shown, dict) else None
        if not isinstance(link, str) or not link.startswith(("http://", "https://")):
            raise ActionError("no headline shown yet")
        self.spawn(["xdg-open", link])

    # system
    def _lock(self) -> None:
        self.spawn(["hyprlock"])

    def _screenshot(self) -> None:
        argv = ["grim", "-"]
        try:
            mons = json.loads(self.run(["hyprctl", "monitors", "-j"], capture=True))
            name = next((m["name"] for m in mons if m.get("focused")), None)
            if name:
                argv = ["grim", "-o", name, "-"]
        except (ActionError, ValueError, TypeError, KeyError, AttributeError):
            pass  # no Hyprland answer: capture every output
        png = self.run(argv, capture=True)
        self.run(["wl-copy", "--type", "image/png"], input=png)
        self.run(["notify-send", "check-out", "screenshot copied"])

    def _audio_output_next(self) -> None:
        try:
            sinks = json.loads(self.run(["pactl", "--format=json", "list", "sinks"], capture=True))
        except ValueError:
            raise ActionError("pactl gave no sink list") from None
        sinks = [s for s in sinks if isinstance(s, dict) and "name" in s]
        if not sinks:
            raise ActionError("no audio outputs")
        names = [s["name"] for s in sinks]
        current = self.run(["pactl", "get-default-sink"], capture=True).decode().strip()
        i = names.index(current) + 1 if current in names else 0
        target = sinks[i % len(sinks)]
        self.run(["pactl", "set-default-sink", target["name"]])
        self.run(["notify-send", "check-out",
                  f"output: {target.get('description') or target['name']}"])
