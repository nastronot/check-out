"""Spectrum module + audioviz tests — pure DSP, protocol, bar rendering, socket."""

import math

import pytest

from checkout import audioviz, spectrum
from checkout.driver import GLYPH_CODES


# --- protocol (tagged variable frame: full / stereo_v / stereo_h) -----------
def test_encode_decode_full_round_trip_and_clamp():
    heights = [0, 1, 7, 8, 14, 99, -3]
    data = spectrum.encode_full(heights)
    assert data[0] == spectrum.LAYOUT_FULL                  # tag byte
    assert len(data) == 1 + spectrum.NUM_BARS              # tag + 20 heights
    dec = spectrum.decode_frame(data)
    assert dec["layout"] == "full"
    assert dec["heights"][:7] == [0, 1, 7, 8, 14, 14, 0]   # clamped 0..14
    assert dec["heights"][7:] == [0] * (spectrum.NUM_BARS - 7)  # zero-padded


def test_encode_decode_stereo_v_round_trip_and_clamp():
    data = spectrum.encode_stereo_v([0, 7, 9], [3, -1])    # clamp 0..7, pad to 19
    assert data[0] == spectrum.LAYOUT_STEREO_V
    assert len(data) == 1 + 2 * spectrum.STEREO_BANDS
    dec = spectrum.decode_frame(data)
    assert dec["layout"] == "stereo_v"
    assert dec["left"][:3] == [0, 7, 7] and len(dec["left"]) == spectrum.STEREO_BANDS
    assert dec["right"][:2] == [3, 0] and len(dec["right"]) == spectrum.STEREO_BANDS


def test_encode_decode_stereo_h_round_trip_and_clamp():
    data = spectrum.encode_stereo_h(95, 200)               # clamp to 0..95
    assert data[0] == spectrum.LAYOUT_STEREO_H
    assert len(data) == 3
    dec = spectrum.decode_frame(data)
    assert dec == {"layout": "stereo_h", "level_l": 95, "level_r": 95}


def test_encode_frame_dispatches_by_layout():
    assert spectrum.decode_frame(spectrum.encode_frame("full", heights=[5]))["layout"] == "full"
    assert spectrum.decode_frame(
        spectrum.encode_frame("stereo_v", left=[1], right=[2]))["layout"] == "stereo_v"
    assert spectrum.decode_frame(
        spectrum.encode_frame("stereo_h", level_l=10, level_r=20))["layout"] == "stereo_h"


def test_decode_rejects_malformed_frames_safely():
    assert spectrum.decode_frame(b"") is None              # empty
    assert spectrum.decode_frame(bytes([spectrum.LAYOUT_FULL])) is None        # no payload
    assert spectrum.decode_frame(bytes([spectrum.LAYOUT_FULL, 1, 2])) is None  # short full
    assert spectrum.decode_frame(bytes([spectrum.LAYOUT_STEREO_V, 1, 2])) is None  # short stereo_v
    assert spectrum.decode_frame(bytes([spectrum.LAYOUT_STEREO_H, 1])) is None     # short stereo_h
    assert spectrum.decode_frame(bytes([99, 1, 2, 3])) is None  # unknown tag


# --- bar glyphs + cell mapping ----------------------------------------------
def test_bar_glyph_is_bottom_anchored_full_width():
    assert spectrum.bar_glyph(0) == [0, 0, 0, 0, 0, 0, 0]
    assert spectrum.bar_glyph(1) == [0, 0, 0, 0, 0, 0, 0x1F]   # bottom row only
    assert spectrum.bar_glyph(7) == [0x1F] * 7                  # full
    # height h lights exactly the bottom h rows
    assert spectrum.bar_glyph(3) == [0, 0, 0, 0, 0x1F, 0x1F, 0x1F]


def test_bar_glyphs_define_first_seven_slots():
    g = spectrum.bar_glyphs()
    assert set(g) == set(range(7))
    assert g[0] == spectrum.bar_glyph(1)   # slot 0 -> height 1
    assert g[6] == spectrum.bar_glyph(7)   # slot 6 -> height 7 (full)


def test_bar_to_cells_double_height_mapping():
    space = " "
    full = chr(GLYPH_CODES[6])            # slot 6 = full cell
    assert spectrum.bar_to_cells(0) == (space, space)
    # 1..7 fill the BOTTOM cell only (top empty)
    assert spectrum.bar_to_cells(1) == (space, chr(GLYPH_CODES[0]))
    assert spectrum.bar_to_cells(7) == (space, full)
    # 8..14 keep the bottom full and fill the TOP cell
    assert spectrum.bar_to_cells(8) == (chr(GLYPH_CODES[0]), full)
    assert spectrum.bar_to_cells(14) == (full, full)
    # clamped
    assert spectrum.bar_to_cells(99) == (full, full)


def test_render_spectrum_is_two_20_char_lines():
    top, bottom = spectrum.render_spectrum([0, 7, 14])
    assert len(top) == spectrum.NUM_BARS and len(bottom) == spectrum.NUM_BARS
    assert top[0] == " " and bottom[0] == " "           # bar 0 empty
    assert bottom[1] == chr(GLYPH_CODES[6])             # bar 7 -> full bottom
    assert top[2] == chr(GLYPH_CODES[6])               # bar 14 -> full top


