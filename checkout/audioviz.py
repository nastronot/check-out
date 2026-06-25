"""checkout.audioviz — audio capture + FFT → 20 log bands → socket stream.

A SEPARATE process (it never touches the serial port). It captures audio, runs
an FFT, buckets into 20 log-spaced bands, maps each to a height 0..14 with
attack-fast/release-slow smoothing, and STREAMS the heights to the daemon over
the unix datagram socket (:mod:`checkout.spectrum`).

Capture (v0.9.1/.2, tool priority fixed v0.9.5): PortAudio's ALSA backend does
NOT reliably expose PipeWire ``.monitor`` sources, so BOTH **system** (a sink
``.monitor``) and **mic** (an input source) are captured NATIVELY with **parec**
(preferred) / ``pw-record`` (fallback) — a subprocess reading raw s16le PCM.
parec is bench-proven to deliver SUSTAINED audio from a monitor; pw-record/pw-cat
piped deliver one buffer then STARVE to near-silence (the real cause of the
spectrum "fills then dies"). ``sounddevice`` (PortAudio) is a FALLBACK only when
Pulse is absent. The capture lifecycle is HARDENED (full stop+close, debounced
restarts, try/except open) so cycling devices can't segfault. Sources are
enumerated with ``pactl``; defaults are ``pactl get-default-sink`` + ``.monitor``
(system) and ``pactl get-default-source`` (mic).

The display is **auto-gained** (v0.9.2): bars normalize against a decaying-max
reference of recent loudness, so they're volume-INDEPENDENT (content-driven), and
a silence floor lets them fall flat without amplifying hiss. ``audio_gain`` is now
**sensitivity** (biases the auto-gain).

SETTINGS come from ``state.json`` (``audio_source`` / ``audio_device`` /
``audio_gain`` / ``audio_decay``) — re-read live; a source/device change restarts
the capture (debounced + safely torn down). The HEAVY per-frame data goes over
the socket, never state.json. Capture only runs while mode is ``spectrum``.

The MINIMAL device list (real Pulse monitors + inputs, labeled) is written to
``devices.json`` (web-readable); the raw ALSA/plugin nodes are excluded.

Run::

    python -m checkout.audioviz            # capture + stream
    python -m checkout.audioviz --list     # enumerate devices -> devices.json
"""

from __future__ import annotations

import argparse
import shutil
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime

from . import config, spectrum
from .state import atomic_write_json, load_state

# Capture params. BLOCK samples per FFT frame; smaller = tighter timing (more
# frames/s, lower per-frame latency) at the cost of coarser low-frequency
# resolution. 256 @ 44.1kHz ~= 172 frames/s — well above the daemon's ~21fps
# render (newest-frame-wins), bench-tuned for snappy bars with acceptable bass.
# Tunable: raise (512/1024) for finer bass, lower for tighter timing.
BLOCK = 256
DEFAULT_RATE = 44100
ZERO_FRAME = [0] * spectrum.NUM_BARS

# parec MUST request a low latency or it BLOCK-BUFFERS ~750ms and dumps audio in
# bursts (bench-proven v0.9.6): ~30 chunks at 0ms apart, then a ~760ms gap,
# repeating — which the daemon saw as a pop-to-top / fall-to-zero pump plus a
# 1-2s delay. `--latency-msec` makes the gaps small + steady (smooth). Tunable:
# higher = burstier/laggier, lower = more wakeups; 10ms is bench-tuned (tighter
# than the original 20ms).
PAREC_LATENCY_MS = 10

# Supervisor cadence + restart debounce (coalesce rapid device switches).
POLL_MS = 200
RESTART_DEBOUNCE_MS = 400
IDLE_SLEEP_S = 0.05

_UNSET = object()
_stop = False


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] audioviz: {msg}", flush=True)


def _handle_signal(signum, frame) -> None:
    global _stop
    _stop = True


def _now_ms() -> float:
    return time.monotonic() * 1000.0


