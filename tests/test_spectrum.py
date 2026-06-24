"""Spectrum module + audioviz tests — pure DSP, protocol, bar rendering, socket."""

import math

import pytest

from checkout import audioviz, spectrum
from checkout.driver import GLYPH_CODES


# --- protocol ---------------------------------------------------------------
def test_encode_decode_round_trip_and_clamp():
    heights = [0, 1, 7, 8, 14, 99, -3]
    data = spectrum.encode_frame(heights)
    assert len(data) == spectrum.NUM_BARS          # always full-width
    dec = spectrum.decode_frame(data)
    assert dec[:7] == [0, 1, 7, 8, 14, 14, 0]      # clamped 0..14
    assert dec[7:] == [0] * (spectrum.NUM_BARS - 7)  # zero-padded


def test_decode_rejects_short_frame():
    assert spectrum.decode_frame(b"") is None
    assert spectrum.decode_frame(bytes(spectrum.NUM_BARS - 1)) is None


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


def test_decay_heights_drains_toward_zero():
    assert spectrum.decay_heights([0, 1, 5]) == [0, 0, 4]
    assert spectrum.decay_heights([3], step=2) == [1]


# --- socket round trip (real unix datagram socket) --------------------------
def test_receiver_drains_to_latest_frame(tmp_path):
    path = str(tmp_path / "spec.sock")
    rx = spectrum.SpectrumReceiver(path)
    rx.open()
    try:
        tx = spectrum.SpectrumSender(path)
        tx.send([1] * spectrum.NUM_BARS)
        tx.send([2] * spectrum.NUM_BARS)
        tx.send([13] * spectrum.NUM_BARS)   # newest wins
        import time
        time.sleep(0.05)
        latest = rx.drain()
        assert latest == [13] * spectrum.NUM_BARS
        assert rx.drain() is None            # queue now empty
        tx.close()
    finally:
        rx.close()


def test_sender_without_listener_does_not_raise(tmp_path):
    # No receiver bound — send must drop silently (newest-wins, never block).
    tx = spectrum.SpectrumSender(str(tmp_path / "nobody.sock"))
    tx.send([5] * spectrum.NUM_BARS)
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


def test_build_device_list_labels_monitors_vs_inputs():
    pulse = [
        {"name": "sink.monitor", "is_monitor": True},
        {"name": "mic.src", "is_monitor": False},   # non-monitor pulse src -> NOT listed
    ]
    desc = {"sink.monitor": "Monitor of Speakers"}
    inputs = [{"index": 3, "name": "Built-in Mic", "is_monitor": False, "default_samplerate": 44100}]
    devs = {d["id"]: d for d in audioviz.build_device_list(pulse, desc, inputs)}
    assert devs["sink.monitor"]["kind"] == "monitor"
    assert devs["sink.monitor"]["is_monitor"] is True
    assert devs["sink.monitor"]["label"] == "[monitor] Monitor of Speakers"
    assert devs["3"]["kind"] == "input" and devs["3"]["is_monitor"] is False
    assert "mic.src" not in devs                # monitors from pulse, inputs from portaudio


_DEVS = [
    {"id": "sink.monitor", "label": "[monitor] Monitor of Speakers", "kind": "monitor", "is_monitor": True},
    {"id": "hdmi.monitor", "label": "[monitor] HDMI", "kind": "monitor", "is_monitor": True},
    {"id": "3", "label": "Built-in Mic", "kind": "input", "is_monitor": False, "index": 3},
]


def test_select_capture_system_defaults_to_default_sink_monitor():
    assert audioviz.select_capture("system", None, _DEVS, "sink.monitor") == ("pulse", "sink.monitor")


def test_select_capture_system_honors_device_override():
    assert audioviz.select_capture("system", "hdmi.monitor", _DEVS, "sink.monitor") == ("pulse", "hdmi.monitor")


def test_select_capture_system_without_monitor_is_none_not_mic():
    inputs_only = [d for d in _DEVS if not d["is_monitor"]]
    assert audioviz.select_capture("system", None, inputs_only, None) is None


def test_select_capture_mic_uses_portaudio():
    assert audioviz.select_capture("mic", None, _DEVS, "sink.monitor") == ("portaudio", None)
    assert audioviz.select_capture("mic", "3", _DEVS, "sink.monitor") == ("portaudio", 3)


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
