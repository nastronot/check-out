"""Bump bar action catalogue + runner (no real HTTP, no real processes)."""

import pytest

from checkout import bumpbar_actions as ba


class FakeApi:
    def __init__(self, state=None, status=None, messages=None, fail=False):
        self.state = {"brightness": 2, "mode": "clock", "blank": False, **(state or {})}
        self.status = status or {}
        self.messages = messages if messages is not None else []
        self.puts, self.commands, self.recalls = [], [], []
        self.fail = fail

    def _check(self):
        if self.fail:
            raise ba.ActionError("web API unreachable")

    def get_state(self):
        self._check()
        return dict(self.state)

    def put_state(self, patch):
        self._check()
        self.puts.append(patch)
        self.state.update(patch)

    def command(self, action):
        self._check()
        self.commands.append(action)

    def get_status(self):
        self._check()
        return self.status

    def get_library(self):
        self._check()
        return {"messages": self.messages, "glyphs": []}

    def recall(self, item_id):
        self._check()
        self.recalls.append(item_id)


class Procs:
    def __init__(self, outputs=None):
        self.runs, self.spawns = [], []
        self.outputs = outputs or {}

    def run(self, argv, input=None, capture=False):
        self.runs.append((argv, input))
        return self.outputs.get(argv[0], b"")

    def spawn(self, argv):
        self.spawns.append(argv)


def make(api=None, procs=None):
    api = api or FakeApi()
    procs = procs or Procs()
    return ba.Runner(api, procs.run, procs.spawn), api, procs


def test_catalogue_ids_unique_and_grouped():
    ids = [a.id for a in ba.ACTIONS]
    assert len(ids) == len(set(ids))
    assert {a.group for a in ba.ACTIONS} == {"checkout", "system"}
    assert "none" in ba.ACTION_IDS
    assert all(set(d) == {"id", "label", "group", "hint", "repeat"} for d in ba.catalogue())


def test_only_volume_and_brightness_repeat():
    assert {a.id for a in ba.ACTIONS if a.repeat} == {
        "brightness_down", "brightness_up", "volume_down", "volume_up"}


@pytest.mark.parametrize("start,action,expect", [
    (2, "brightness_up", 3), (3, "brightness_up", None),
    (1, "brightness_down", 0), (0, "brightness_down", None)])
def test_brightness_steps_and_clamps(start, action, expect):
    r, api, _ = make(FakeApi(state={"brightness": start}))
    r.do(action)
    assert api.puts == ([] if expect is None else [{"brightness": expect}])


@pytest.mark.parametrize("mode,action,expect", [
    ("clock", "mode_next", "message"), ("dynamic", "mode_next", "clock"),
    ("clock", "mode_prev", "dynamic"), ("marquee", "mode_next", "clock")])
def test_mode_cycles_visible_modes(mode, action, expect):
    r, api, _ = make(FakeApi(state={"mode": mode}))
    r.do(action)
    assert api.puts == [{"mode": expect}]


def test_blank_toggle():
    r, api, _ = make()
    r.do("blank_toggle")
    r.do("blank_toggle")
    assert api.puts == [{"blank": True}, {"blank": False}]


def test_message_next_wraps_and_follows_last_id():
    api = FakeApi(messages=[{"id": "a"}, {"id": "b"}])
    r, api, _ = make(api)
    r.do("message_next")
    r.do("message_next")
    r.do("message_next")
    assert api.recalls == ["a", "b", "a"]


def test_message_next_with_empty_library_errors():
    r, _, _ = make()
    with pytest.raises(ba.ActionError, match="no saved messages"):
        r.do("message_next")


def test_show_news_sends_command():
    r, api, _ = make()
    r.do("show_news")
    assert api.commands == ["show_news"]


def test_api_failure_surfaces_as_action_error():
    r, _, _ = make(FakeApi(fail=True))
    with pytest.raises(ba.ActionError, match="unreachable"):
        r.do("mode_next")


def test_open_headline_spawns_xdg_open():
    api = FakeApi(status={"news_shown": {"link": "https://example.com/x"}})
    r, _, procs = make(api)
    r.do("open_headline")
    assert procs.spawns == [["xdg-open", "https://example.com/x"]]


@pytest.mark.parametrize("shown", [None, {}, {"link": "file:///etc/passwd"}])
def test_open_headline_refuses_missing_or_non_http(shown):
    r, _, procs = make(FakeApi(status={"news_shown": shown}))
    with pytest.raises(ba.ActionError):
        r.do("open_headline")
    assert procs.spawns == []