# --- pulse (pactl) enumeration ----------------------------------------------
def _run_cmd(args, timeout: float = 2.0) -> str | None:
    """Run a command, returning stdout on success or None (missing/error)."""
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout if res.returncode == 0 else None


def parse_pulse_sources(short_text: str | None) -> list[dict]:
    """Parse ``pactl list sources short`` rows into ``{name, is_monitor}``."""
    out: list[dict] = []
    for line in (short_text or "").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[1].strip():
            name = parts[1].strip()
            out.append({"name": name, "is_monitor": name.endswith(".monitor")})
    return out


def parse_source_descriptions(long_text: str | None) -> dict:
    """Map source name → human Description from ``pactl list sources`` (long)."""
    desc: dict = {}
    cur = None
    for line in (long_text or "").splitlines():
        s = line.strip()
        if s.startswith("Name:"):
            cur = s[len("Name:"):].strip()
        elif s.startswith("Description:") and cur:
            desc[cur] = s[len("Description:"):].strip()
            cur = None
    return desc


def default_sink_monitor() -> str | None:
    """The monitor source of the current default sink (``<sink>.monitor``)."""
    out = _run_cmd(["pactl", "get-default-sink"])
    if not out:
        return None
    sink = out.strip()
    return f"{sink}.monitor" if sink else None


def _pretty_monitor(name: str) -> str:
    base = name[:-len(".monitor")] if name.endswith(".monitor") else name
    return base.replace("alsa_output.", "")


# --- portaudio (mic) enumeration --------------------------------------------
def enumerate_devices() -> list[dict]:
    """PortAudio INPUT devices (mics) as plain dicts; empty on any failure."""
    try:
        import sounddevice as sd
    except Exception as exc:  # PortAudio missing, etc.
        log(f"sounddevice unavailable: {exc}")
        return []
    out: list[dict] = []
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) <= 0:
                continue
            name = d.get("name", "")
            out.append(
                {
                    "index": i,
                    "name": name,
                    "max_input_channels": int(d["max_input_channels"]),
                    "is_monitor": "monitor" in name.lower(),
                    "default_samplerate": float(
                        d.get("default_samplerate", DEFAULT_RATE)
                    ),
                }
            )
    except Exception as exc:
        log(f"device query failed: {exc}")
        return []
    return out


# --- unified, LABELED device list -------------------------------------------
def build_device_list(
    pulse_sources: list[dict] | None = None,
    descriptions: dict | None = None,
    inputs: list[dict] | None = None,
) -> list[dict]:
    """Combine Pulse monitors (system audio) + PortAudio inputs (mic), labeled.

    Each entry: ``{id, label, kind, is_monitor, backend, ...}`` where ``id`` is
    the value the UI writes into ``audio_device`` (a monitor source NAME for
    monitors, the PortAudio index string for inputs). Args injectable for tests.
    """
    if pulse_sources is None:
        pulse_sources = parse_pulse_sources(_run_cmd(["pactl", "list", "sources", "short"]))
    if descriptions is None:
        descriptions = parse_source_descriptions(_run_cmd(["pactl", "list", "sources"]))
    if inputs is None:
        inputs = enumerate_devices()

    devices: list[dict] = []
    # Pulse sources are the REAL devices: actual output monitors + capture inputs.
    # Using them (not PortAudio) keeps the list MINIMAL — the raw ALSA plugin /
    # hw:* / rate-converter / per-app-stream nodes PortAudio enumerates never
    # appear. A handful of monitors + the real inputs, each labeled.
    for s in pulse_sources:
        name = s["name"]
        label = descriptions.get(name) or _pretty_monitor(name)
        devices.append(
            {
                "id": name,
                "label": label,
                "kind": "monitor" if s.get("is_monitor") else "input",
                "is_monitor": bool(s.get("is_monitor")),
                "backend": "pulse",
            }
        )
    if not devices:
        # Fallback: no pactl/Pulse at all — enumerate PortAudio inputs (mic only).
        for d in (inputs if inputs is not None else enumerate_devices()):
            if d.get("is_monitor"):
                continue
            devices.append(
                {
                    "id": str(d["index"]),
                    "label": d["name"],
                    "kind": "input",
                    "is_monitor": False,
                    "backend": "portaudio",
                    "index": d["index"],
                    "default_samplerate": d.get("default_samplerate", DEFAULT_RATE),
                }
            )
    return devices


