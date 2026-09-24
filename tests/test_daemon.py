"""Daemon-level tests: shutdown, command nonce, animation, status mirror."""

from datetime import datetime, timedelta

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


def test_legacy_ticker_and_scroll_modes_render_as_message(monkeypatch):
    written = []
    monkeypatch.setattr(daemon, "save_status", lambda s: written.append(s))
    for legacy in ("ticker", "scroll"):
        drv = _CountingDriver()
        # Legacy modes must drive the merged message path, not crash / blank.
        state = {"mode": legacy, "message": "X" * 40, "scroll_top": True}
        daemon.tick_once(drv, state, daemon._new_ctx(), now=NOW)
        assert drv.shows == 1, legacy
        assert written[-1]["top"].strip() == "X" * 20, legacy


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


def test_marquee_preview_top_advances_over_time(monkeypatch):
    """status.top is a software preview window that MOVES as wall-clock advances
    (a TIME-based offset now, so the fast loop's iteration count doesn't matter)."""
    written = []
    monkeypatch.setattr(daemon, "save_status", lambda s: written.append(s))
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    state = {"mode": "marquee",
             "marquee_text": "A LONG MARQUEE MESSAGE THAT SCROLLS ON THE TOP ROW"}
    # Advance ~300ms between ticks: past both the status throttle and the preview
    # step, so each write lands a distinct window.
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 6, 19, 12, 0, 0, 0))
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 6, 19, 12, 0, 0, 300000))
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 6, 19, 12, 0, 0, 600000))
    tops = [w["top"] for w in written]
    assert len(set(tops)) == 3  # advances as time passes


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


def test_marquee_substitutes_glyph_placeholders(monkeypatch, capsys):
    """The hardware ticker renders user glyphs, so {gN} in marquee_text must be
    substituted to the glyph CODE byte before start_ticker — not sent literally."""
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    state = {"mode": "marquee", "marquee_text": "TEMP {g0}C",
             "marquee_bottom_text": "HI {g2}"}
    capsys.readouterr()
    daemon.tick_once(drv, state, ctx, now=NOW)
    tx = _all_tx_bytes(capsys.readouterr().out)
    # Ticker payload starts at 0x05; the glyph code 0x15 (slot 0) is in it, and the
    # literal token bytes '{','g','0','}' are NOT.
    assert 0x05 in tx
    assert 0x15 in tx                       # {g0} -> 0x15
    assert ord("{") not in tx and ord("}") not in tx
    # Bottom (0x10 0x14 ...) carries slot 2's code 0x17 ({g2}).
    assert 0x17 in tx


def test_marquee_glyph_limit_counted_post_substitution(monkeypatch, capsys):
    """45-char buffer limit counts RENDERED cells: a {g0} after 44 chars (raw token
    pushes past 45, but the glyph is cell 45) must survive as its code byte."""
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    # 44 'A' + "{g0}" -> raw 48 chars, substituted 45 cells (44 A's + glyph).
    state = {"mode": "marquee", "marquee_text": "A" * 44 + "{g0}"}
    capsys.readouterr()
    daemon.tick_once(drv, state, ctx, now=NOW)
    tx = _all_tx_bytes(capsys.readouterr().out)
    # Post-substitution truncation keeps the 45th cell (the glyph code); raw-token
    # truncation would have cut mid-"{g0}" and lost it.
    assert 0x15 in tx


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


# --- single fast loop (emit-diff + status throttle + per-mode elapsed timing) --
def test_fast_loop_clock_emits_once_per_second_and_throttles_status(monkeypatch):
    """Many fast iterations within a second emit the clock ONCE (emit-diff) and
    write status only on its throttle — not once per iteration."""
    written = []
    monkeypatch.setattr(daemon, "save_status", lambda s: written.append(s))
    drv = _CountingDriver()
    ctx = daemon._new_ctx()
    state = {"mode": "clock"}

    base = datetime(2026, 6, 19, 12, 0, 0)
    # 30 iterations across one second (~33ms apart) — the clock frame is constant.
    for i in range(30):
        daemon.tick_once(
            drv, state, ctx, now=base.replace(microsecond=i * 33_000)
        )
    # Display drawn once (the second's frame never changed).
    assert drv.shows == 1
    # Status throttled well below 30 writes (≈ STATUS_HZ over ~1s).
    assert 1 <= len(written) <= 12
    # Next second -> the clock frame changes -> exactly one more draw.
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 6, 19, 12, 0, 1))
    assert drv.shows == 2