@pytest.mark.parametrize("action,argv", [
    ("volume_down", ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"]),
    ("volume_up", ["wpctl", "set-volume", "-l", "1", "@DEFAULT_AUDIO_SINK@", "5%+"]),
    ("mic_mute", ["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"]),
    ("media_prev", ["playerctl", "previous"]),
    ("media_next", ["playerctl", "next"]),
    ("media_play_pause", ["playerctl", "play-pause"])])
def test_system_commands_argv(action, argv):
    r, _, procs = make()
    r.do(action)
    assert procs.runs == [(argv, None)]


def test_lock_spawns_detached():
    r, _, procs = make()
    r.do("lock")
    assert procs.spawns == [["hyprlock"]]
    assert procs.runs == []


def test_screenshot_focused_monitor_to_clipboard():
    procs = Procs(outputs={
        "hyprctl": b'[{"name":"DP-1","focused":false},{"name":"HDMI-A-1","focused":true}]',
        "grim": b"PNG"})
    r, _, procs = make(procs=procs)
    r.do("screenshot")
    argvs = [a for a, _ in procs.runs]
    assert argvs[0] == ["hyprctl", "monitors", "-j"]
    assert argvs[1] == ["grim", "-o", "HDMI-A-1", "-"]
    assert procs.runs[2] == (["wl-copy", "--type", "image/png"], b"PNG")
    assert argvs[3][0] == "notify-send"


def test_screenshot_without_hyprland_captures_all_outputs():
    procs = Procs(outputs={"hyprctl": b"not json", "grim": b"PNG"})
    r, _, procs = make(procs=procs)
    r.do("screenshot")
    assert procs.runs[1][0] == ["grim", "-"]


def test_audio_output_next_cycles_sinks():
    procs = Procs()
    calls = iter([
        b'[{"name":"a","description":"Speakers"},{"name":"b","description":"Headset"}]',
        b"a\n", b"", b""])

    def run(argv, input=None, capture=False):
        procs.runs.append((argv, input))
        return next(calls)

    r = ba.Runner(FakeApi(), run, procs.spawn)
    r.do("audio_output_next")
    argvs = [a for a, _ in procs.runs]
    assert argvs[2] == ["pactl", "set-default-sink", "b"]
    assert argvs[3][:2] == ["notify-send", "check-out"]
    assert "Headset" in argvs[3][-1]


def test_none_does_nothing_and_unknown_raises():
    r, api, procs = make()
    r.do("none")
    assert api.puts == [] and procs.runs == []
    with pytest.raises(ba.ActionError):
        r.do("rm_rf")


def test_real_run_reports_missing_program():
    with pytest.raises(ba.ActionError, match="not installed"):
        ba.real_run(["checkout-no-such-program-xyz"])


def test_real_run_reports_failure():
    with pytest.raises(ba.ActionError, match="failed"):
        ba.real_run(["false"])


# --- review fixes: session env, silent failures -------------------------------
def test_parse_session_env_keeps_only_session_keys():
    text = ("PATH=/usr/bin\nWAYLAND_DISPLAY=wayland-1\n"
            "HYPRLAND_INSTANCE_SIGNATURE=abc_123\nDISPLAY=:0\nWAYLAND_DISPLAY_X=no\n")
    assert ba.parse_session_env(text) == {
        "WAYLAND_DISPLAY": "wayland-1", "HYPRLAND_INSTANCE_SIGNATURE": "abc_123",
        "DISPLAY": ":0"}


def test_session_env_overlays_the_live_session(monkeypatch):
    # A service started at login, before Hyprland shared its variables, has
    # none; each desktop command reads them fresh from the user manager.
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.setattr(ba, "_show_environment", lambda: "WAYLAND_DISPLAY=wayland-9\n")
    assert ba.session_env()["WAYLAND_DISPLAY"] == "wayland-9"


def test_real_spawn_reports_a_program_that_dies_at_once(monkeypatch):
    # hyprlock with no display exits immediately; "locked" must not be claimed.
    monkeypatch.setattr(ba, "_show_environment", lambda: "")
    with pytest.raises(ba.ActionError, match="exited"):
        ba.real_spawn(["false"])


def test_real_spawn_leaves_a_long_lived_program_running(monkeypatch):
    monkeypatch.setattr(ba, "_show_environment", lambda: "")
    ba.real_spawn(["sleep", "1"])  # still running after the check: no error


def test_real_run_turns_any_os_error_into_action_error(tmp_path, monkeypatch):
    monkeypatch.setattr(ba, "_show_environment", lambda: "")
    script = tmp_path / "not-executable"
    script.write_text("#!/bin/sh\n")
    with pytest.raises(ba.ActionError):
        ba.real_run([str(script)])
    with pytest.raises(ba.ActionError):
        ba.real_spawn([str(script)])