def default_source_name() -> str | None:
    """The current default INPUT source (``pactl get-default-source``), for mic."""
    out = _run_cmd(["pactl", "get-default-source"])
    if not out:
        return None
    return out.strip() or None


def write_devices(devices, default_monitor=None, default_source=None,
                  path: str | None = None) -> None:
    """Atomically write the labeled device list for the UI selector."""
    atomic_write_json(
        path or config.DEVICES_PATH,
        {
            "devices": devices,
            "default_monitor": default_monitor,
            "default_source": default_source,
            "updated_at": datetime.now().isoformat(),
        },
    )


# --- capture selection (pure) -----------------------------------------------
def find_device(devices: list[dict], source: str, device=None) -> int | None:
    """Legacy PortAudio input chooser (kept for the mic path + tests).

    ``device`` (index or name substring) wins; ``source == "system"`` → first
    monitor; else None = default input.
    """
    inputs = [d for d in devices if d.get("max_input_channels", 0) > 0]
    if device not in (None, "", "default"):
        try:
            idx = int(device)
            if any(d["index"] == idx for d in inputs):
                return idx
        except (ValueError, TypeError):
            pass
        needle = str(device).lower()
        for d in inputs:
            if needle in d["name"].lower():
                return d["index"]
        return None
    if source == "system":
        for d in inputs:
            if d.get("is_monitor"):
                return d["index"]
        return None
    return None


def _resolve_monitor(device, monitors: list[dict], default_monitor) -> str | None:
    if device not in (None, "", "default"):
        d = str(device)
        for m in monitors:
            if d == m["id"] or d.lower() in m["label"].lower():
                return m["id"]
        if d.endswith(".monitor"):
            return d  # raw monitor name override (not in the cached list)
    if default_monitor and any(m["id"] == default_monitor for m in monitors):
        return default_monitor
    if monitors:
        return monitors[0]["id"]
    return default_monitor  # trust pactl's default even if the list came up empty


def _resolve_input(device, inputs: list[dict]) -> int | None:
    """PortAudio fallback input chooser (by index/label)."""
    if device not in (None, "", "default"):
        d = str(device)
        try:
            idx = int(d)
            if any(i.get("index") == idx for i in inputs):
                return idx
        except (ValueError, TypeError):
            pass
        for i in inputs:
            if d.lower() in i["label"].lower():
                return i.get("index")
        return None
    return None  # default input device


def _resolve_pulse_input(device, inputs: list[dict], default_source) -> str | None:
    if device not in (None, "", "default"):
        d = str(device)
        for i in inputs:
            if d == i["id"] or d.lower() in i["label"].lower():
                return i["id"]
        if not d.isdigit():
            return d  # raw source name override
    if default_source and (not inputs or any(i["id"] == default_source for i in inputs)):
        return default_source
    if inputs:
        return inputs[0]["id"]
    return default_source


def select_capture(source, device, devices, default_monitor, default_source=None):
    """Resolve (source, device) to a capture key, or None for no capture.

    - system → ``("pulse", monitor_name)`` (the chosen / default-sink / first
      monitor), or ``None`` if no monitor exists — emit zeros, NEVER the mic.
    - mic → ``("pulse", input_name)`` when Pulse inputs / a default source exist
      (captured by pw-record like system), else the PortAudio fallback
      ``("portaudio", idx)``.
    """
    monitors = [d for d in devices if d.get("is_monitor")]
    if source == "system":
        name = _resolve_monitor(device, monitors, default_monitor)
        return ("pulse", name) if name else None
    pulse_inputs = [d for d in devices
                    if d.get("kind") == "input" and d.get("backend") == "pulse"]
    if pulse_inputs or default_source:
        name = _resolve_pulse_input(device, pulse_inputs, default_source)
        if name:
            return ("pulse", name)
    pa_inputs = [d for d in devices
                 if d.get("kind") == "input" and d.get("backend") == "portaudio"]
    return ("portaudio", _resolve_input(device, pa_inputs))