def test_fast_loop_scroll_steps_on_elapsed_time(monkeypatch):
    """Scroll advances by ELAPSED time (now_ms // speed), independent of how many
    fast iterations happen — so it steps at scroll_speed_ms, not the loop rate."""
    from datetime import timedelta

    from checkout.frames.message import MessageFrame

    state = {
        "mode": "message",
        "message": "A LONG SCROLLING MESSAGE ACROSS THE TOP ROW OF THE DISPLAY",
        "scroll_top": True, "scroll_dir_top": "left", "scroll_speed_ms": 200,
    }
    t0 = datetime.fromtimestamp(0)
    # Two instants in the SAME 200ms window render identically; crossing the
    # window boundary advances the window.
    a, b, c = (MessageFrame().render(t0 + timedelta(milliseconds=ms), state)[0]
               for ms in (0, 199, 200))
    assert a == b      # same step window
    assert a != c      # advanced after speed_ms elapsed


# --- spectrum mode -----------------------------------------------------------
class _FakeRx:
    """A SpectrumReceiver stand-in: drain() yields queued frames (latest each)."""
    def __init__(self, frames=None):
        self.frames = list(frames or [])
    def drain(self):
        if not self.frames:
            return None
        frame = self.frames[-1]   # newest-wins
        self.frames = []
        return frame


def _spectrum_ctx():
    ctx = daemon._new_ctx()
    ctx["spectrum_rx_failed"] = True   # don't bind a real socket in tests
    return ctx


def _full(heights):
    """A decoded full-layout frame (what the real SpectrumReceiver.drain returns)."""
    return {"layout": "full", "heights": list(heights)}


def test_spectrum_enter_defines_seven_bar_glyphs(monkeypatch, capsys):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = _spectrum_ctx()
    ctx["spectrum_rx"] = _FakeRx([_full([7] * 20)])
    capsys.readouterr()
    daemon.tick_once(drv, {"mode": "spectrum"}, ctx, now=NOW)
    tx = _all_tx_bytes(capsys.readouterr().out)
    assert tx.count(0x03) == 7          # 7 DefineCharacter writes (height glyphs)
    assert ctx["mode_glyphs_key"] == ("spectrum", "full", "bars")


def test_spectrum_drains_latest_and_renders_bars(monkeypatch):
    written = []
    monkeypatch.setattr(daemon, "save_status", lambda s: written.append(s))
    drv = _CountingDriver()
    ctx = _spectrum_ctx()
    # A burst of frames in the queue: the newest ([14]*20) wins.
    ctx["spectrum_rx"] = _FakeRx([_full([1] * 20), _full([9] * 20), _full([14] * 20)])
    daemon.tick_once(drv, {"mode": "spectrum"}, ctx, now=NOW)
    assert ctx["spectrum_heights"] == [14] * 20
    assert written[-1]["mode"] == "spectrum"
    assert written[-1]["bars"] == [14] * 20
    assert drv.shows == 1               # bars drawn


def test_spectrum_decays_to_zero_when_stale(monkeypatch):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = _CountingDriver()
    ctx = _spectrum_ctx()
    ctx["spectrum_rx"] = _FakeRx([])    # nothing arriving
    ctx["spectrum_heights"] = [10] * 20
    ctx["spectrum_recv_ms"] = 0         # last frame long ago
    # now well past SPECTRUM_STALE_MS -> bars decay one step per tick.
    t0 = datetime(2026, 6, 19, 12, 0, 0)
    daemon.tick_once(drv, {"mode": "spectrum"}, ctx, now=t0)
    assert ctx["spectrum_heights"] == [9] * 20
    daemon.tick_once(drv, {"mode": "spectrum"}, ctx,
                     now=datetime(2026, 6, 19, 12, 0, 0, 250_000))
    assert ctx["spectrum_heights"] == [8] * 20


