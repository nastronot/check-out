"""Daemon-level tests: shutdown, command nonce, animation, status mirror."""

from datetime import datetime

import checkout.daemon as daemon
from checkout.driver import VFDDriver


def _last_tx_bytes(out: str) -> list[str]:
    tx_lines = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("TX")]
    return tx_lines[-1][2:].split()


def _all_tx_bytes(out: str) -> list[int]:
    data: list[int] = []
    for ln in out.splitlines():
        ln = ln.strip()
        if ln.startswith("TX"):
            data.extend(int(t, 16) for t in ln[2:].split())
    return data


NOW = datetime(2026, 6, 19, 12, 0, 0)


# --- command nonce -----------------------------------------------------------
def test_command_nonce_processed_once_then_reprocessed(monkeypatch, capsys):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()

    def tick_with(cmd_id):
        state = {
            "mode": "clock",
            "command": {"id": cmd_id, "action": "self_test", "args": {}},
        }
        capsys.readouterr()  # clear
        daemon.tick_once(drv, state, ctx, now=NOW)
        return _all_tx_bytes(capsys.readouterr().out).count(0x0F)

    assert tick_with("c1") == 1   # first time: self_test runs (emits 0x0F)
    assert tick_with("c1") == 0   # same nonce: not re-run
    assert tick_with("c2") == 1   # new nonce: runs again


def test_command_null_id_is_noop(monkeypatch, capsys):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    state = {"mode": "clock", "command": {"id": None, "action": "self_test"}}
    daemon.tick_once(drv, state, ctx, now=NOW)
    assert 0x0F not in _all_tx_bytes(capsys.readouterr().out)


# --- animation ---------------------------------------------------------------
def test_resolve_emit_none_always_shows():
    p = {"on_ms": 500, "off_ms": 500}
    assert daemon.resolve_emit(0, "none", p, "T", "B") == ("show", "T", "B")
    assert daemon.resolve_emit(999, "none", p, "T", "B") == ("show", "T", "B")


def test_resolve_emit_flash_toggles_to_blank():
    p = {"on_ms": 500, "off_ms": 500}
    assert daemon.resolve_emit(0, "flash", p, "T", "B") == ("show", "T", "B")
    assert daemon.resolve_emit(600, "flash", p, "T", "B") == ("blank",)


def test_resolve_emit_blink_swaps_to_blank_lines():
    p = {"on_ms": 500, "off_ms": 500}
    assert daemon.resolve_emit(0, "blink", p, "T", "B") == ("show", "T", "B")
    off = daemon.resolve_emit(600, "blink", p, "T", "B")
    # blink keeps the display ON: it shows blank LINES, not a real blank().
    assert off == ("show", " " * 20, " " * 20)


def test_flash_animation_toggles_on_clock_in_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    state = {
        "mode": "clock",
        "animation": "flash",
        "animation_params": {"on_ms": 500, "off_ms": 500},
    }
    on_now = datetime(2026, 6, 19, 12, 0, 0, 0)        # phase ON
    off_now = datetime(2026, 6, 19, 12, 0, 0, 600000)  # phase OFF (same second)

    capsys.readouterr()
    daemon.tick_once(drv, state, ctx, now=on_now)
    on_bytes = _all_tx_bytes(capsys.readouterr().out)
    assert 0x10 in on_bytes  # a show() frame (DisplayPosition) was emitted

    daemon.tick_once(drv, state, ctx, now=off_now)
    off_bytes = _all_tx_bytes(capsys.readouterr().out)
    # OFF phase blanks: init-seq + cursor-off, and no show() this tick.
    assert off_bytes == [0x1F, 0x00, 0x01, 0x11, 0x14]


# --- status mirror -----------------------------------------------------------
def test_status_written_with_expected_fields(monkeypatch):
    written = []
    monkeypatch.setattr(daemon, "save_status", lambda s: written.append(s))
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    state = {"mode": "clock", "brightness": "dim", "blank": False, "scroll": False}
    daemon.tick_once(drv, state, ctx, now=NOW)

    assert written, "status should be written"
    status = written[-1]
    for key in ("alive", "mode", "top", "bottom", "brightness", "blank",
                "scroll", "last_command_id"):
        assert key in status
    assert status["alive"] is True
    assert status["mode"] == "clock"
    assert len(status["top"]) == 20 and len(status["bottom"]) == 20


def test_shutdown_blanks_with_cursor_hidden(monkeypatch, capsys):
    """The shutdown path must end in 0x14 (blank), not a bare clear."""
    drv = VFDDriver(dry_run=True)
    monkeypatch.setattr(daemon, "open_driver", lambda dry_run: drv)
    monkeypatch.setattr(daemon.time, "sleep", lambda s: None)
    monkeypatch.setattr(daemon, "BANNER_SECONDS", 0)
    # Request shutdown before the loop body runs.
    monkeypatch.setattr(daemon, "_stop", True)

    rc = daemon.run(dry_run=True)
    assert rc == 0

    last = _last_tx_bytes(capsys.readouterr().out)
    # blank() re-inits (reset + extended mode + scroll off) then cursor-off LAST,
    # so the exit screen is dark, no cursor block, and never in scroll mode.
    assert last == ["1F", "00", "01", "11", "14"]
    assert last[-1] == "14"
    # Port closed cleanly (dry-run driver has no open handle).
    assert drv._serial is None


class _CountingDriver:
    """Full no-op driver that records show()/blank() calls without a port."""

    port = "fake"
    baud = 9600

    def __init__(self):
        self.shows = 0
        self.blanks = 0

    def initialize(self):
        pass

    def clear(self):
        pass

    def reset(self):
        pass

    def self_test(self):
        pass

    def define_character(self, index, rows7):
        pass

    def select_code_page(self, page):
        pass

    def set_brightness(self, level):
        pass

    def set_vertical_scroll(self, enabled):
        pass

    def show(self, top, bottom):
        self.shows += 1

    def blank(self):
        self.blanks += 1

    def close(self):
        pass