# --- debounce ----------------------------------------------------------------
class ChangeDebouncer:
    """Coalesce rapid value changes: :meth:`due` is True once the value has been
    stable (unchanged) for ``window_ms``. Switching quickly through the device
    dropdown therefore yields ONE restart at the final value."""

    def __init__(self, window_ms: float = RESTART_DEBOUNCE_MS) -> None:
        self.window_ms = window_ms
        self._pending = _UNSET
        self._since = 0.0

    def observe(self, value, now_ms: float) -> None:
        if self._pending is _UNSET or value != self._pending:
            self._pending = value
            self._since = now_ms

    def peek(self):
        return self._pending

    def due(self, now_ms: float) -> bool:
        return self._pending is not _UNSET and (now_ms - self._since) >= self.window_ms

    def take(self):
        value = self._pending
        self._pending = _UNSET
        return value


# --- capture backends --------------------------------------------------------
def _capture_tool() -> str | None:
    # Prefer parec: bench-proven (v0.9.5) to deliver SUSTAINED continuous audio
    # from a `.monitor` source (RMS ~0.2 for the whole stream). pw-record /
    # pw-cat, piped, deliver ONE good buffer then STARVE to near-silence (RMS
    # ~0.00003) — that was the real cause of the spectrum "fills then dies", not
    # the DSP. (This reverses the v0.9.1 guess; that earlier "parec emits nothing"
    # was a bad invocation — `parec --device=<src> --format=s16le ...` works.)
    # pw-record is kept only as a fallback when parec is unavailable.
    for tool in ("parec", "pw-record"):
        if shutil.which(tool):
            return tool
    return None


def parec_command(tool: str, source: str, rate: int, channels: int) -> list[str]:
    """Build the raw-PCM (s16le) capture command for a Pulse source.

    parec is the PRIMARY tool. It MUST request a low latency (``--latency-msec``)
    or it block-buffers ~750ms and dumps audio in bursts → a visible pump + delay
    (the root cause of the long spectrum-tuning saga; bench-proven v0.9.6).
    pw-record is a deprioritized fallback (it starves a piped reader after one
    buffer here, v0.9.5) and has no equivalent low-latency flag we rely on."""
    if tool == "pw-record":
        return ["pw-record", "--target", source, "--rate", str(rate),
                "--channels", str(channels), "--format", "s16", "-"]
    # parec (pacat --record): raw s16le PCM to stdout, LOW-LATENCY (not block-buffered).
    return ["parec", f"--device={source}", "--format=s16le",
            f"--rate={rate}", f"--channels={channels}",
            f"--latency-msec={PAREC_LATENCY_MS}"]


def _read_exact(stream, nbytes: int, stopped) -> bytes | None:
    """Read exactly ``nbytes`` from a pipe, accumulating partial reads.

    Returns the full block, or None at EOF / when ``stopped()`` goes True. A raw
    pipe ``read(n)`` may return fewer than ``n`` bytes; without accumulating, the
    leftover desyncs the s16le frame boundary and audio is dropped."""
    buf = bytearray()
    while len(buf) < nbytes:
        if stopped():
            return None
        chunk = stream.read(nbytes - len(buf))
        if not chunk:
            return None  # EOF
        buf += chunk
    return bytes(buf)