def test_line_glyph_lights_exactly_one_peak_row():
    # height 0 -> dark; height h -> exactly ONE lit row at index GLYPH_ROWS-h.
    assert spectrum.line_glyph(0) == [0, 0, 0, 0, 0, 0, 0]
    assert spectrum.line_glyph(1) == [0, 0, 0, 0, 0, 0, 0x1F]   # bottom row only
    assert spectrum.line_glyph(7) == [0x1F, 0, 0, 0, 0, 0, 0]   # top row only
    assert spectrum.line_glyph(3) == [0, 0, 0, 0, 0x1F, 0, 0]   # single row at 4
    for h in range(1, 8):
        g = spectrum.line_glyph(h)
        assert g.count(0x1F) == 1                       # exactly one lit row
        assert g.index(0x1F) == spectrum.GLYPH_ROWS - h  # at the peak row


def test_line_glyphs_define_first_seven_slots():
    g = spectrum.line_glyphs()
    assert sorted(g) == list(spectrum.BAR_GLYPH_SLOTS)  # same slots as bars
    assert g[0] == spectrum.line_glyph(1)
    assert g[6] == spectrum.line_glyph(7)


def test_line_to_cells_single_row_bottom_empties_into_top():
    space = " "
    assert spectrum.line_to_cells(0) == (space, space)
    # 1..7: the line sits in the BOTTOM cell, top empty.
    assert spectrum.line_to_cells(1) == (space, chr(GLYPH_CODES[0]))
    assert spectrum.line_to_cells(7) == (space, chr(GLYPH_CODES[6]))
    # 8..14: the line is up in the TOP cell and the BOTTOM goes EMPTY (no fill
    # below it) — the key contrast with bar_to_cells, where the bottom stays full.
    assert spectrum.line_to_cells(8) == (chr(GLYPH_CODES[0]), space)
    assert spectrum.line_to_cells(14) == (chr(GLYPH_CODES[6]), space)
    assert spectrum.line_to_cells(99) == (chr(GLYPH_CODES[6]), space)  # clamped
    # Distinct from bars: at height 8 bars keep the bottom full, line empties it.
    assert spectrum.bar_to_cells(8)[1] != spectrum.line_to_cells(8)[1]


def test_style_glyphs_and_render_select_by_style():
    assert spectrum.style_glyphs("bars") == spectrum.bar_glyphs()
    assert spectrum.style_glyphs("line") == spectrum.line_glyphs()
    assert spectrum.style_glyphs("junk") == spectrum.bar_glyphs()   # default
    # render_spectrum picks the matching cell mapping.
    assert spectrum.render_spectrum([8], "line")[1][0] == " "       # bottom empty
    assert spectrum.render_spectrum([8], "bars")[1][0] == chr(GLYPH_CODES[6])


def test_decay_heights_drains_toward_zero():
    assert spectrum.decay_heights([0, 1, 5]) == [0, 0, 4]
    assert spectrum.decay_heights([3], step=2) == [1]


# --- stereo glyphs ----------------------------------------------------------
def test_label_glyph_is_inverted():
    # The label INVERTS the letter: a lit field with the letter dark.
    plain_l = spectrum.label_glyph("L", invert=False)
    inv_l = spectrum.label_glyph("L")
    assert plain_l == [0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x1F]
    assert inv_l == [(r ^ 0x1F) & 0x1F for r in plain_l]
    assert inv_l[0] == 0x1E and inv_l[6] == 0x00   # bottom row (was full) now dark
    assert spectrum.label_glyph("R") == [
        (r ^ 0x1F) & 0x1F for r in [0x0F, 0x11, 0x11, 0x0F, 0x05, 0x09, 0x11]
    ]


def test_col_glyph_lights_leftmost_n_columns():
    assert spectrum.col_glyph(0) == [0x00] * 7
    assert spectrum.col_glyph(1) == [0x01] * 7    # leftmost column, all rows
    assert spectrum.col_glyph(3) == [0x07] * 7    # leftmost 3 columns
    assert spectrum.col_glyph(5) == [0x1F] * 7    # full cell
    assert spectrum.col_glyph(9) == [0x1F] * 7    # clamped


def test_vline_glyph_lights_single_column():
    assert spectrum.vline_glyph(1) == [0x01] * 7  # leftmost only
    assert spectrum.vline_glyph(3) == [0x04] * 7  # column 3 only (bit 2)
    assert spectrum.vline_glyph(5) == [0x10] * 7  # rightmost only


def test_layout_glyphs_budget_per_layout_and_style():
    # full: 7 height glyphs (slots 0..6).
    assert sorted(spectrum.layout_glyphs("full", "bars")) == list(range(7))
    # stereo_v: 7 height glyphs + L/R labels = 9 (exact fit).
    g = spectrum.layout_glyphs("stereo_v", "line")
    assert sorted(g) == list(range(9))
    assert g[spectrum.STEREO_V_LABEL_L_SLOT] == spectrum.label_glyph("L")
    assert g[0] == spectrum.line_glyph(1)      # the line height set lives in 0..6
    # stereo_h bars: 5 col glyphs + L/R labels = 7.
    gh = spectrum.layout_glyphs("stereo_h", "bars")
    assert sorted(gh) == list(range(7))
    assert gh[0] == spectrum.col_glyph(1) and gh[4] == spectrum.col_glyph(5)
    assert gh[spectrum.STEREO_H_LABEL_R_SLOT] == spectrum.label_glyph("R")
    # stereo_h line: the 5 column slots hold single-column glyphs instead.
    assert spectrum.layout_glyphs("stereo_h", "line")[0] == spectrum.vline_glyph(1)