def test_show_emitted_once_per_change_no_double_write(monkeypatch):
    """A tick emits at most one show/blank, and re-shows only when content changes."""
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = _CountingDriver()
    ctx = daemon._new_ctx()
    state = {"mode": "clock"}

    t0 = datetime(2026, 6, 19, 12, 0, 0)
    daemon.tick_once(drv, state, ctx, now=t0)
    assert drv.shows == 1                      # first frame drawn
    daemon.tick_once(drv, state, ctx, now=t0)  # same second -> no change
    assert drv.shows == 1                      # not redrawn (never double-write)

    daemon.tick_once(drv, state, ctx, now=datetime(2026, 6, 19, 12, 0, 1))
    assert drv.shows == 2                      # clock advanced -> one redraw
    assert drv.blanks == 0


def test_blank_state_blanks_once_then_latches(monkeypatch):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = _CountingDriver()
    ctx = daemon._new_ctx()
    state = {"mode": "clock", "blank": True}

    daemon.tick_once(drv, state, ctx, now=NOW)
    daemon.tick_once(drv, state, ctx, now=NOW)
    assert drv.blanks == 1  # latched: blanked once, not every tick
    assert drv.shows == 0


def test_status_heartbeat_advances_without_re_pushing_display(monkeypatch):
    """Liveness (status heartbeat) is separate from content change (serial writes).

    With identical content across ticks, status.json is still rewritten each tick
    (heartbeat advances, so the UI stays ALIVE), but the display is drawn only
    once — emit-diffing to the serial port is preserved.
    """
    written = []
    monkeypatch.setattr(daemon, "save_status", lambda s: written.append(s))
    drv = _CountingDriver()
    ctx = daemon._new_ctx()
    state = {"mode": "clock"}
    t = datetime(2026, 6, 19, 12, 0, 0)  # same instant -> identical top/bottom

    daemon.tick_once(drv, state, ctx, now=t)
    daemon.tick_once(drv, state, ctx, now=t)
    daemon.tick_once(drv, state, ctx, now=t)

    # Status written EVERY tick with a monotonically increasing heartbeat...
    assert [s["heartbeat"] for s in written] == [1, 2, 3]
    assert all(s["alive"] is True for s in written)
    # ...while the display was pushed only ONCE (unchanged frame not re-sent).
    assert drv.shows == 1
    assert drv.blanks == 0


def test_invalid_brightness_coerced_once_no_spam(monkeypatch):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    warnings = []
    monkeypatch.setattr(daemon, "log", lambda m: warnings.append(m))
    levels = []
    drv = _CountingDriver()
    drv.set_brightness = lambda level: levels.append(level)
    ctx = daemon._new_ctx()
    state = {"mode": "clock", "brightness": "neon"}  # invalid

    for _ in range(3):
        daemon.tick_once(drv, state, ctx, now=NOW)

    # Coerced to a valid level exactly once, then cached (no per-tick re-write).
    assert levels == ["bright"]
    # And warned exactly once — not every tick.
    assert sum("invalid brightness" in w for w in warnings) == 1


def test_reset_command_reapplies_scroll_and_settings_next_tick(monkeypatch, capsys):
    """After a display-resetting command, the NEXT tick re-emits scroll/brightness/
    code-page (cache invalidated) so the display can't stay stuck in scroll mode."""
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()

    # A normal tick establishes the caches (scroll disabled, brightness, etc.).
    daemon.tick_once(drv, {"mode": "clock"}, ctx, now=NOW)
    capsys.readouterr()  # clear

    # self_test tick: runs the command, then early-returns — no settings re-apply
    # this tick (the panel is still re-initializing and would swallow them).
    cmd_state = {"mode": "clock", "command": {"id": "c1", "action": "self_test"}}
    daemon.tick_once(drv, cmd_state, ctx, now=NOW)
    cmd_tx = _all_tx_bytes(capsys.readouterr().out)
    assert 0x0F in cmd_tx  # self-test ran
    # No frame drawn this tick (early return after the reset).
    assert [0x10, 0x00] not in [cmd_tx[i : i + 2] for i in range(len(cmd_tx) - 1)]

    # The next normal tick re-applies settings from the invalidated caches.
    daemon.tick_once(drv, {"mode": "clock"}, ctx, now=datetime(2026, 6, 19, 12, 0, 1))
    next_tx = _all_tx_bytes(capsys.readouterr().out)
    assert 0x11 in next_tx  # vertical-scroll DISABLE re-sent (the desync fix)
    assert 0x04 in next_tx  # brightness re-sent
    assert 0x02 in next_tx  # code page re-sent


def test_valid_brightness_after_invalid_rewarns(monkeypatch):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    warnings = []
    monkeypatch.setattr(daemon, "log", lambda m: warnings.append(m))
    levels = []
    drv = _CountingDriver()
    drv.set_brightness = lambda level: levels.append(level)
    ctx = daemon._new_ctx()

    daemon.tick_once(drv, {"brightness": "neon"}, ctx, now=NOW)   # bad -> bright
    daemon.tick_once(drv, {"brightness": "dim"}, ctx, now=NOW)    # valid -> dim
    daemon.tick_once(drv, {"brightness": "neon"}, ctx, now=NOW)   # bad again -> bright
    assert levels == ["bright", "dim", "bright"]
    # The intervening valid value clears the dedupe, so the second bad value warns.
    assert sum("invalid brightness" in w for w in warnings) == 2