class ParecCapture:
    """System-audio capture via a pw-record/parec subprocess + reader thread."""

    def __init__(self, source_name, rate, on_chunk, channels=2, tool=None):
        self.source = source_name
        self.rate = int(rate)
        self.on_chunk = on_chunk
        self.channels = channels
        self.tool = tool or _capture_tool()
        self._proc = None
        self._thread = None
        self._stop = False

    def start(self) -> None:
        if self.tool is None:
            raise RuntimeError("no parec/pw-record found (install pipewire-pulse)")
        import numpy as np  # fail early + clearly if numpy is missing
        self._np = np
        cmd = parec_command(self.tool, self.source, self.rate, self.channels)
        self._proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
        )
        self._stop = False
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self) -> None:
        np = self._np
        nbytes = BLOCK * self.channels * 2  # s16le = 2 bytes/sample
        proc = self._proc
        try:
            while not self._stop and proc is not None and proc.poll() is None:
                # Read EXACTLY a full block: a pipe read can return fewer bytes,
                # so accumulate (else partial reads desync and drop audio).
                data = _read_exact(proc.stdout, nbytes, lambda: self._stop)
                if data is None:
                    break
                arr = np.frombuffer(data, dtype="<i2").astype("float32") / 32768.0
                # DEINTERLEAVE s16le: samples alternate L,R,L,R... Keep L and R
                # SEPARATE (stereo layouts need per-channel data; the full layout
                # derives mono = (L+R)/2 downstream — one capture path).
                if self.channels >= 2:
                    stereo = arr.reshape(-1, self.channels)
                    left, right = stereo[:, 0], stereo[:, 1]
                else:
                    left = right = arr
                try:
                    self.on_chunk(left, right, self.rate)
                except Exception:
                    pass
        except Exception as exc:
            log(f"capture reader stopped: {exc}")

    def stop(self) -> None:
        self._stop = True
        proc, self._proc = self._proc, None
        if proc is not None:
            for step in (proc.terminate, lambda: proc.wait(timeout=1.0)):
                try:
                    step()
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=1.0)


class SoundDeviceCapture:
    """Mic capture via PortAudio with a HARDENED teardown (full stop+close)."""

    def __init__(self, device_index, rate, on_chunk):
        self.device_index = device_index
        self.rate = int(rate)
        self.on_chunk = on_chunk
        self._stream = None

    def start(self) -> None:
        import sounddevice as sd

        def _cb(indata, frames, time_info, status):
            mono = indata[:, 0] if getattr(indata, "ndim", 1) > 1 else indata
            try:
                # Mic is mono: feed it as BOTH channels so the stereo layouts work
                # (L == R — a centered signal) and the full layout's (L+R)/2 = mono.
                self.on_chunk(mono, mono, self.rate)
            except Exception:
                pass

        stream = sd.InputStream(
            device=self.device_index, channels=1, samplerate=self.rate,
            blocksize=BLOCK, dtype="float32", callback=_cb,
        )
        stream.start()
        self._stream = stream

    def stop(self) -> None:
        # Null the handle FIRST so a re-entrant/failed teardown can't reuse it,
        # then fully stop() THEN close() — each guarded so a bad prior stream
        # can't block (or crash) the next open. PortAudio segfaults if a stream
        # isn't cleanly torn down before the next is opened.
        stream, self._stream = self._stream, None
        if stream is None:
            return
        for step in (stream.stop, stream.close):
            try:
                step()
            except Exception as exc:
                log(f"portaudio teardown: {exc}")