# --- stereo renderers -------------------------------------------------------
def test_render_stereo_v_labels_and_cells():
    top, bottom = spectrum.render_stereo_v([0, 7, 4] + [0] * 16, [7] * 19, "bars")
    assert len(top) == 20 and len(bottom) == 20
    assert top[0] == chr(GLYPH_CODES[spectrum.STEREO_V_LABEL_L_SLOT])   # L label
    assert bottom[0] == chr(GLYPH_CODES[spectrum.STEREO_V_LABEL_R_SLOT])  # R label
    assert top[1] == " "                       # height 0 -> empty
    assert top[2] == chr(GLYPH_CODES[6])       # height 7 -> slot 6 (full cell)
    assert top[3] == chr(GLYPH_CODES[3])       # height 4 -> slot 3


def test_render_stereo_h_bars_fills_with_partial_leading_cell():
    # level 7 (0..95): cell0 full (5 cols), cell1 partial (2 cols), rest empty.
    top, _ = spectrum.render_stereo_h(7, 0, "bars")
    assert top[0] == chr(GLYPH_CODES[spectrum.STEREO_H_LABEL_L_SLOT])  # label
    assert top[1] == chr(GLYPH_CODES[spectrum.STEREO_H_COL_SLOTS[4]])  # col_glyph(5) full
    assert top[2] == chr(GLYPH_CODES[spectrum.STEREO_H_COL_SLOTS[1]])  # col_glyph(2) partial
    assert top[3] == " "                                              # beyond the level
    # level 0 -> all data cells empty.
    t0, _ = spectrum.render_stereo_h(0, 0, "bars")
    assert t0[1:] == " " * 19


def test_render_stereo_h_line_lights_single_leading_column():
    # level 7 line: the single lit COLUMN is global col 7 = cell1, in-cell col 2.
    top, _ = spectrum.render_stereo_h(7, 0, "line")
    assert top[1] == " "                                              # cell 0 empty
    assert top[2] == chr(GLYPH_CODES[spectrum.STEREO_H_COL_SLOTS[1]])  # vline(2) in cell 1
    assert top[3] == " "
    # level 5 line: global col 5 = cell0 in-cell col 5 (the rightmost of cell 0).
    t5, _ = spectrum.render_stereo_h(5, 0, "line")
    assert t5[1] == chr(GLYPH_CODES[spectrum.STEREO_H_COL_SLOTS[4]])   # vline(5)
    assert t5[2] == " "


# --- stereo DSP (shared auto-gain makes the balance visible) ----------------
def test_stereo_v_shared_gain_louder_channel_reads_higher():
    np = pytest.importorskip("numpy")
    av = audioviz.AudioViz("/tmp/checkout-test-nosock.sock")
    av.configure(1.0, 0.0, "stereo_v")
    rate, n = 44100, 512
    t = np.arange(n) / rate
    loud = (np.sin(2 * np.pi * 440 * t) * 0.5).astype("float32")
    quiet = (np.sin(2 * np.pi * 440 * t) * 0.03).astype("float32")
    for _ in range(20):
        frame = av.process_frame(loud, quiet, rate)
    dec = spectrum.decode_frame(frame)
    assert max(dec["left"]) > max(dec["right"])   # balance visible


def test_stereo_v_silence_in_one_channel_drops_that_row():
    np = pytest.importorskip("numpy")
    av = audioviz.AudioViz("/tmp/checkout-test-nosock.sock")
    av.configure(1.0, 0.5, "stereo_v")
    rate, n = 44100, 512
    t = np.arange(n) / rate
    loud = (np.sin(2 * np.pi * 440 * t) * 0.5).astype("float32")
    silent = np.zeros(n, dtype="float32")
    for _ in range(60):
        frame = av.process_frame(loud, silent, rate)
    dec = spectrum.decode_frame(frame)
    assert max(dec["left"]) > 0 and max(dec["right"]) == 0


def test_stereo_h_overall_level_scaled_0_95_and_balance():
    np = pytest.importorskip("numpy")
    av = audioviz.AudioViz("/tmp/checkout-test-nosock.sock")
    av.configure(1.0, 0.0, "stereo_h")
    rate, n = 44100, 512
    t = np.arange(n) / rate
    loud = (np.sin(2 * np.pi * 440 * t) * 0.5).astype("float32")
    quiet = (np.sin(2 * np.pi * 440 * t) * 0.03).astype("float32")
    for _ in range(30):
        frame = av.process_frame(loud, quiet, rate)
    dec = spectrum.decode_frame(frame)
    assert 0 <= dec["level_l"] <= spectrum.STEREO_H_MAX
    assert dec["level_l"] > dec["level_r"]        # louder channel = longer meter