def test_spectrum_restores_user_glyphs_on_exit(monkeypatch, capsys):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = _spectrum_ctx()
    ctx["spectrum_rx"] = _FakeRx([_full([5] * 20)])
    daemon.tick_once(drv, {"mode": "spectrum"}, ctx, now=NOW)   # enter: bar glyphs
    capsys.readouterr()
    # Leave to a mode whose state carries a user glyph -> it must be re-defined.
    state = {"mode": "clock", "glyphs": {"0": [1, 2, 4, 8, 16, 1, 2]}}
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 6, 19, 12, 0, 1))
    tx = _all_tx_bytes(capsys.readouterr().out)
    assert ctx["mode_glyphs_key"] is None
    assert 0x03 in tx                  # user glyph re-defined (restored)


def _parse_defines(tx):
    """Extract {code: [7 wire rows]} from DefineCharacter (0x03 code rows.. 0x00)."""
    out = {}
    i = 0
    while i < len(tx):
        if tx[i] == 0x03 and i + 9 < len(tx) and tx[i + 9] == 0x00:
            out[tx[i + 1]] = tx[i + 2 : i + 9]
            i += 10
        else:
            i += 1
    return out


def test_spectrum_enters_with_active_style_default_bars(monkeypatch, capsys):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = _spectrum_ctx()
    ctx["spectrum_rx"] = _FakeRx([_full([7] * 20)])
    daemon.tick_once(drv, {"mode": "spectrum"}, ctx, now=NOW)
    assert ctx["mode_glyphs_key"][2] == "bars"   # default style defined on enter


def test_spectrum_style_change_redefines_glyph_slots(monkeypatch, capsys):
    from checkout import spectrum

    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = _spectrum_ctx()
    ctx["spectrum_rx"] = _FakeRx([_full([14] * 20)])
    # Enter with the default BARS style.
    daemon.tick_once(drv, {"mode": "spectrum"}, ctx, now=NOW)
    assert ctx["mode_glyphs_key"][2] == "bars"
    capsys.readouterr()  # discard the enter TX

    # Flip to LINE mid-spectrum: it must redefine the 7 slots with the LINE set.
    state = {"mode": "spectrum", "spectrum_style": "line"}
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 6, 19, 12, 0, 0, 250_000))
    tx = _all_tx_bytes(capsys.readouterr().out)
    assert ctx["mode_glyphs_key"][2] == "line"

    defines = _parse_defines(tx)
    assert len(defines) == 7                 # all 7 slots redefined
    # The defined rows are the LINE set (single lit row each), not the bar set.
    full_row = (0x1F & 0x1F) << 3            # 0xF8, the driver's wire byte for a lit row
    for slot, code in zip(spectrum.BAR_GLYPH_SLOTS, [spectrum.GLYPH_CODES[s] for s in spectrum.BAR_GLYPH_SLOTS]):
        rows = list(defines[code])
        assert rows.count(full_row) == 1     # exactly ONE lit row (a line, not a bar)
    # Slot 6 (height 7) differs between the sets: bar = all rows lit, line = one.
    bar6 = [(r & 0x1F) << 3 for r in spectrum.bar_glyph(7)]
    line6 = [(r & 0x1F) << 3 for r in spectrum.line_glyph(7)]
    assert list(defines[spectrum.GLYPH_CODES[6]]) == line6 != bar6


def test_spectrum_layout_change_redefines_glyphs_and_renders_stereo(monkeypatch):
    from checkout import spectrum

    written = []
    monkeypatch.setattr(daemon, "save_status", lambda s: written.append(s))
    drv = _CountingDriver()
    ctx = _spectrum_ctx()
    # Enter FULL (7 height glyphs), then switch to STEREO_V (9 glyphs: 7 + L/R).
    ctx["spectrum_rx"] = _FakeRx([_full([14] * 20)])
    daemon.tick_once(drv, {"mode": "spectrum", "spectrum_layout": "full"}, ctx, now=NOW)
    assert ctx["mode_glyphs_key"] == ("spectrum", "full", "bars")
    base_defines = drv.defines

    ctx["spectrum_rx"] = _FakeRx([
        {"layout": "stereo_v", "left": [7] * 19, "right": [2] * 19}])
    daemon.tick_once(drv, {"mode": "spectrum", "spectrum_layout": "stereo_v"}, ctx,
                     now=datetime(2026, 6, 19, 12, 0, 0, 250_000))
    assert ctx["mode_glyphs_key"] == ("spectrum", "stereo_v", "bars")
    assert drv.defines - base_defines == 9          # 9 glyphs defined for stereo_v
    assert ctx["spectrum_left"] == [7] * 19 and ctx["spectrum_right"] == [2] * 19
    # status mirrors the layout + per-channel data for the preview.
    assert written[-1]["spectrum_layout"] == "stereo_v"
    assert written[-1]["spectrum_left"] == [7] * 19
    assert written[-1]["bars"] is None


