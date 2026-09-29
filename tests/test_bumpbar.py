"""The bump bar service: layer logic, map reload, status file, device loop."""

import json
import os
import time

from checkout import bumpbar as bb
from checkout import bumpbar_map as bm
from checkout.bumpbar_actions import ActionError

A, F, G, H, J = 30, 33, 34, 35, 36  # decrease, increase, next, shift, serve


def test_keypad_tap_and_release():
    k, m = bb.Keypad(), bm.default_map()
    assert k.feed(G, 1, m) == ("next", "tap", "mode_next")
    assert k.feed(G, 0, m) is None
    assert k.feed(99, 1, m) is None


def test_keypad_shift_layer():
    # The bar sends every key as an instant tap (bench 2026-09-28), so the grey
    # key is a ONE-SHOT shift: tap it, and the next key within the window uses
    # the shift layer.
    now = [0.0]
    k, m = bb.Keypad(clock=lambda: now[0]), bm.default_map()
    assert k.feed(H, 1, m) is None          # grey alone does nothing
    assert k.feed(H, 0, m) is None          # its instant release keeps it armed
    assert k.layer == "shift"
    now[0] = 1.0
    assert k.feed(J, 1, m) == ("serve", "shift", "media_play_pause")
    assert k.layer == "tap"                 # used up by one key
    assert k.feed(J, 1, m) == ("serve", "tap", "open_headline")


def test_keypad_shift_expires():
    now = [0.0]
    k, m = bb.Keypad(clock=lambda: now[0]), bm.default_map()
    k.feed(H, 1, m)
    now[0] = bb.SHIFT_WINDOW_S + 0.1
    assert k.layer == "tap"
    assert k.feed(J, 1, m) == ("serve", "tap", "open_headline")


def test_keypad_repeat_actions_keep_shift_armed():
    # Stepping the volume: grey, then DECREASE three times = three volume steps.
    now = [0.0]
    k, m = bb.Keypad(clock=lambda: now[0]), bm.default_map()
    k.feed(H, 1, m)
    for t in (1.0, 3.5, 6.0):                  # each step re-arms the window
        now[0] = t
        assert k.feed(A, 1, m) == ("decrease", "shift", "volume_down")
    now[0] = 6.0 + bb.SHIFT_WINDOW_S + 0.1
    assert k.feed(A, 1, m) == ("decrease", "tap", "brightness_down")


def test_keypad_other_shift_actions_use_it_up():
    k, m = bb.Keypad(), bm.default_map()
    k.feed(H, 1, m)
    assert k.feed(J, 1, m)[1] == "shift"       # play/pause
    assert k.layer == "tap"


def test_keypad_grey_twice_cancels():
    k, m = bb.Keypad(), bm.default_map()
    k.feed(H, 1, m)
    k.feed(H, 1, m)
    assert k.layer == "tap"


def test_keypad_repeat_only_for_repeat_actions():
    k, m = bb.Keypad(), bm.default_map()
    assert k.feed(G, 2, m) is None                                 # mode_next: once
    assert k.feed(F, 2, m) == ("increase", "tap", "brightness_up")  # repeats


def test_map_watcher_reloads_and_keeps_last_good(tmp_path):
    p = tmp_path / "m.json"
    w = bb.MapWatcher(str(p))
    assert w.current() == bm.default_map() and w.error is None
    bm.save_map(str(p), {"tap": {"next": "lock"}})
    os.utime(p, (time.time() + 5, time.time() + 5))
    assert w.current()["tap"]["next"] == "lock"
    p.write_text("{broken")
    os.utime(p, (time.time() + 10, time.time() + 10))
    assert w.current()["tap"]["next"] == "lock"
    assert "cannot read" in w.error


def test_status_writer_writes_on_change_and_heartbeat(tmp_path):
    p = tmp_path / "s.json"
    now = [100.0]
    s = bb.StatusWriter(str(p), clock=lambda: now[0])
    s.update(connected=True)
    first = json.loads(p.read_text())
    assert first["connected"] is True and first["alive"] is True
    p.unlink()
    s.tick()                     # no change, no heartbeat yet
    assert not p.exists()
    now[0] += 2.5
    s.tick()                     # heartbeat
    assert p.exists()
    s.close()
    assert json.loads(p.read_text())["alive"] is False