def test_full_layout_is_mono_sum():
    np = pytest.importorskip("numpy")
    av = audioviz.AudioViz("/tmp/checkout-test-nosock.sock")
    av.configure(1.0, 0.0, "full")
    rate, n = 44100, 512
    t = np.arange(n) / rate
    sig = (np.sin(2 * np.pi * 440 * t) * 0.4).astype("float32")
    frame = av.process_frame(sig, sig, rate)
    dec = spectrum.decode_frame(frame)
    assert dec["layout"] == "full" and len(dec["heights"]) == 20


# --- socket round trip (real unix datagram socket) --------------------------
def test_receiver_drains_to_latest_frame(tmp_path):
    path = str(tmp_path / "spec.sock")
    rx = spectrum.SpectrumReceiver(path)
    rx.open()
    try:
        tx = spectrum.SpectrumSender(path)
        tx.send(spectrum.encode_full([1] * spectrum.NUM_BARS))
        tx.send(spectrum.encode_full([2] * spectrum.NUM_BARS))
        tx.send(spectrum.encode_full([13] * spectrum.NUM_BARS))   # newest wins
        import time
        time.sleep(0.05)
        latest = rx.drain()
        assert latest == {"layout": "full", "heights": [13] * spectrum.NUM_BARS}
        assert rx.drain() is None            # queue now empty
        tx.close()
    finally:
        rx.close()


def test_receiver_drains_stereo_frames(tmp_path):
    path = str(tmp_path / "spec_stereo.sock")
    rx = spectrum.SpectrumReceiver(path)
    rx.open()
    try:
        tx = spectrum.SpectrumSender(path)
        tx.send(spectrum.encode_stereo_v([7] * 19, [2] * 19))
        tx.send(spectrum.encode_stereo_h(80, 10))   # newest wins (a different layout)
        import time
        time.sleep(0.05)
        assert rx.drain() == {"layout": "stereo_h", "level_l": 80, "level_r": 10}
        tx.close()
    finally:
        rx.close()


def test_sender_without_listener_does_not_raise(tmp_path):
    # No receiver bound — send must drop silently (newest-wins, never block).
    tx = spectrum.SpectrumSender(str(tmp_path / "nobody.sock"))
    tx.send(spectrum.encode_full([5] * spectrum.NUM_BARS))
    tx.close()


# --- DSP helpers (pure, numpy-free) -----------------------------------------
def test_log_band_edges_monotonic_and_in_range():
    edges = spectrum.log_band_edges(20, 44100, 1024)
    assert len(edges) == 21
    n_bins = 1024 // 2 + 1
    assert all(0 <= e < n_bins for e in edges)
    assert all(b >= a for a, b in zip(edges, edges[1:]))   # non-decreasing
    # low bands are narrower than high bands (log spacing)
    assert edges[-1] > edges[0]


def test_bucketize_averages_bins_per_band():
    edges = [0, 2, 4]
    mags = [1.0, 3.0, 10.0, 20.0]
    assert spectrum.bucketize(mags, edges) == [2.0, 15.0]


def test_to_levels_scales_with_gain_and_clamps():
    # A louder band reads a higher level; gain lifts quiet signals.
    quiet = spectrum.to_levels([0.01], gain=1.0)[0]
    loud = spectrum.to_levels([1.0], gain=1.0)[0]
    assert 0 <= quiet <= loud <= spectrum.MAX_BAR
    assert spectrum.to_levels([0.01], gain=50.0)[0] > quiet


def test_decay_levels_attack_fast_release_slow():
    # Rise instantly to the new peak; fall only by `factor`.
    out = spectrum.decay_levels([0.0, 10.0], [12.0, 0.0], factor=0.5)
    assert out == [12.0, 5.0]


def test_decay_levels_factor_zero_no_tail():
    # factor 0 = snappy: out = max(new, prev*0) = new — no falling tail at all.
    out = spectrum.decay_levels([10.0, 5.0], [3.0, 0.0], factor=0.0)
    assert out == [3.0, 0.0]


# --- audioviz device selection (pure) ---------------------------------------
DEVICES = [
    {"index": 3, "name": "Built-in Microphone", "max_input_channels": 2, "is_monitor": False},
    {"index": 7, "name": "Monitor of Speakers", "max_input_channels": 2, "is_monitor": True},
    {"index": 9, "name": "No Inputs HDMI", "max_input_channels": 0, "is_monitor": False},
]


def test_find_device_system_picks_monitor():
    assert audioviz.find_device(DEVICES, "system", None) == 7


def test_find_device_mic_uses_default():
    assert audioviz.find_device(DEVICES, "mic", None) is None


def test_find_device_explicit_by_index_and_name():
    assert audioviz.find_device(DEVICES, "mic", 3) == 3
    assert audioviz.find_device(DEVICES, "mic", "microphone") == 3   # substring
    assert audioviz.find_device(DEVICES, "system", "monitor") == 7


def test_find_device_explicit_missing_returns_none():
    assert audioviz.find_device(DEVICES, "mic", "nonexistent") is None


def test_find_device_system_without_monitor_returns_none():
    mics = [d for d in DEVICES if not d["is_monitor"]]
    assert audioviz.find_device(mics, "system", None) is None


