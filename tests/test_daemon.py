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


def test_resolve_emit_blink_never_blanks_and_differs_from_flash():
    p = {"on_ms": 500, "off_ms": 500}
    # blink shows the SAME frame both phases — it pulses via brightness, not blank.
    assert daemon.resolve_emit(0, "blink", p, "T", "B") == ("show", "T", "B")
    assert daemon.resolve_emit(600, "blink", p, "T", "B") == ("show", "T", "B")
    # The off-phase differs from flash: flash blanks, blink keeps the frame.
    flash_off = daemon.resolve_emit(600, "flash", p, "T", "B")
    blink_off = daemon.resolve_emit(600, "blink", p, "T", "B")
    assert flash_off == ("blank",)
    assert blink_off != flash_off


def test_blink_pulses_brightness_min_on_off_phase():
    p = {"on_ms": 500, "off_ms": 500}
    # on-phase keeps the base level; off-phase pulses down to MIN (0).
    assert daemon.animation_brightness(0, "blink", p, 3) == 3
    assert daemon.animation_brightness(600, "blink", p, 3) == 0
    # flash/none never touch brightness.
    assert daemon.animation_brightness(600, "flash", p, 3) == 3
    assert daemon.animation_brightness(600, "none", p, 2) == 2


def test_pulse_is_a_triangle_wave_through_four_levels():
    p = {"step_ms": 100}
    # One step per 100ms -> the level sweeps 0,1,2,3,2,1, then repeats.
    seq = [daemon.animation_brightness(t * 100, "pulse", p, 3) for t in range(12)]
    assert seq == [0, 1, 2, 3, 2, 1, 0, 1, 2, 3, 2, 1]
    # pulse OVERRIDES the static base (sweeps the full range regardless of base).
    assert daemon.animation_brightness(0, "pulse", p, 1) == 0
    assert daemon.animation_brightness(300, "pulse", p, 1) == 3


def test_pulse_distinct_from_blink_and_flash():
    p = {"on_ms": 500, "off_ms": 500, "step_ms": 100}
    # pulse never blanks (resolve_emit always shows the frame)...
    assert daemon.resolve_emit(300, "pulse", p, "T", "B") == ("show", "T", "B")
    # ...and it's a 4-level sweep, not blink's 2-state snap (0 or base):
    pulse_levels = {daemon.animation_brightness(t * 100, "pulse", p, 3) for t in range(6)}
    blink_levels = {daemon.animation_brightness(t * 100, "blink", p, 3) for t in range(20)}
    assert pulse_levels == {0, 1, 2, 3}
    assert blink_levels == {0, 3}  # blink only snaps between MIN and the base


# --- software scroll (mode "scroll") -----------------------------------------
def test_render_scroll_top_only_left():
    state = {
        "message": "A LONG MESSAGE THAT SCROLLS ACROSS THE TOP ROW",
        "scroll_top": True,
        "scroll_bottom": False,
        "scroll_dir_top": "left",
        "scroll_speed_ms": 100,
    }
    top0, bottom0 = daemon.render_scroll(state, 0)
    top1, _ = daemon.render_scroll(state, 300)  # +3 steps
    assert len(top0) == 20 and top0 != top1   # top scrolls
    assert bottom0 == " " * 20                  # bottom static + empty


def test_render_scroll_direction_reverses_offset():
    state = {
        "message": "0123456789ABCDEFGHIJKLMNOPQRST",
        "scroll_top": True,
        "scroll_dir_top": "left",
        "scroll_speed_ms": 100,
    }
    left = daemon.render_scroll({**state, "scroll_dir_top": "left"}, 300)[0]
    right = daemon.render_scroll({**state, "scroll_dir_top": "right"}, 300)[0]
    base = daemon.render_scroll(state, 0)[0]
    assert left != right          # opposite directions diverge
    assert left != base and right != base


def test_render_scroll_both_rows_independent():
    state = {
        "message": "TOP LINE IS LONG ENOUGH TO SCROLL\nBOTTOM LINE ALSO LONG ENOUGH",
        "scroll_top": True,
        "scroll_bottom": True,
        "scroll_dir_top": "left",
        "scroll_dir_bottom": "right",
        "scroll_speed_ms": 100,
    }
    top, bottom = daemon.render_scroll(state, 500)
    assert len(top) == 20 and len(bottom) == 20
    assert top.strip() and bottom.strip()


def test_scroll_speed_clamped_to_floor():
    # A 1ms request can't outrun the floor: it advances at SCROLL_FLOOR_MS.
    state = {"message": "X" * 40, "scroll_top": True, "scroll_dir_top": "left",
             "scroll_speed_ms": 1}
    # Within one floor window the offset is identical (no per-1ms stepping).
    a = daemon.render_scroll(state, daemon.SCROLL_FLOOR_MS - 1)[0]
    b = daemon.render_scroll(state, 0)[0]
    assert a == b


