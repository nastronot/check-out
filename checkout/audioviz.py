"""checkout.audioviz — audio capture + FFT → 20 log bands → socket stream.

A SEPARATE process (it never touches the serial port). It captures audio with
``sounddevice`` (PortAudio), runs an FFT, buckets into 20 log-spaced bands, maps
each to a height 0..14 with attack-fast/release-slow smoothing, and STREAMS the
heights to the daemon over the unix datagram socket (:mod:`checkout.spectrum`).

SETTINGS come from ``state.json`` (``audio_source`` / ``audio_device`` /
``audio_gain`` / ``audio_decay``) — re-read on mtime change so the UI sliders
apply live; the source/device change restarts the capture stream. The HEAVY
per-frame data goes over the socket, never state.json.

It enumerates capture devices to ``devices.json`` (web-readable) for the UI
selector. Missing PortAudio / no device / no monitor are handled gracefully:
it logs once and streams zeros (so the daemon's bars decay to flat) while
retrying, rather than crashing.

Run::

    python -m checkout.audioviz            # capture + stream
    python -m checkout.audioviz --list     # just enumerate devices -> devices.json
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from datetime import datetime

from . import config, spectrum
from .state import atomic_write_json, load_state

# Capture params. BLOCK samples per FFT frame; ~43 frames/s at 44.1kHz/1024 —
# above the daemon's ~21fps render, which is fine (newest-frame-wins).
BLOCK = 1024
DEFAULT_RATE = 44100
SETTINGS_POLL_S = 0.5     # how often to re-check state.json for live settings
ZERO_FRAME = [0] * spectrum.NUM_BARS

_stop = False


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] audioviz: {msg}", flush=True)


def _handle_signal(signum, frame) -> None:
    global _stop
    _stop = True


# --- device enumeration ------------------------------------------------------
def enumerate_devices() -> list[dict]:
    """Return the available INPUT devices as plain dicts (empty on any failure).

    A device whose name contains "monitor" is flagged ``is_monitor`` — that's how
    a PipeWire/PulseAudio loopback-of-playback ("system" audio) source appears.
    """
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


def write_devices(devices: list[dict], path: str | None = None) -> None:
    """Atomically write the device list for the UI selector (devices.json)."""
    atomic_write_json(
        path or config.DEVICES_PATH,
        {"devices": devices, "updated_at": datetime.now().isoformat()},
    )


def find_device(devices: list[dict], source: str, device=None) -> int | None:
    """Choose a capture device index (pure logic, unit-testable).

    - An explicit ``device`` (int index or name substring) wins when it matches
      an input device; an explicit-but-missing device returns None.
    - ``source == "system"`` → the first monitor input (loopback of playback).
    - ``source == "mic"`` (or no monitor found) → None, i.e. PortAudio's default
      input device.
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
        return None  # asked-for device not present
    if source == "system":
        for d in inputs:
            if d.get("is_monitor"):
                return d["index"]
        return None  # no monitor -> caller falls back to default + logs
    return None      # "mic" -> default input device


# --- DSP engine --------------------------------------------------------------
class AudioViz:
    """Turns audio chunks into smoothed bar heights and streams them."""

    def __init__(self, socket_path: str | None = None) -> None:
        self.sender = spectrum.SpectrumSender(socket_path)
        self.gain = 1.0
        self.decay = 0.85
        self.levels = [0.0] * spectrum.NUM_BARS
        self._np = None
        self._window = None
        self._edges = None
        self._n = None
        self._rate = None

    def configure(self, gain, decay) -> None:
        try:
            self.gain = float(gain)
        except (TypeError, ValueError):
            self.gain = 1.0
        try:
            self.decay = float(decay)
        except (TypeError, ValueError):
            self.decay = 0.85

    def _ensure_dsp(self, n: int, rate: float) -> None:
        import numpy as np

        if self._edges is None or self._n != n or self._rate != rate:
            self._np = np
            self._n = n
            self._rate = rate
            self._window = np.hanning(n)
            self._edges = spectrum.log_band_edges(spectrum.NUM_BARS, rate, n)

    def process(self, samples, rate: float) -> list[int]:
        """One audio chunk (1-D float samples) → 20 integer bar heights."""
        self._ensure_dsp(len(samples), rate)
        np = self._np
        windowed = np.asarray(samples, dtype=float) * self._window
        mag = np.abs(np.fft.rfft(windowed))
        bands = spectrum.bucketize(mag, self._edges)
        new = spectrum.to_levels(bands, gain=self.gain)
        self.levels = spectrum.decay_levels(self.levels, new, self.decay)
        return [int(round(x)) for x in self.levels]

    def send(self, heights) -> None:
        self.sender.send(heights)

    def send_zeros(self) -> None:
        # Let the running levels relax so a re-start doesn't jump.
        self.levels = spectrum.decay_levels(self.levels, ZERO_FRAME, self.decay)
        self.sender.send([int(round(x)) for x in self.levels])

    def close(self) -> None:
        self.sender.close()