def test_audioviz_process_finds_a_tone_band():
    np = pytest.importorskip("numpy")
    rate, n = 44100, 1024
    t = np.arange(n) / rate
    tone = np.sin(2 * math.pi * 2000 * t).astype("float32")
    eng = audioviz.AudioViz("/tmp/checkout-test-none.sock")
    heights = eng.process(tone, rate)
    assert len(heights) == spectrum.NUM_BARS
    assert max(heights) > 0                # the tone lit some band
    eng.close()


# --- v0.9.1: hardened restart + PipeWire monitor detection ------------------
class _FakeStream:
    def __init__(self, raise_on=None):
        self.stopped = self.closed = False
        self.raise_on = raise_on

    def stop(self):
        if self.raise_on == "stop":
            raise RuntimeError("boom")
        self.stopped = True

    def close(self):
        if self.raise_on == "close":
            raise RuntimeError("boom")
        self.closed = True


def test_sounddevice_stop_fully_tears_down_and_nulls_handle():
    cap = audioviz.SoundDeviceCapture(0, 44100, lambda s, r: None)
    st = _FakeStream()
    cap._stream = st
    cap.stop()
    assert st.stopped and st.closed       # stop() THEN close()
    assert cap._stream is None            # handle released


def test_sounddevice_stop_survives_a_teardown_error():
    cap = audioviz.SoundDeviceCapture(0, 44100, lambda s, r: None)
    cap._stream = _FakeStream(raise_on="stop")
    cap.stop()                            # must NOT raise (PortAudio would segfault)
    assert cap._stream is None


class _FailCapture:
    def __init__(self):
        self.stopped = False

    def start(self):
        raise RuntimeError("device busy")

    def stop(self):
        self.stopped = True


def test_restart_capture_catches_failed_open_and_emits_zeros(monkeypatch):
    fail = _FailCapture()
    monkeypatch.setattr(audioviz, "make_capture", lambda key, on, devs: fail)
    out = audioviz._restart_capture(None, ("portaudio", 0), lambda s, r: None, [])
    assert out is None                    # fell back, no raise
    assert fail.stopped                   # the partially-started capture torn down


def test_restart_capture_stops_the_old_capture():
    old = _FailCapture()
    out = audioviz._restart_capture(old, None, lambda s, r: None, [])
    assert old.stopped and out is None


def test_change_debouncer_coalesces_rapid_changes():
    d = audioviz.ChangeDebouncer(window_ms=400)
    d.observe(("pulse", "a"), 0)
    assert not d.due(100)
    d.observe(("pulse", "b"), 100)        # changed -> timer resets
    assert not d.due(400)                 # only 300ms stable at "b"
    assert d.due(500)                     # 400ms stable
    assert d.take() == ("pulse", "b")     # newest value wins


def test_change_debouncer_fires_after_stable_window():
    d = audioviz.ChangeDebouncer(window_ms=300)
    d.observe("x", 0)
    assert d.peek() == "x"
    assert d.due(300)


_SOURCES_SHORT = (
    "3194\talsa_output.creative.analog-stereo-output.monitor\tPipeWire\ts24le\tRUNNING\n"
    "3195\talsa_input.creative.analog-stereo-input\tPipeWire\ts24le\tSUSPENDED\n"
    "31159\talsa_output.hdmi-stereo.monitor\tPipeWire\ts32le\tSUSPENDED"
)


def test_parse_pulse_sources_flags_monitors():
    srcs = {s["name"]: s["is_monitor"] for s in audioviz.parse_pulse_sources(_SOURCES_SHORT)}
    assert srcs["alsa_output.creative.analog-stereo-output.monitor"] is True
    assert srcs["alsa_input.creative.analog-stereo-input"] is False
    assert srcs["alsa_output.hdmi-stereo.monitor"] is True


def test_parse_source_descriptions():
    long_text = (
        "Source #1\n\tName: alsa_output.x.monitor\n\tDescription: Monitor of Speakers\n"
        "Source #2\n\tName: alsa_input.y\n\tDescription: Built-in Mic\n"
    )
    d = audioviz.parse_source_descriptions(long_text)
    assert d["alsa_output.x.monitor"] == "Monitor of Speakers"
    assert d["alsa_input.y"] == "Built-in Mic"


def test_default_sink_monitor(monkeypatch):
    monkeypatch.setattr(audioviz, "_run_cmd", lambda args, timeout=2.0: "my_sink\n")
    assert audioviz.default_sink_monitor() == "my_sink.monitor"
    monkeypatch.setattr(audioviz, "_run_cmd", lambda *a, **k: None)
    assert audioviz.default_sink_monitor() is None


def test_default_source_name(monkeypatch):
    monkeypatch.setattr(audioviz, "_run_cmd", lambda args, timeout=2.0: "my_input\n")
    assert audioviz.default_source_name() == "my_input"
    monkeypatch.setattr(audioviz, "_run_cmd", lambda *a, **k: None)
    assert audioviz.default_source_name() is None