# --- DSP engine --------------------------------------------------------------
class AudioViz:
    """Turns audio chunks into smoothed bar heights and streams them."""

    def __init__(self, socket_path: str | None = None) -> None:
        self.sender = spectrum.SpectrumSender(socket_path)
        # "sensitivity" biases the auto-gain (1.0 = neutral); kept under the
        # legacy audio_gain field for back-compat.
        self.sensitivity = 1.0
        self.decay = 0.85
        self.layout = "full"
        self._ref = spectrum.REF_FLOOR   # auto-gain running reference (SHARED L/R)
        self._np = None
        self._window = None
        self._edges = None       # full: 20-band edges
        self._edges_v = None     # stereo_v: 19-band edges
        self._n = None
        self._rate = None
        self._reset_levels()

    def _reset_levels(self) -> None:
        """Zero every layout's smoothing state (on init / layout switch)."""
        self.levels = [0.0] * spectrum.NUM_BARS                 # full
        self.levels_l = [0.0] * spectrum.STEREO_BANDS           # stereo_v left
        self.levels_r = [0.0] * spectrum.STEREO_BANDS           # stereo_v right
        self.level_l = 0.0                                      # stereo_h left
        self.level_r = 0.0                                      # stereo_h right

    def configure(self, sensitivity, decay, layout="full") -> None:
        try:
            self.sensitivity = float(sensitivity)
        except (TypeError, ValueError):
            self.sensitivity = 1.0
        try:
            self.decay = float(decay)
        except (TypeError, ValueError):
            self.decay = 0.85
        layout = layout if layout in spectrum.LAYOUTS else "full"
        if layout != self.layout:
            # Switching layouts: reset the per-layout smoothing + the shared ref so
            # the new layout converges cleanly (no carryover from the old shape).
            self.layout = layout
            self._reset_levels()
            self._ref = spectrum.REF_FLOOR

    def _ensure_dsp(self, n: int, rate: float) -> None:
        import numpy as np

        if self._window is None or self._n != n or self._rate != rate:
            self._np = np
            self._n = n
            self._rate = rate
            self._window = np.hanning(n)
            self._edges = spectrum.log_band_edges(spectrum.NUM_BARS, rate, n)
            self._edges_v = spectrum.log_band_edges(spectrum.STEREO_BANDS, rate, n)

    # --- per-layout analysis -------------------------------------------------
    def process(self, samples, rate: float) -> list[int]:
        """One MONO audio chunk → 20 integer bar heights (the full layout path).

        AUTO-GAIN: normalize against a running reference so bars are volume-
        independent (content-driven). Below the silence floor, output ~0 and let
        the reference release (don't amplify silence/hiss into full-scale)."""
        self._ensure_dsp(len(samples), rate)
        np = self._np
        arr = np.asarray(samples, dtype=float)
        rms = float(np.sqrt(np.mean(np.square(arr)))) if arr.size else 0.0
        mag = np.abs(np.fft.rfft(arr * self._window))
        bands = spectrum.bucketize(mag, self._edges)

        if rms < spectrum.SILENCE_FLOOR_RMS:
            self._ref = spectrum.update_ref(self._ref, 0.0)
            new = [0] * spectrum.NUM_BARS
        else:
            self._ref = spectrum.update_ref(self._ref, spectrum.band_mean(bands))
            new = spectrum.normalize_levels(bands, self._ref, self.sensitivity)

        self.levels = spectrum.decay_levels(self.levels, new, self.decay)
        return [int(round(x)) for x in self.levels]

    def process_frame(self, left, right, rate: float) -> bytes:
        """One STEREO chunk (L, R) → the encoded tagged frame for the active layout.

        full     -> mono = (L+R)/2 through the 20-band path.
        stereo_v -> each channel FFT'd to 19 bands, SHARED auto-gain.
        stereo_h -> one overall level per channel (0..95), SHARED auto-gain.
        """
        self._ensure_dsp(len(left), rate)
        np = self._np
        L = np.asarray(left, dtype=float)
        R = np.asarray(right, dtype=float)
        if self.layout == "stereo_v":
            return self._frame_stereo_v(L, R)
        if self.layout == "stereo_h":
            return self._frame_stereo_h(L, R)
        return spectrum.encode_full(self.process((L + R) * 0.5, rate))

    def _frame_stereo_v(self, L, R) -> bytes:
        np = self._np
        w = self._window
        rms = (float(np.sqrt((np.mean(np.square(L)) + np.mean(np.square(R))) / 2.0))
               if L.size else 0.0)
        bands_l = spectrum.bucketize(np.abs(np.fft.rfft(L * w)), self._edges_v)
        bands_r = spectrum.bucketize(np.abs(np.fft.rfft(R * w)), self._edges_v)
        if rms < spectrum.SILENCE_FLOOR_RMS:
            self._ref = spectrum.update_ref(self._ref, 0.0)
            new_l = [0] * spectrum.STEREO_BANDS
            new_r = [0] * spectrum.STEREO_BANDS
        else:
            # SHARED reference across BOTH channels (mean of all 38 bands) so a
            # louder channel reads visibly louder — seeing the stereo BALANCE is
            # the point. (Independent per-channel gain would hide the balance.)
            self._ref = spectrum.update_ref(
                self._ref, spectrum.band_mean(list(bands_l) + list(bands_r)))
            new_l = spectrum.normalize_levels(
                bands_l, self._ref, self.sensitivity, max_bar=spectrum.STEREO_V_MAX)
            new_r = spectrum.normalize_levels(
                bands_r, self._ref, self.sensitivity, max_bar=spectrum.STEREO_V_MAX)
        self.levels_l = spectrum.decay_levels(self.levels_l, new_l, self.decay)
        self.levels_r = spectrum.decay_levels(self.levels_r, new_r, self.decay)
        return spectrum.encode_stereo_v(
            [int(round(x)) for x in self.levels_l],
            [int(round(x)) for x in self.levels_r])

    def _frame_stereo_h(self, L, R) -> bytes:
        np = self._np
        rms_l = float(np.sqrt(np.mean(np.square(L)))) if L.size else 0.0
        rms_r = float(np.sqrt(np.mean(np.square(R)))) if R.size else 0.0
        if max(rms_l, rms_r) < spectrum.SILENCE_FLOOR_RMS:
            self._ref = spectrum.update_ref(self._ref, 0.0)
            new_l = new_r = 0
        else:
            # SHARED reference (mean broadband loudness of both channels), so the
            # louder channel's meter is visibly longer — the balance is readable.
            self._ref = spectrum.update_ref(self._ref, (rms_l + rms_r) / 2.0)
            new_l = spectrum.normalize_levels(
                [rms_l], self._ref, self.sensitivity, max_bar=spectrum.STEREO_H_MAX)[0]
            new_r = spectrum.normalize_levels(
                [rms_r], self._ref, self.sensitivity, max_bar=spectrum.STEREO_H_MAX)[0]
        self.level_l = spectrum.decay_levels([self.level_l], [new_l], self.decay)[0]
        self.level_r = spectrum.decay_levels([self.level_r], [new_r], self.decay)[0]
        return spectrum.encode_stereo_h(int(round(self.level_l)), int(round(self.level_r)))

    # --- output --------------------------------------------------------------
    def feed(self, left, right, rate: float) -> None:
        """Analyze a stereo chunk and stream the active layout's frame."""
        self.sender.send(self.process_frame(left, right, rate))

    def send_zeros(self) -> None:
        """Relax the ACTIVE layout's levels toward 0 and send (so a re-start
        doesn't jump). Each layout drains its own smoothing state."""
        if self.layout == "stereo_v":
            zeros = [0] * spectrum.STEREO_BANDS
            self.levels_l = spectrum.decay_levels(self.levels_l, zeros, self.decay)
            self.levels_r = spectrum.decay_levels(self.levels_r, zeros, self.decay)
            self.sender.send(spectrum.encode_stereo_v(
                [int(round(x)) for x in self.levels_l],
                [int(round(x)) for x in self.levels_r]))
        elif self.layout == "stereo_h":
            self.level_l = spectrum.decay_levels([self.level_l], [0], self.decay)[0]
            self.level_r = spectrum.decay_levels([self.level_r], [0], self.decay)[0]
            self.sender.send(spectrum.encode_stereo_h(
                int(round(self.level_l)), int(round(self.level_r))))
        else:
            self.levels = spectrum.decay_levels(self.levels, ZERO_FRAME, self.decay)
            self.sender.send(spectrum.encode_full([int(round(x)) for x in self.levels]))

    def close(self) -> None:
        self.sender.close()