def test_render_scroll_clock_source_shows_time_and_ticks(monkeypatch):
    # A row whose source is "clock" shows the TIME line and updates each second.
    state = {
        "message": "IGNORED TOP\nIGNORED BOTTOM",
        "scroll_top_source": "clock",
        "scroll_bottom_source": "message",
    }
    t0 = datetime(2026, 6, 19, 12, 0, 0)
    t1 = datetime(2026, 6, 19, 12, 0, 1)
    top0, bottom0 = daemon.render_scroll(state, 0, t0)
    top1, _ = daemon.render_scroll(state, 0, t1)
    assert top0.strip() == "12:00:00 PM"   # clock TIME line, not the message
    assert top1.strip() == "12:00:01 PM"   # ticks each second
    assert bottom0.strip() == "IGNORED BOTTOM"  # message row unaffected


def test_render_scroll_mixed_clock_top_scrolling_message_bottom():
    # Top clock (static, refreshed) + bottom scrolling message both render 20-wide.
    state = {
        "message": "\nA LONG BOTTOM MESSAGE THAT SCROLLS ACROSS THE ROW",
        "scroll_top_source": "clock",
        "scroll_bottom_source": "message",
        "scroll_bottom": True,
        "scroll_dir_bottom": "left",
        "scroll_speed_ms": 100,
    }
    now = datetime(2026, 6, 19, 12, 0, 0)
    b0 = daemon.render_scroll(state, 0, now)[1]
    b1 = daemon.render_scroll(state, 300, now)[1]
    top = daemon.render_scroll(state, 0, now)[0]
    assert top.strip() == "12:00:00 PM"
    assert len(b0) == 20 and b0 != b1  # bottom message scrolls


def test_legacy_ticker_mode_renders_as_scroll(monkeypatch):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = _CountingDriver()
    ctx = daemon._new_ctx()
    # mode "ticker" (legacy) must drive the scroll path, not crash / blank.
    state = {"mode": "ticker", "message": "X" * 40, "scroll_top": True}
    daemon.tick_once(drv, state, ctx, now=NOW)
    assert drv.shows == 1


# --- marquee (hardware ticker) -----------------------------------------------
def test_marquee_starts_ticker_once_and_writes_static_bottom(monkeypatch, capsys):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    state = {"mode": "marquee", "marquee_text": "HELLO NEWS",
             "marquee_bottom_text": "BOTTOM"}

    capsys.readouterr()
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 6, 19, 12, 0, 0))
    t1 = _all_tx_bytes(capsys.readouterr().out)
    assert 0x05 in t1                       # ticker started
    assert t1[t1.index(0x05) + 1:].count(0x0D) >= 1
    assert [0x10, 0x14] in [t1[i:i + 2] for i in range(len(t1) - 1)]  # bottom written

    # Next tick (+1s): same marquee text + STATIC bottom -> nothing re-sent (no
    # ticker re-kick, no bottom rewrite). The bottom is static, never a clock.
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 6, 19, 12, 0, 1))
    assert _all_tx_bytes(capsys.readouterr().out) == []


def test_marquee_clock_bottom_request_is_static_only(monkeypatch):
    """A legacy marquee_bottom='clock' must NOT drive a live clock — it's ignored
    (static-only), so the bottom is the static text and never ticks per second."""
    written = []
    monkeypatch.setattr(daemon, "save_status", lambda s: written.append(s))
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    state = {"mode": "marquee", "marquee_text": "HI", "marquee_bottom": "clock",
             "marquee_bottom_text": "STATIC BOTTOM"}
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 6, 19, 12, 0, 0))
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 6, 19, 12, 0, 1))
    # Bottom is the static text both ticks (no AM/PM clock, no per-second change).
    assert written[-1]["bottom"].strip() == "STATIC BOTTOM"
    assert ":" not in written[-1]["bottom"]


def test_marquee_preview_top_advances_each_tick(monkeypatch):
    """status.top is a software preview window that MOVES every tick even with a
    fixed `now` (it advances a per-tick offset, not wall-clock)."""
    written = []
    monkeypatch.setattr(daemon, "save_status", lambda s: written.append(s))
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    state = {"mode": "marquee",
             "marquee_text": "A LONG MARQUEE MESSAGE THAT SCROLLS ON THE TOP ROW"}
    daemon.tick_once(drv, state, ctx, now=NOW)
    daemon.tick_once(drv, state, ctx, now=NOW)  # SAME now
    daemon.tick_once(drv, state, ctx, now=NOW)
    tops = [w["top"] for w in written]
    assert len(set(tops)) == 3  # advances tick to tick despite a fixed clock