def test_build_device_list_is_minimal_pulse_monitors_and_inputs():
    # Pulse sources ARE the real, minimal list — monitors + real inputs, labeled.
    pulse = [
        {"name": "sink.monitor", "is_monitor": True},
        {"name": "mic.src", "is_monitor": False},
    ]
    desc = {"sink.monitor": "Monitor of Speakers", "mic.src": "Built-in Mic"}
    devs = {d["id"]: d for d in audioviz.build_device_list(pulse, desc, inputs=[])}
    assert devs["sink.monitor"]["kind"] == "monitor" and devs["sink.monitor"]["is_monitor"]
    assert devs["sink.monitor"]["label"] == "Monitor of Speakers"
    assert devs["mic.src"]["kind"] == "input" and not devs["mic.src"]["is_monitor"]
    assert devs["mic.src"]["label"] == "Built-in Mic"
    assert all(d["backend"] == "pulse" for d in devs.values())


def test_build_device_list_falls_back_to_portaudio_without_pulse():
    # No pactl/Pulse -> the PortAudio inputs are the (best-effort) fallback list.
    inputs = [{"index": 3, "name": "USB Mic", "is_monitor": False, "default_samplerate": 44100}]
    devs = {d["id"]: d for d in audioviz.build_device_list([], {}, inputs)}
    assert devs["3"]["kind"] == "input" and devs["3"]["backend"] == "portaudio"
    assert devs["3"]["label"] == "USB Mic"


_DEVS = [
    {"id": "sink.monitor", "label": "Monitor of Speakers", "kind": "monitor", "is_monitor": True, "backend": "pulse"},
    {"id": "hdmi.monitor", "label": "Monitor of HDMI", "kind": "monitor", "is_monitor": True, "backend": "pulse"},
    {"id": "alsa_input.mic", "label": "Built-in Mic", "kind": "input", "is_monitor": False, "backend": "pulse"},
]


def test_select_capture_system_defaults_to_default_sink_monitor():
    assert audioviz.select_capture("system", None, _DEVS, "sink.monitor") == ("pulse", "sink.monitor")


def test_select_capture_system_honors_device_override():
    assert audioviz.select_capture("system", "hdmi.monitor", _DEVS, "sink.monitor") == ("pulse", "hdmi.monitor")


def test_select_capture_system_without_monitor_is_none_not_mic():
    inputs_only = [d for d in _DEVS if not d["is_monitor"]]
    assert audioviz.select_capture("system", None, inputs_only, None) is None


def test_select_capture_mic_uses_pulse_input():
    # Default source, then an explicit override — both via pw-record (pulse).
    assert audioviz.select_capture("mic", None, _DEVS, "sink.monitor", "alsa_input.mic") == ("pulse", "alsa_input.mic")
    assert audioviz.select_capture("mic", "alsa_input.mic", _DEVS, "sink.monitor", "x") == ("pulse", "alsa_input.mic")


def test_select_capture_mic_falls_back_to_portaudio_without_pulse():
    pa = [{"id": "3", "label": "USB Mic", "kind": "input", "is_monitor": False,
           "backend": "portaudio", "index": 3}]
    assert audioviz.select_capture("mic", None, pa, None, None) == ("portaudio", None)
    assert audioviz.select_capture("mic", "3", pa, None, None) == ("portaudio", 3)


class _FakePipe:
    def __init__(self, data, chunk):
        self.data, self.chunk, self.pos = data, chunk, 0

    def read(self, n):
        out = self.data[self.pos:self.pos + min(n, self.chunk)]
        self.pos += len(out)
        return out


def test_read_exact_accumulates_partial_pipe_reads():
    data = bytes(range(10)) * 5          # 50 bytes
    pipe = _FakePipe(data, chunk=7)      # returns <=7 bytes per read
    got = audioviz._read_exact(pipe, 20, lambda: False)
    assert got == data[:20] and len(got) == 20


def test_read_exact_returns_none_at_eof():
    pipe = _FakePipe(b"abc", chunk=10)   # only 3 bytes then EOF
    assert audioviz._read_exact(pipe, 20, lambda: False) is None


def test_read_exact_returns_none_when_stopped():
    pipe = _FakePipe(bytes(100), chunk=4)
    assert audioviz._read_exact(pipe, 20, lambda: True) is None  # stop flag set


# --- v0.9.2: auto-gain (volume-independent) ---------------------------------
def test_normalize_levels_is_volume_independent():
    bands = [0.2, 1.0, 0.5, 0.1]
    loud = spectrum.normalize_levels(bands, max(bands))
    quiet = spectrum.normalize_levels([b * 0.01 for b in bands], max(bands) * 0.01)
    assert loud == quiet                       # shape independent of absolute level
    # Centered map: a band AT the reference lands mid-high (~range/(range+headroom)),
    # NOT pinned to the top — louder bands have headroom above it.
    at_ref = round(spectrum.AUTOGAIN_RANGE_DB
                   / (spectrum.AUTOGAIN_RANGE_DB + spectrum.AUTOGAIN_HEADROOM_DB)
                   * spectrum.MAX_BAR)
    assert max(loud) == at_ref
    # A band ABOVE the reference reaches the top (headroom).
    assert spectrum.normalize_levels([4.0], 1.0)[0] == spectrum.MAX_BAR