# --- supervisor --------------------------------------------------------------
def _read_settings(state: dict) -> tuple[str, object, float, float, str]:
    layout = state.get("spectrum_layout", "full")
    return (
        state.get("audio_source", "system"),
        state.get("audio_device"),
        state.get("audio_gain", 1.0),
        state.get("audio_decay", 0.85),
        layout if layout in spectrum.LAYOUTS else "full",
    )


def _input_rate(devices, idx) -> float:
    for d in devices:
        if d.get("kind") == "input" and d.get("index") == idx:
            return float(d.get("default_samplerate", DEFAULT_RATE))
    return float(DEFAULT_RATE)


def _safe_stop(capture) -> None:
    if capture is None:
        return
    try:
        capture.stop()
    except Exception as exc:
        log(f"capture stop failed: {exc}")


def make_capture(key, on_chunk, devices):
    """Construct (but don't start) the capture backend for a key, or None."""
    if key is None:
        return None
    kind, ident = key
    if kind == "pulse":
        return ParecCapture(ident, DEFAULT_RATE, on_chunk)
    return SoundDeviceCapture(ident, _input_rate(devices, ident), on_chunk)


def _restart_capture(old, key, on_chunk, devices):
    """Safely tear down ``old`` and start the capture for ``key``.

    A failed OPEN is caught and logged — the result is just "no capture / zeros",
    never a crash. Returns the new capture, or None.
    """
    _safe_stop(old)
    if key is None:
        return None
    kind, ident = key
    capture = make_capture(key, on_chunk, devices)
    try:
        capture.start()
    except Exception as exc:
        log(f"open failed [{kind}] {ident!r}: {exc}; emitting zeros")
        _safe_stop(capture)
        return None
    log(f"capturing [{kind}] {ident if ident is not None else 'default'}")
    return capture