def test_marquee_ignores_animation_regardless_of_state(monkeypatch, capsys):
    """Marquee forces animation "none": a leftover flash/blink/pulse from another
    mode must NOT blank the frame or pulse brightness on the marquee path."""
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    # A blink/pulse base would pulse brightness; flash would blank on the off
    # phase. None of that should happen in marquee.
    off_now = datetime(2026, 6, 19, 12, 0, 0, 600000)  # flash/blink OFF phase
    for anim in ("flash", "blink", "pulse"):
        ctx = daemon._new_ctx()
        state = {
            "mode": "marquee", "marquee_text": "NEWS", "marquee_bottom_text": "X",
            "brightness": 3, "animation": anim,
            "animation_params": {"on_ms": 500, "off_ms": 500, "step_ms": 100},
        }
        capsys.readouterr()
        daemon.tick_once(drv, state, ctx, now=off_now)
        tx = _all_tx_bytes(capsys.readouterr().out)
        assert 0x1F not in tx, f"{anim}: marquee must not blank/reset (flash)"
        # Brightness, if emitted, is the static MAX (0xFF) — never a pulsed level.
        if 0x04 in tx:
            assert tx[tx.index(0x04) + 1] == 0xFF, f"{anim}: brightness not pulsed"
        assert 0x05 in tx  # the ticker still runs


def test_marquee_re_kicks_ticker_after_reset(monkeypatch, capsys):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    state = {"mode": "marquee", "marquee_text": "NEWS", "marquee_bottom_text": "X"}
    daemon.tick_once(drv, state, ctx, now=NOW)  # starts ticker
    capsys.readouterr()

    # A reset command early-returns; the NEXT marquee tick must re-start the ticker.
    cmd = {**state, "command": {"id": "r1", "action": "reset"}}
    daemon.tick_once(drv, cmd, ctx, now=NOW)
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 6, 19, 12, 0, 2))
    after = _all_tx_bytes(capsys.readouterr().out)
    assert 0x05 in after  # ticker re-kicked after the reset


def test_marquee_static_bottom_only_updates_on_change(monkeypatch, capsys):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    state = {"mode": "marquee", "marquee_text": "HI", "marquee_bottom": "static",
             "marquee_bottom_text": "STATIC"}
    daemon.tick_once(drv, state, ctx, now=NOW)
    capsys.readouterr()
    # Same static bottom + same marquee text -> nothing re-sent next tick.
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 6, 19, 12, 0, 5))
    assert _all_tx_bytes(capsys.readouterr().out) == []


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


def test_blink_off_phase_pulses_brightness_not_blank(monkeypatch, capsys):
    """blink's off-phase dims (0x04 0x20) and keeps the frame — never blanks."""
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    state = {
        "mode": "clock",
        "brightness": 3,
        "animation": "blink",
        "animation_params": {"on_ms": 500, "off_ms": 500},
    }
    on_now = datetime(2026, 6, 19, 12, 0, 0, 0)        # phase ON  -> level 3 (0xFF)
    off_now = datetime(2026, 6, 19, 12, 0, 0, 600000)  # phase OFF -> level 0 (0x20)

    capsys.readouterr()
    daemon.tick_once(drv, state, ctx, now=on_now)
    on_bytes = _all_tx_bytes(capsys.readouterr().out)
    assert [0x04, 0xFF] == on_bytes[on_bytes.index(0x04):on_bytes.index(0x04) + 2]

    daemon.tick_once(drv, state, ctx, now=off_now)
    off_bytes = _all_tx_bytes(capsys.readouterr().out)
    # Off-phase pulses brightness DOWN to MIN...
    assert 0x04 in off_bytes
    assert off_bytes[off_bytes.index(0x04):off_bytes.index(0x04) + 2] == [0x04, 0x20]
    # ...and it does NOT blank (no reset/init-seq this tick).
    assert 0x1F not in off_bytes


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
    # Status carries the APPLIED brightness index (legacy "dim" -> 0).
    assert status["brightness"] == 0
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

    # Coerced to the default index (3=Maximum) exactly once, then cached.
    assert levels == [3]
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

    daemon.tick_once(drv, {"brightness": "neon"}, ctx, now=NOW)  # bad -> 3 (default)
    daemon.tick_once(drv, {"brightness": 0}, ctx, now=NOW)       # valid -> 0
    daemon.tick_once(drv, {"brightness": "neon"}, ctx, now=NOW)  # bad again -> 3
    assert levels == [3, 0, 3]
    # The intervening valid value clears the dedupe, so the second bad value warns.
    assert sum("invalid brightness" in w for w in warnings) == 2