def _fake_sysfs(tmp_path):
    """/sys/class/input + /dev/input for the bar (event25 kbd, 26, 27 on the same
    USB device 5-2.4) and an unrelated keyboard (event6)."""
    sysfs, devdir = tmp_path / "sys" / "class" / "input", tmp_path / "dev" / "input"
    sysfs.mkdir(parents=True)
    (devdir / "by-id").mkdir(parents=True)
    usb = tmp_path / "sys" / "devices" / "usb5" / "5-2" / "5-2.4"
    other = tmp_path / "sys" / "devices" / "usb5" / "5-1"
    for ev, parent in (("event25", usb / "5-2.4:1.0" / "0003:0F39:0101.000C" / "input" / "input32"),
                       ("event26", usb / "5-2.4:1.1" / "0003:0F39:0101.000D" / "input" / "input33"),
                       ("event27", usb / "5-2.4:1.1" / "0003:0F39:0101.000D" / "input" / "input34"),
                       ("event6", other / "5-1:1.0" / "0003:046D:C548.0001" / "input" / "input6")):
        parent.mkdir(parents=True)
        (sysfs / ev).mkdir()
        (sysfs / ev / "device").symlink_to(parent)
        (devdir / ev).write_text("")
    kbd = devdir / "by-id" / "usb-Heng_Yu_Technology_M4220-event-kbd"
    kbd.symlink_to(devdir / "event25")
    return str(kbd), str(sysfs), str(devdir)


def test_device_nodes_finds_every_node_of_the_same_usb_device(tmp_path):
    # udev makes one by-id link per interface, so "Consumer Control" (event27)
    # has none; the sysfs walk still finds it. The unrelated keyboard is left alone.
    kbd, sysfs, devdir = _fake_sysfs(tmp_path)
    nodes = bb.device_nodes(kbd, sysfs=sysfs, devdir=devdir)
    assert nodes[0] == kbd
    assert [os.path.basename(n) for n in nodes[1:]] == ["event26", "event27"]


def test_device_nodes_without_sysfs_is_just_the_keyboard(tmp_path):
    kbd = tmp_path / "kbd"
    kbd.write_text("")
    assert bb.device_nodes(str(kbd), sysfs=str(tmp_path / "nope")) == [str(kbd)]


class FakeRunner:
    def __init__(self, fail=False):
        self.done, self.fail = [], fail

    def do(self, action):
        if self.fail:
            raise ActionError("web API: down")
        self.done.append(action)


def make_service(tmp_path, runner=None):
    status = bb.StatusWriter(str(tmp_path / "s.json"))
    svc = bb.Service(runner or FakeRunner(), bb.MapWatcher(str(tmp_path / "m.json")),
                     status, opener=lambda: None, sleep=lambda s: None)
    return svc


def test_handle_press_runs_action_and_records(tmp_path):
    svc = make_service(tmp_path)
    svc.handle(G, 1)
    assert svc.runner.done == ["mode_next"]
    st = json.loads((tmp_path / "s.json").read_text())
    assert st["last_press"]["button"] == "next" and st["error"] is None


def test_handle_press_api_error_sets_error(tmp_path):
    svc = make_service(tmp_path, runner=FakeRunner(fail=True))
    svc.handle(G, 1)                       # must not raise
    st = json.loads((tmp_path / "s.json").read_text())
    assert "down" in st["error"]


def test_run_idles_when_device_missing(tmp_path):
    sleeps = []
    status = bb.StatusWriter(str(tmp_path / "s.json"))
    svc = bb.Service(FakeRunner(), bb.MapWatcher(str(tmp_path / "m.json")), status,
                     opener=lambda: None, sleep=sleeps.append)
    ticks = iter([False, False, False, True])
    svc.run(stop=lambda: next(ticks))
    assert sleeps == [bb.RETRY_S] * 3
    assert json.loads((tmp_path / "s.json").read_text())["connected"] is False


class FakeEvent:
    def __init__(self, code, value, type=1):
        self.type, self.code, self.value = type, code, value


class FakeDevice:
    """Stands in for an evdev InputDevice: a pipe gives select() a real fd."""

    def __init__(self, path, batches, unplug_after=False):
        self.path = path
        self._r, self._w = os.pipe()
        self.batches = list(batches)
        self.unplug_after = unplug_after
        self.closed = self.ungrabbed = False
        os.write(self._w, b"x")

    def fileno(self):
        return self._r

    def read(self):
        if self.batches:
            return self.batches.pop(0)
        if self.unplug_after:
            raise OSError(19, "No such device")
        return []

    def ungrab(self):
        self.ungrabbed = True

    def close(self):
        self.closed = True
        for fd in (self._r, self._w):
            try:
                os.close(fd)
            except OSError:
                pass