# --- capture loop ------------------------------------------------------------
def _read_settings(state: dict) -> tuple[str, object, float, float]:
    return (
        state.get("audio_source", "system"),
        state.get("audio_device"),
        state.get("audio_gain", 1.0),
        state.get("audio_decay", 0.85),
    )


def run(socket_path: str | None = None) -> int:
    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    av = AudioViz(socket_path)
    devices = enumerate_devices()
    write_devices(devices)

    state = load_state()
    source, device, gain, decay = _read_settings(state)
    av.configure(gain, decay)

    try:
        import sounddevice as sd
    except Exception as exc:
        log(f"no audio backend ({exc}); streaming zeros. Install sounddevice.")
        return _zeros_loop(av)

    log(f"source={source} device={device!r} gain={gain} decay={decay}")
    warned_no_monitor = False

    while not _stop:
        idx = find_device(devices, source, device)
        if idx is None and source == "system" and not warned_no_monitor:
            log("no PipeWire/Pulse monitor source found; using default input")
            warned_no_monitor = True
        rate = _device_rate(devices, idx)

        def _callback(indata, frames, time_info, status):  # PortAudio thread
            if _stop:
                return
            mono = indata[:, 0] if getattr(indata, "ndim", 1) > 1 else indata
            try:
                av.send(av.process(mono, rate))
            except Exception:
                av.send(ZERO_FRAME)

        try:
            with sd.InputStream(
                device=idx, channels=1, samplerate=rate,
                blocksize=BLOCK, dtype="float32", callback=_callback,
            ):
                log(f"capturing on device {idx if idx is not None else 'default'} @ {rate:.0f}Hz")
                # Supervise: re-read settings on change; restart on source/device swap.
                while not _stop:
                    time.sleep(SETTINGS_POLL_S)
                    new_state = load_state()
                    nsrc, ndev, ngain, ndecay = _read_settings(new_state)
                    av.configure(ngain, ndecay)
                    if (nsrc, ndev) != (source, device):
                        source, device = nsrc, ndev
                        warned_no_monitor = False
                        log(f"source/device changed -> {source} {device!r}; restarting")
                        break  # leave the `with`, reopen the stream
                    if new_state.get("mode") != "spectrum":
                        # Not in spectrum: keep the stream but stop spamming the
                        # socket — a couple of zero frames let the daemon's bars
                        # rest if it happens to still be draining.
                        av.send_zeros()
        except Exception as exc:
            log(f"capture error ({exc}); retrying in 1s")
            _sleep_zeros(av, 1.0)
            devices = enumerate_devices()  # device list may have changed
            write_devices(devices)

    av.close()
    return 0


def _device_rate(devices: list[dict], idx) -> float:
    for d in devices:
        if d.get("index") == idx:
            return float(d.get("default_samplerate", DEFAULT_RATE))
    return float(DEFAULT_RATE)


def _zeros_loop(av: AudioViz) -> int:
    """Fallback when there's no audio backend at all: stream zeros until stopped."""
    while not _stop:
        av.send(ZERO_FRAME)
        time.sleep(1.0 / 30)
    av.close()
    return 0


def _sleep_zeros(av: AudioViz, seconds: float) -> None:
    end = time.monotonic() + seconds
    while not _stop and time.monotonic() < end:
        av.send_zeros()
        time.sleep(1.0 / 30)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="checkout.audioviz", description=__doc__)
    parser.add_argument(
        "--list", action="store_true",
        help="enumerate input devices to devices.json (and stdout) then exit",
    )
    args = parser.parse_args(argv)
    if args.list:
        devices = enumerate_devices()
        write_devices(devices)
        for d in devices:
            tag = " [monitor]" if d["is_monitor"] else ""
            print(f"{d['index']:>3}  {d['name']}{tag}")
        if not devices:
            print("(no input devices found)")
        return 0
    return run()


if __name__ == "__main__":
    sys.exit(main())