def test_normalize_levels_sensitivity_biases_fullness():
    bands = [0.1, 0.3, 0.05]
    ref = max(bands)
    low = spectrum.normalize_levels(bands, ref, sensitivity=0.5)
    high = spectrum.normalize_levels(bands, ref, sensitivity=2.0)
    assert sum(high) >= sum(low)


def test_update_ref_attacks_gradually_and_releases_to_floor():
    # Rising is a SMOOTH attack (not an instant snap), so a transient can't pump.
    ref = spectrum.update_ref(1.0, 10.0)       # 1 + (10-1)*0.4 = 4.6, not 10
    assert 1.0 < ref < 10.0
    # ...and it keeps climbing toward the peak over successive frames.
    r2 = spectrum.update_ref(ref, 10.0)
    assert ref < r2 < 10.0
    released = spectrum.update_ref(ref, 0.0)   # silence -> releases (no ratchet)
    assert spectrum.REF_FLOOR <= released < ref
    for _ in range(50000):                     # never drops below the floor
        released = spectrum.update_ref(released, 0.0)
    assert released == spectrum.REF_FLOOR


def test_signal_rms():
    assert spectrum.signal_rms([]) == 0.0
    assert abs(spectrum.signal_rms([1, -1, 1, -1]) - 1.0) < 1e-9
    assert spectrum.signal_rms([0, 0, 0]) == 0.0


def _tone(np, amp, n=1024, rate=44100, f=1500):
    t = np.arange(n) / rate
    return (amp * np.sin(2 * math.pi * f * t)).astype("float32")


def test_autogain_quiet_and_loud_reach_similar_fullness():
    np = pytest.importorskip("numpy")
    loud, quiet = audioviz.AudioViz("/tmp/x.sock"), audioviz.AudioViz("/tmp/x.sock")
    for _ in range(40):                        # adapt the references
        hl = loud.process(_tone(np, 0.4), 44100)
        hq = quiet.process(_tone(np, 0.008), 44100)  # 50x quieter
    assert max(hl) >= 12 and max(hq) >= 12     # both fill despite the level gap


def test_autogain_silence_is_flat_and_does_not_ratchet():
    np = pytest.importorskip("numpy")
    eng = audioviz.AudioViz("/tmp/x.sock")
    for _ in range(40):
        eng.process(_tone(np, 0.4), 44100)
    ref_loud = eng._ref
    rng = np.random.RandomState(0)
    last = None
    for _ in range(200):                       # below-floor noise = silence
        last = eng.process((1e-4 * rng.randn(1024)).astype("float32"), 44100)
    assert max(last) == 0                       # bars fall flat
    assert eng._ref <= ref_loud                 # reference did NOT ratchet up on noise


def test_autogain_readapts_when_signal_returns():
    np = pytest.importorskip("numpy")
    eng = audioviz.AudioViz("/tmp/x.sock")
    for _ in range(60):                        # silence first
        eng.process((1e-5 * np.ones(1024)).astype("float32"), 44100)
    for _ in range(40):                        # real audio returns
        h = eng.process(_tone(np, 0.3), 44100)
    assert max(h) > 0                           # adapts and shows bars again


# --- v0.9.3: auto-gain envelope fixes ---------------------------------------
def test_percentile_peak_is_a_high_percentile_not_the_max():
    bands = list(range(1, 21))                 # 1..20
    p85 = spectrum.percentile_peak(bands, 85)
    assert 16.0 < p85 < 19.0                    # ~85th percentile of 1..20
    assert p85 < max(bands)                      # NOT the single loudest band
    assert spectrum.percentile_peak([]) == 0.0
    assert spectrum.percentile_peak([5.0]) == 5.0


def test_normalize_levels_volume_independent_across_range():
    # The SAME spectrum at very different absolute levels -> identical bars, now
    # that REF_FLOOR sits below quiet-music levels (Bug 1).
    base = [0.05, 0.4, 1.0, 0.2, 0.6, 0.1]
    ref = spectrum.percentile_peak(base)
    out0 = spectrum.normalize_levels(base, ref)
    for scale in (10.0, 1.0, 0.1, 0.01, 0.002):
        scaled = [b * scale for b in base]
        assert spectrum.normalize_levels(scaled, ref * scale) == out0


def test_update_ref_attack_climbs_over_frames_then_releases():
    # Smooth attack: a single big peak does NOT pin the reference instantly.
    ref = spectrum.REF_FLOOR
    first = spectrum.update_ref(ref, 10.0)
    assert first < 10.0                          # didn't snap to the peak
    r = first
    for _ in range(20):                          # repeated frames climb toward it
        r = spectrum.update_ref(r, 10.0)
    assert r > first and r > 9.0                  # converges up over time
    assert spectrum.update_ref(r, 0.0) < r        # lower signal -> releases


def test_engine_decay_holds_bars_after_a_silent_frame():
    np = pytest.importorskip("numpy")
    eng = audioviz.AudioViz("/tmp/x.sock")
    sig = _tone(np, 0.5)
    for _ in range(40):                          # warm the bars up
        eng.process(sig, 44100)
    before = max(eng.levels)
    assert before > 0
    h = eng.process(np.zeros(1024, dtype="float32"), 44100)  # ONE silent frame
    # decay_levels (prev persists, out=max(new, prev*factor)) holds the bars —
    # they don't flash to 0 on a single quiet frame.
    assert max(h) >= before * 0.5