def test_run_reads_keys_from_the_keyboard_node_only(tmp_path):
    kbd = FakeDevice("/dev/kbd", [[FakeEvent(G, 1), FakeEvent(G, 0)]])
    sysctl = FakeDevice("/dev/if01", [[FakeEvent(116, 1)]])  # KEY_POWER: ignored
    runner = FakeRunner()
    status = bb.StatusWriter(str(tmp_path / "s.json"))
    svc = bb.Service(runner, bb.MapWatcher(str(tmp_path / "m.json")), status,
                     opener=lambda: [kbd, sysctl], sleep=lambda s: None)
    ticks = iter([False, False, True])
    svc.run(stop=lambda: next(ticks))
    assert runner.done == ["mode_next"]
    assert kbd.ungrabbed and kbd.closed and sysctl.closed


def test_run_survives_unplug_and_reports_disconnected(tmp_path):
    kbd = FakeDevice("/dev/kbd", [], unplug_after=True)
    opens = iter([[kbd], None])
    status = bb.StatusWriter(str(tmp_path / "s.json"))
    svc = bb.Service(FakeRunner(), bb.MapWatcher(str(tmp_path / "m.json")), status,
                     opener=lambda: next(opens), sleep=lambda s: None)
    ticks = iter([False, False, True])
    svc.run(stop=lambda: next(ticks))
    assert kbd.closed
    assert json.loads((tmp_path / "s.json").read_text())["connected"] is False


def test_run_reports_permission_error(tmp_path):
    def opener():
        raise PermissionError(13, "Permission denied")

    status = bb.StatusWriter(str(tmp_path / "s.json"))
    svc = bb.Service(FakeRunner(), bb.MapWatcher(str(tmp_path / "m.json")), status,
                     opener=opener, sleep=lambda s: None)
    ticks = iter([False, True])
    svc.run(stop=lambda: next(ticks))
    assert "Permission denied" in json.loads((tmp_path / "s.json").read_text())["error"]


def test_handle_logs_an_unmapped_key(tmp_path, capsys):
    svc = make_service(tmp_path)
    svc.handle(99, 1)
    assert "unmapped key code 99" in capsys.readouterr().out
    assert svc.runner.done == []


# --- review fixes ----------------------------------------------------------------
class ExplodingRunner:
    def do(self, action):
        raise OSError(28, "No space left on device")


def test_an_action_os_error_is_not_an_unplug(tmp_path):
    # Only select()/read() failures mean the bar went away; an action or status
    # write failing must not drop and re-grab the bar.
    kbd = FakeDevice("/dev/kbd", [[FakeEvent(G, 1)]])
    opens = []
    status = bb.StatusWriter(str(tmp_path / "s.json"))
    svc = bb.Service(ExplodingRunner(), bb.MapWatcher(str(tmp_path / "m.json")), status,
                     opener=lambda: opens.append(1) or [kbd], sleep=lambda s: None)
    ticks = iter([False, False, True])
    svc.run(stop=lambda: next(ticks))
    assert opens == [1]
    st = json.loads((tmp_path / "s.json").read_text())
    assert st["connected"] is True and "No space left" in st["error"]


def test_missing_evdev_is_reported_not_fatal(tmp_path):
    def opener():
        raise ModuleNotFoundError("No module named 'evdev'")

    status = bb.StatusWriter(str(tmp_path / "s.json"))
    svc = bb.Service(FakeRunner(), bb.MapWatcher(str(tmp_path / "m.json")), status,
                     opener=opener, sleep=lambda s: None)
    ticks = iter([False, True])
    svc.run(stop=lambda: next(ticks))
    assert "evdev" in json.loads((tmp_path / "s.json").read_text())["error"]


def test_unplug_clears_the_device_and_an_absent_bar_clears_old_errors(tmp_path):
    kbd = FakeDevice("/dev/kbd", [], unplug_after=True)
    calls = iter(["perm", [kbd], None])

    def opener():
        c = next(calls)
        if c == "perm":
            raise PermissionError(13, "Permission denied")
        return c

    status = bb.StatusWriter(str(tmp_path / "s.json"))
    svc = bb.Service(FakeRunner(), bb.MapWatcher(str(tmp_path / "m.json")), status,
                     opener=opener, sleep=lambda s: None)
    ticks = iter([False, False, False, True])   # perm error, connect+unplug, absent
    svc.run(stop=lambda: next(ticks))
    st = json.loads((tmp_path / "s.json").read_text())
    assert st["connected"] is False and st["device"] is None and st["error"] is None