def test_spectrum_ignores_frame_of_wrong_layout(monkeypatch):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = _CountingDriver()
    ctx = _spectrum_ctx()
    ctx["spectrum_level_l"] = 40
    ctx["spectrum_level_r"] = 10
    ctx["spectrum_recv_ms"] = int(NOW.timestamp() * 1000)  # fresh -> no stale decay
    # In stereo_h but a FULL frame arrives -> wrong layout, ignored (levels unchanged).
    ctx["spectrum_rx"] = _FakeRx([_full([14] * 20)])
    daemon.tick_once(drv, {"mode": "spectrum", "spectrum_layout": "stereo_h"}, ctx, now=NOW)
    assert ctx["spectrum_level_l"] == 40 and ctx["spectrum_level_r"] == 10


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
        self.defines = 0

    def initialize(self):
        pass

    def clear(self):
        pass

    def reset(self):
        pass

    def self_test(self):
        pass

    def define_character(self, index, rows7):
        self.defines += 1

    def select_code_page(self, page):
        pass

    def set_brightness(self, level):
        pass

    def set_vertical_scroll(self, enabled):
        pass

    def show(self, top, bottom):
        self.shows += 1

    def show_changes(self, old, new):
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

    With identical content across ticks, status.json is rewritten on its THROTTLE
    (heartbeat advances over time, so the UI stays ALIVE), but the display is
    drawn only once — emit-diffing to the serial port is preserved.
    """
    written = []
    monkeypatch.setattr(daemon, "save_status", lambda s: written.append(s))
    drv = _CountingDriver()
    ctx = daemon._new_ctx()
    state = {"mode": "clock"}
    # Same SECOND (identical clock frame), but advance past the status throttle
    # each call so the heartbeat ticks while the frame stays constant.
    for i in range(3):
        daemon.tick_once(
            drv, state, ctx,
            now=datetime(2026, 6, 19, 12, 0, 0, i * 250_000),  # +250ms each
        )

    # Status written each throttle window with a monotonically increasing heartbeat...
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


def test_mode_glyphs_are_redefined_after_a_reset(monkeypatch):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = _CountingDriver()
    ctx = _spectrum_ctx()
    ctx["spectrum_rx"] = _FakeRx([])
    daemon.tick_once(drv, {"mode": "spectrum"}, ctx, now=NOW)
    first = drv.defines
    daemon._invalidate_caches(ctx)                     # what a reset/reconnect does
    daemon.tick_once(drv, {"mode": "spectrum"}, ctx, now=NOW)
    assert drv.defines == 2 * first


# --- weather mode ------------------------------------------------------------
def test_mode_glyph_sets_round_trip_spectrum_weather_clock(monkeypatch, capsys):
    from checkout import weather
    from checkout.weather import WeatherFetcher

    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    monkeypatch.setattr(daemon.DYNAMIC_FRAME, "fetcher", WeatherFetcher(autostart=False))
    drv = VFDDriver(dry_run=True)
    ctx = _spectrum_ctx()
    ctx["spectrum_rx"] = _FakeRx([])
    user = {"0": [1, 2, 4, 8, 16, 1, 2]}

    daemon.tick_once(drv, {"mode": "spectrum", "glyphs": user}, ctx, now=NOW)
    assert ctx["mode_glyphs_key"] == ("spectrum", "full", "bars")

    capsys.readouterr()
    daemon.tick_once(drv, {"mode": "dynamic", "glyphs": user}, ctx,
                     now=datetime(2026, 6, 19, 12, 0, 1))
    defines = _parse_defines(_all_tx_bytes(capsys.readouterr().out))
    assert ctx["mode_glyphs_key"][1].startswith("clock-")
    assert len(defines) == len(weather.glyph_set("tick")[1])

    capsys.readouterr()
    daemon.tick_once(drv, {"mode": "clock", "glyphs": user}, ctx,
                     now=datetime(2026, 6, 19, 12, 0, 2))
    defines = _parse_defines(_all_tx_bytes(capsys.readouterr().out))
    assert ctx["mode_glyphs_key"] is None
    assert list(defines) == [0x15]                    # the user's slot 0 is back


def _weather_setup(monkeypatch, colon="tick"):
    from checkout.weather import WeatherFetcher

    written = []
    monkeypatch.setattr(daemon, "save_status", lambda s: written.append(s))
    fetcher = WeatherFetcher(autostart=False)
    monkeypatch.setattr(daemon.DYNAMIC_FRAME, "fetcher", fetcher)
    state = {"mode": "dynamic", "weather_lat": 41.9, "weather_lon": -87.6,
             "dynamic_colon": colon}
    return written, fetcher, state


def test_weather_ignores_the_global_animation(monkeypatch, capsys):
    _, _, state = _weather_setup(monkeypatch, colon="on")
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    state = {**state, "animation": "flash", "animation_params": {"on_ms": 500, "off_ms": 500}}
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 9, 23, 20, 33, 12, 600_000))
    assert ctx["last_emit"][0] == "show"                    # flash's dark phase ignored


def test_weather_sets_and_clears_the_fetch_location(monkeypatch):
    _, fetcher, state = _weather_setup(monkeypatch)
    drv = _CountingDriver()
    ctx = daemon._new_ctx()
    daemon.tick_once(drv, state, ctx, now=NOW)
    assert fetcher.due_in(0) == 0                            # wants a fetch
    daemon.tick_once(drv, {"mode": "clock"}, ctx, now=NOW)
    assert fetcher.due_in(0) is None                         # idle outside weather


def test_weather_status_reports_glyphs_and_weather(monkeypatch):
    written, _, state = _weather_setup(monkeypatch)
    drv = _CountingDriver()
    daemon.tick_once(drv, state, daemon._new_ctx(),
                     now=datetime(2026, 9, 23, 20, 33, 12, 100_000))
    s = written[-1]
    assert s["mode"] == "dynamic"
    assert set(s["mode_glyphs"]) == {"0", "1", "2", "3", "4", "8"}   # labels + marker
    assert s["weather"]["error"] is None


def test_clock_status_has_no_mode_glyphs(monkeypatch):
    written = []
    monkeypatch.setattr(daemon, "save_status", lambda s: written.append(s))
    daemon.tick_once(_CountingDriver(), {"mode": "clock"}, daemon._new_ctx(), now=NOW)
    assert written[-1]["mode_glyphs"] is None
    assert written[-1]["weather"] is None


def test_blank_stops_brightness_animation_so_nothing_follows_cursor_off(monkeypatch, capsys):
    # hardware rule 1: any write after 0x14 re-shows the cursor, so a dark screen
    # must stay silent — no pulse brightness writes while blank.
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    state = {"mode": "clock", "animation": "pulse", "blank": True}
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 9, 23, 20, 33, 12, 0))
    capsys.readouterr()
    for ms in range(50, 1000, 50):
        daemon.tick_once(drv, state, ctx, now=datetime(2026, 9, 23, 20, 33, 12, ms * 1000))
    assert _all_tx_bytes(capsys.readouterr().out) == []


# --- weather colon: a character change, written as a one-cell update ----------
def _tx_after(capsys):
    return _all_tx_bytes(capsys.readouterr().out)


def test_weather_tick_rewrites_only_the_colon_cell(monkeypatch, capsys):
    _, _, state = _weather_setup(monkeypatch, colon="tick")
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    t = datetime(2026, 9, 23, 20, 33, 12, 100_000)
    daemon.tick_once(drv, state, ctx, now=t)                     # first frame: full
    capsys.readouterr()
    daemon.tick_once(drv, state, ctx, now=t.replace(microsecond=200_000))
    assert _tx_after(capsys) == []                               # unchanged: silent
    daemon.tick_once(drv, state, ctx, now=t.replace(microsecond=600_000))
    assert _tx_after(capsys) == [0x10, 15, ord(" "), 0x14]       # colon off (20-cell line)
    daemon.tick_once(drv, state, ctx, now=t.replace(second=13, microsecond=0))
    assert _tx_after(capsys) == [0x10, 15, ord(":"), 0x14]       # colon on


def test_weather_never_uses_the_hardware_cursor_or_brightness(monkeypatch, capsys):
    for colon in ("on", "tick", "twinkle", "pulse", "pacman"):
        _, _, state = _weather_setup(monkeypatch, colon=colon)
        drv = VFDDriver(dry_run=True)
        ctx = daemon._new_ctx()
        daemon.tick_once(drv, state, ctx, now=datetime(2026, 9, 23, 20, 33, 12))
        capsys.readouterr()
        tx = []
        for ms in range(0, 1000, 20):
            daemon.tick_once(drv, state, ctx,
                             now=datetime(2026, 9, 23, 20, 33, 13, ms * 1000))
            tx += _tx_after(capsys)
        assert 0x13 not in tx, colon                             # no cursor-on
        assert 0x04 not in tx, colon                             # no brightness writes


def test_mode_change_repaints_the_whole_frame(monkeypatch, capsys):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    daemon.tick_once(drv, {"mode": "clock"}, ctx, now=NOW)
    daemon.tick_once(drv, {"mode": "marquee", "marquee_text": "hi"}, ctx, now=NOW)
    capsys.readouterr()
    # Back to clock in the same second: the frame text is identical to before,
    # but marquee changed the glass, so it must be repainted in full.
    daemon.tick_once(drv, {"mode": "clock"}, ctx, now=NOW)
    tx = _tx_after(capsys)
    assert tx[:2] == [0x10, 0x00] and 0x14 in tx


def test_clock_second_change_is_a_small_write(monkeypatch, capsys):
    monkeypatch.setattr(daemon, "save_status", lambda s: None)
    drv = VFDDriver(dry_run=True)
    ctx = daemon._new_ctx()
    daemon.tick_once(drv, {"mode": "clock"}, ctx, now=datetime(2026, 6, 19, 12, 0, 1))
    capsys.readouterr()
    daemon.tick_once(drv, {"mode": "clock"}, ctx, now=datetime(2026, 6, 19, 12, 0, 2))
    tx = _tx_after(capsys)
    assert len(tx) == 4 and tx[-1] == 0x14                       # one cell


def test_switching_colon_features_loads_each_ones_glyphs(monkeypatch):
    from checkout import glyphs

    _, _, state = _weather_setup(monkeypatch, colon="tick")
    drv = _RecordingDefines()
    ctx = daemon._new_ctx()
    daemon.tick_once(drv, state, ctx, now=NOW)
    assert ctx["mode_glyphs_key"][1].startswith("clock-")
    drv.defined.clear()
    daemon.tick_once(drv, {**state, "dynamic_colon": "on"}, ctx, now=NOW)
    assert drv.defined == {}                         # on/tick share the am/pm set
    daemon.tick_once(drv, {**state, "dynamic_colon": "pacman"}, ctx, now=NOW)
    assert ctx["mode_glyphs_key"][1].startswith("pacman-")
    daemon.tick_once(drv, {**state, "dynamic_colon": "twinkle"}, ctx, now=NOW)
    assert ctx["mode_glyphs_key"][1].startswith("twinkle-")
    assert drv.defined[5] == glyphs.TWINKLE_DOT
    assert drv.defined[7] == glyphs.TWINKLE_CORNERS


class _RecordingDefines(_CountingDriver):
    def __init__(self):
        super().__init__()
        self.defined = {}

    def define_character(self, slot, rows):
        self.defined[slot] = list(rows)



def test_weather_is_always_centered_whatever_the_saved_alignment(monkeypatch):
    # Every top line is a full 20 cells now; the bottom proves the rule.
    written, _, state = _weather_setup(monkeypatch, colon="on")
    state = {**state, "weather_lat": None, "align_bottom": "right"}
    daemon.tick_once(_CountingDriver(), state, daemon._new_ctx(),
                     now=datetime(2026, 9, 23, 20, 33, 12))
    assert written[-1]["bottom"] == "SET LOCATION".center(20)

def test_message_still_honours_the_saved_alignment(monkeypatch):
    written = []
    monkeypatch.setattr(daemon, "save_status", lambda s: written.append(s))
    state = {"mode": "message", "message": "HI\nTHERE", "align_top": "left",
             "align_bottom": "right"}
    daemon.tick_once(_CountingDriver(), state, daemon._new_ctx(), now=NOW)
    assert written[-1]["top"] == "HI".ljust(20)
    assert written[-1]["bottom"] == "THERE".rjust(20)


def test_pacman_solo_choice_loads_its_own_ghost_frames(monkeypatch):
    from checkout import glyphs, weather as wx

    _, _, state = _weather_setup(monkeypatch, colon="pacman")
    drv = _RecordingDefines()
    ctx = daemon._new_ctx()
    daemon.tick_once(drv, {**state, "dynamic_pacman_solo": False}, ctx, now=NOW)
    assert drv.defined[wx.SLOT_SPRITE_A] == glyphs.GHOST_A
    drv.defined.clear()
    daemon.tick_once(drv, {**state, "dynamic_pacman_solo": True,
                           "dynamic_pacman_sprite": "ghost"}, ctx, now=NOW)
    assert ctx["mode_glyphs_key"] == ("dynamic", "pacman-ghost")
    assert drv.defined[wx.SLOT_SPRITE_A] == glyphs.GHOST_B
    assert drv.defined[wx.SLOT_SPRITE_B] == glyphs.GHOST_C


def test_widest_line_loads_the_solo_glyphs_automatically(monkeypatch):
    from checkout import glyphs, weather as wx

    _, _, state = _weather_setup(monkeypatch, colon="pacman")
    state = {**state, "dynamic_pacman_solo": False, "dynamic_pacman_sprite": "ghost"}
    drv = _RecordingDefines()
    ctx = daemon._new_ctx()
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 12, 31, 1, 33))    # 17 cells
    assert ctx["mode_glyphs_key"] == ("dynamic", "pacman-duo-ghost")
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 12, 31, 12, 33))   # 18 cells
    assert ctx["mode_glyphs_key"] == ("dynamic", "pacman-ghost")
    assert drv.defined[wx.SLOT_SPRITE_B] == glyphs.GHOST_C


def test_marker_glyph_reloads_at_noon(monkeypatch):
    from checkout import glyphs, weather as wx

    _, _, state = _weather_setup(monkeypatch, colon="twinkle")
    drv = _RecordingDefines()
    ctx = daemon._new_ctx()
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 9, 24, 11, 59, 59))
    assert drv.defined[wx.SLOT_MERIDIEM] == glyphs.AM
    drv.defined.clear()
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 9, 24, 11, 59, 59, 500_000))
    assert drv.defined == {}                                   # same half: no reload
    daemon.tick_once(drv, state, ctx, now=datetime(2026, 9, 24, 12, 0, 0))
    assert drv.defined[wx.SLOT_MERIDIEM] == glyphs.PM



# --- news alerts in dynamic --------------------------------------------------------
from checkout.frames import news_alert as _na  # noqa: E402
from checkout.news import Headline as _Headline  # noqa: E402

_HEAD = _Headline("bbc", "A headline that is long enough to scroll", "b1", 1.0)
_T = datetime(2026, 9, 24, 12, 0, 0)


class _FakeNews:
    def __init__(self, alert=None, latest=None):
        self.alert, self._latest = alert, latest

    def set_config(self, sources, interval_s):
        self.config = (sources, interval_s)

    def take_alert(self):
        a, self.alert = self.alert, None
        return a

    def latest(self):
        return self._latest

    def status(self):
        return {"sources": {"bbc": {"title": "t", "published": None, "error": None}},
                "latest": None, "error": None}


def _news_setup(monkeypatch, effect="none", **fake):
    written, _, state = _weather_setup(monkeypatch, colon="on")
    news = _FakeNews(**fake)
    monkeypatch.setattr(daemon.DYNAMIC_FRAME, "news", news)
    monkeypatch.setattr(daemon.DYNAMIC_FRAME, "_alert", None)
    monkeypatch.setattr(daemon.DYNAMIC_FRAME, "_last_start_ms", None)   # no gap carried over
    monkeypatch.setattr(daemon.DYNAMIC_FRAME, "_shown", None)
    state = {**state, "news_enabled": True, "news_topics": ["politics"], "news_interval_min": 5,
             "news_repeat": 0, "news_speed_ms": 100, "news_effect": effect}
    return written, news, state


def test_an_alert_loads_the_banner_glyphs_then_the_clock_glyphs_return(monkeypatch):
    written, _, state = _news_setup(monkeypatch, alert=_HEAD)
    drv = _RecordingDefines()
    ctx = daemon._new_ctx()
    daemon.tick_once(drv, state, ctx, now=_T)
    assert ctx["mode_glyphs_key"] == ("dynamic", "news")
    assert drv.defined == _na.alert_glyphs()
    assert written[-1]["top"] == _na.banner()
    end = _T + timedelta(milliseconds=_na.duration_ms("BBC: " + _HEAD.title, 0, 100))
    daemon.tick_once(drv, state, ctx, now=end)
    assert ctx["mode_glyphs_key"][1].startswith("clock-")
    assert written[-1]["top"].startswith("09/24/26")


def test_the_alert_effect_drives_brightness(monkeypatch):
    _, _, state = _news_setup(monkeypatch, effect="throb", alert=_HEAD)
    levels = []

    class _Drv(_CountingDriver):
        def set_brightness(self, level):
            levels.append(level)

    drv, ctx = _Drv(), daemon._new_ctx()
    for ms in range(0, 900, 50):
        daemon.tick_once(drv, {**state, "animation": "flash"}, ctx,
                         now=_T + timedelta(milliseconds=ms))
    assert levels[:6] == [0, 1, 2, 3, 2, 1]


def test_show_news_command_plays_the_latest_headline(monkeypatch):
    written, _, state = _news_setup(monkeypatch, latest=_HEAD)
    state = {**state, "command": {"id": "n1", "action": "show_news", "args": {}}}
    daemon.tick_once(_CountingDriver(), state, daemon._new_ctx(), now=_T)
    assert written[-1]["top"] == _na.banner()                  # no reset: drawn at once


def test_status_reports_news_while_it_is_on(monkeypatch):
    written, _, state = _news_setup(monkeypatch)
    daemon.tick_once(_CountingDriver(), state, daemon._new_ctx(), now=_T)
    assert written[-1]["news"]["sources"]["bbc"]["title"] == "t"
    assert written[-1]["news"]["alerting"] is False
    daemon.tick_once(_CountingDriver(), {**state, "news_enabled": False}, daemon._new_ctx(), now=_T)
    assert written[-1]["news"] is None


def test_status_keeps_the_last_headline_shown_with_its_link(monkeypatch):
    head = _Headline("bbc", "A story", "https://www.bbc.co.uk/news/1", 1.0)
    written, news, state = _news_setup(monkeypatch)
    ctx = daemon._new_ctx()
    daemon.tick_once(_CountingDriver(), state, ctx, now=_T - timedelta(seconds=1))
    assert written[-1]["news_shown"] is None                   # nothing played yet
    news.alert = head
    daemon.tick_once(_CountingDriver(), state, ctx, now=_T)
    shown = written[-1]["news_shown"]
    assert (shown["outlet"], shown["title"], shown["link"]) == ("BBC", "A story", head.link)
    later = _T + timedelta(hours=1)                            # alert over, other mode
    daemon.tick_once(_CountingDriver(), {**state, "mode": "clock"}, ctx, now=later)
    assert written[-1]["news_shown"]["title"] == "A story"


def test_status_drops_a_link_that_is_not_a_web_address(monkeypatch):
    written, _, state = _news_setup(monkeypatch, alert=_HEAD)     # link "b1"
    daemon.tick_once(_CountingDriver(), state, daemon._new_ctx(), now=_T)
    assert written[-1]["news_shown"]["link"] is None


def test_leaving_dynamic_ends_an_alert(monkeypatch):
    _, _, state = _news_setup(monkeypatch, alert=_HEAD)
    ctx = daemon._new_ctx()
    daemon.tick_once(_CountingDriver(), state, ctx, now=_T)
    assert daemon.DYNAMIC_FRAME.alerting(_T)
    daemon.tick_once(_CountingDriver(), {**state, "mode": "clock"}, ctx, now=_T)
    assert not daemon.DYNAMIC_FRAME.alerting(_T)


def test_status_says_when_an_alert_is_showing(monkeypatch):
    written, _, state = _news_setup(monkeypatch, alert=_HEAD)
    daemon.tick_once(_CountingDriver(), state, daemon._new_ctx(), now=_T)
    assert written[-1]["news"]["alerting"] is True