def run(socket_path: str | None = None) -> int:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    av = AudioViz(socket_path)
    devices = build_device_list()
    default_monitor = default_sink_monitor()
    default_source = default_source_name()
    write_devices(devices, default_monitor, default_source)
    monitors = [d for d in devices if d.get("is_monitor")]
    log(f"{len(devices)} devices ({len(monitors)} monitors); "
        f"default monitor: {default_monitor}")

    on_chunk = lambda l, r, rate: av.feed(l, r, rate)  # noqa: E731
    debouncer = ChangeDebouncer(RESTART_DEBOUNCE_MS)
    applied = _UNSET
    capture = None
    last_poll = -1e9

    while not _stop:
        now = _now_ms()
        if now - last_poll >= POLL_MS:
            last_poll = now
            state = load_state()
            source, device, gain, decay, layout = _read_settings(state)
            av.configure(gain, decay, layout)
            # Capture only while in spectrum mode (no parec churn otherwise).
            desired = (
                select_capture(source, device, devices, default_monitor, default_source)
                if state.get("mode") == "spectrum"
                else None
            )
            debouncer.observe(desired, now)

        first = applied is _UNSET
        if (first or debouncer.peek() != applied) and debouncer.due(now):
            target = debouncer.take()
            capture = _restart_capture(capture, target, on_chunk, devices)
            applied = target
            if capture is None and target is not None:
                log("capture unavailable for the selected source; emitting zeros")

        if capture is None:
            av.send_zeros()
        time.sleep(IDLE_SLEEP_S)

    _safe_stop(capture)
    av.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="checkout.audioviz", description=__doc__)
    parser.add_argument(
        "--list", action="store_true",
        help="enumerate devices to devices.json (and stdout) then exit",
    )
    args = parser.parse_args(argv)
    if args.list:
        devices = build_device_list()
        default_monitor = default_sink_monitor()
        default_source = default_source_name()
        write_devices(devices, default_monitor, default_source)
        for kind, title in (("monitor", "MONITORS (system)"), ("input", "INPUTS (mic)")):
            print(title)
            for d in (x for x in devices if x["kind"] == kind):
                default_id = default_monitor if kind == "monitor" else default_source
                mark = "*" if d["id"] == default_id else " "
                print(f"  {mark} {d['label']}")
        if not devices:
            print("(no devices found — is pipewire-pulse / PortAudio installed?)")
        print(f"\ndefault monitor: {default_monitor or '(none)'}")
        print(f"default input:   {default_source or '(none)'}")
        return 0
    return run()


if __name__ == "__main__":
    sys.exit(main())