# --- v0.9.4: broadband ref + centered normalization (no sink, spread) --------
def test_band_mean_is_arithmetic_mean():
    assert spectrum.band_mean([]) == 0.0
    assert spectrum.band_mean([2.0, 4.0]) == 3.0


def test_normalize_levels_centered_with_headroom():
    # A band AT the reference lands mid-high (NOT pinned to the top).
    at = spectrum.normalize_levels([1.0], 1.0)[0]
    expected = round(spectrum.AUTOGAIN_RANGE_DB
                     / (spectrum.AUTOGAIN_RANGE_DB + spectrum.AUTOGAIN_HEADROOM_DB)
                     * spectrum.MAX_BAR)
    assert at == expected and 0 < at < spectrum.MAX_BAR
    assert spectrum.normalize_levels([10.0], 1.0)[0] == spectrum.MAX_BAR  # headroom -> top
    assert spectrum.normalize_levels([0.001], 1.0)[0] == 0                # far below -> 0


def test_normalize_levels_spreads_a_realistic_spectrum():
    # A typical tilted spectrum should SPREAD across the display, not collapse.
    bands = [1.0, 0.7, 0.5, 0.35, 0.25, 0.18, 0.13, 0.1, 0.07, 0.05,
             0.04, 0.03, 0.025, 0.02, 0.016, 0.013, 0.01, 0.008, 0.006, 0.005]
    lv = spectrum.normalize_levels(bands, spectrum.band_mean(bands))
    assert max(lv) >= 12                       # loud bands near the top
    assert (max(lv) - min(lv)) >= 6            # a genuine spread (not all one level)
    assert sum(1 for x in lv if x > 0) >= 12   # most bands visible (no collapse)


def test_update_ref_release_recovers_quickly():
    # AUTOGAIN_RELEASE 0.95 -> reference falls below ~40% within ~18 frames.
    ref = 1.0
    for _ in range(18):
        ref = spectrum.update_ref(ref, 0.0)
    assert ref < 0.4


def _pink(np, vol, seed):
    rng = np.random.RandomState(seed)
    F = np.fft.rfft(rng.randn(1024))
    f = np.arange(F.size).astype(float)
    f[0] = 1.0
    sig = np.fft.irfft(F / np.sqrt(f), 1024)   # 1/sqrt(f) tilt = pink-ish broadband
    return (sig / np.max(np.abs(sig)) * vol).astype("float32")


def test_engine_converges_to_a_spread_not_a_sink():
    np = pytest.importorskip("numpy")
    sig = _pink(np, 0.4, 7)
    eng = audioviz.AudioViz("/tmp/x.sock")
    for _ in range(120):                       # ~3s of the same broadband frame
        h = eng.process(sig, 44100)
    assert max(h) >= 12                        # fills toward the top
    assert sum(h) >= 60                        # did NOT sink to ~0
    assert (max(h) - min(h)) >= 5              # spread across the display
    h2 = eng.process(sig, 44100)               # stable: no ongoing downward drift
    assert abs(sum(h2) - sum(h)) <= 6


def test_engine_spread_is_volume_independent():
    np = pytest.importorskip("numpy")
    loud, quiet = audioviz.AudioViz("/tmp/x.sock"), audioviz.AudioViz("/tmp/x.sock")
    for i in range(120):
        hl = loud.process(_pink(np, 0.5, i % 9), 44100)
        hq = quiet.process(_pink(np, 0.05, i % 9), 44100)   # 10x quieter, same content
    assert abs(sum(hl) - sum(hq)) <= 12


# --- v0.9.5: capture tool priority (parec sustains; pw-record starves) -------
def test_capture_tool_prefers_parec(monkeypatch):
    # Both present -> parec (pw-record starves a piped reader after one buffer).
    monkeypatch.setattr(audioviz.shutil, "which", lambda t: "/usr/bin/" + t)
    assert audioviz._capture_tool() == "parec"


def test_capture_tool_falls_back_to_pw_record(monkeypatch):
    monkeypatch.setattr(audioviz.shutil, "which",
                        lambda t: "/usr/bin/pw-record" if t == "pw-record" else None)
    assert audioviz._capture_tool() == "pw-record"


def test_capture_tool_none_when_neither_present(monkeypatch):
    monkeypatch.setattr(audioviz.shutil, "which", lambda t: None)
    assert audioviz._capture_tool() is None


def test_parec_command_is_the_confirmed_working_invocation():
    cmd = audioviz.parec_command("parec", "sink.monitor", 44100, 1)
    assert cmd == ["parec", "--device=sink.monitor", "--format=s16le",
                   "--rate=44100", "--channels=1",
                   f"--latency-msec={audioviz.PAREC_LATENCY_MS}"]
    # The low-latency flag is REQUIRED — without it parec block-buffers ~750ms
    # and dumps audio in bursts (the pump + delay).
    assert f"--latency-msec={audioviz.PAREC_LATENCY_MS}" in cmd


def test_pw_record_command_is_the_fallback():
    cmd = audioviz.parec_command("pw-record", "sink.monitor", 44100, 1)
    assert cmd[0] == "pw-record" and "--target" in cmd and cmd[-1] == "-"
