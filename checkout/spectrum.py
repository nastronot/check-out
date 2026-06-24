"""Spectrum analyzer — shared protocol, bar rendering, and DSP helpers.

Three processes cooperate for SPECTRUM mode:

  - **audioviz** (:mod:`checkout.audioviz`): captures audio (mic / system
    monitor), runs an FFT, buckets into 20 log-spaced bands, maps each to a
    height 0..14, and STREAMS the heights over a unix DATAGRAM socket.
  - **daemon** (:mod:`checkout.daemon`): in spectrum mode, drains the socket to
    the LATEST frame each fast-loop iteration and renders double-height bars.
  - **web/UI**: mirrors the bars from ``status.json`` into the phosphor preview.

The HEAVY per-frame data (20 bar heights) goes over the socket — newest frame
wins (``SOCK_DGRAM``), so a slow reader can't back up a stream and there's no
filesystem churn. SETTINGS (source/device/gain/decay) go via ``state.json``.

This module is the PURE logic shared by daemon + audioviz (testable with no
PortAudio and no serial port) plus the daemon-side :class:`SpectrumReceiver` and
the audioviz-side :class:`SpectrumSender`.

BENCH-LOCKED params (do not retune): 9600 baud caps full-frame redraw at ~21fps;
double-height bars over 7 partial-height glyphs read cleanly; 20 bands × 14
levels fit the 2×20 glass.
"""

from __future__ import annotations

import math
import os
import socket

from . import config
from .driver import GLYPH_CODES, GLYPH_ROWS

# --- locked geometry ---------------------------------------------------------
NUM_BARS = 20            # one band per display column
LEVELS_PER_CELL = GLYPH_ROWS   # 7 partial-height glyphs per character cell
MAX_BAR = 2 * LEVELS_PER_CELL  # 14 — double-height (bottom cell then top cell)

# The first 7 of the 9 user-glyph slots hold the height glyphs (slot i -> a bar
# of i+1 lit rows). NOTE this OVERWRITES those user-glyph slots while in spectrum
# mode; the daemon re-applies state.glyphs on exit.
BAR_GLYPH_SLOTS = tuple(range(LEVELS_PER_CELL))  # 0..6

# --- socket / message protocol ----------------------------------------------
# A frame is exactly NUM_BARS bytes, each a height 0..MAX_BAR (one per bar). Tiny
# + fixed, so a single datagram is one whole frame and "newest wins" is natural
# (no sequence number needed — the daemon drains to the last datagram per loop).
SOCKET_PATH = config.SPECTRUM_SOCKET
_RECV_BUF = 256


def encode_frame(heights) -> bytes:
    """Pack bar heights into the NUM_BARS-byte wire frame (clamped 0..MAX_BAR)."""
    vals = [max(0, min(MAX_BAR, int(h))) for h in list(heights)[:NUM_BARS]]
    vals += [0] * (NUM_BARS - len(vals))
    return bytes(vals)


def decode_frame(data) -> list[int] | None:
    """Decode a wire frame to NUM_BARS heights, or None if it's too short/empty."""
    if not data or len(data) < NUM_BARS:
        return None
    return [max(0, min(MAX_BAR, b)) for b in data[:NUM_BARS]]


# --- bar glyphs + cell mapping ----------------------------------------------
def bar_glyph(height: int) -> list[int]:
    """Editor-natural rows (7 ints, low 5 bits = cols) for a bottom-anchored bar.

    ``height`` lit rows (0..7), full width (``0x1F``): row ``r`` is lit iff
    ``r >= GLYPH_ROWS - height`` (so a height-1 bar lights only the bottom row).
    """
    h = max(0, min(GLYPH_ROWS, int(height)))
    return [0x1F if r >= (GLYPH_ROWS - h) else 0x00 for r in range(GLYPH_ROWS)]


def bar_glyphs() -> dict[int, list[int]]:
    """The 7 height glyphs keyed by slot (slot i -> a bar of i+1 lit rows)."""
    return {slot: bar_glyph(slot + 1) for slot in BAR_GLYPH_SLOTS}


_SPACE = " "


def bar_to_cells(height: int) -> tuple[str, str]:
    """Map a bar height 0..14 to ``(top_char, bottom_char)`` display characters.

    The BOTTOM cell fills first (heights 1..7 → the glyph code for that height,
    top empty), then the TOP cell (heights 8..14 → bottom full + top partial).
    An empty bar is two spaces. The chars are glyph CODE bytes (slots 0..6),
    which the driver's ``_sanitize`` allow-lists.
    """
    h = max(0, min(MAX_BAR, int(height)))
    if h == 0:
        return (_SPACE, _SPACE)
    if h <= LEVELS_PER_CELL:                       # 1..7: bottom partial, top empty
        return (_SPACE, chr(GLYPH_CODES[h - 1]))
    # 8..14: bottom full (height 7 = slot 6), top partial (height h-7)
    top_code = GLYPH_CODES[h - 1 - LEVELS_PER_CELL]
    bottom_code = GLYPH_CODES[LEVELS_PER_CELL - 1]
    return (chr(top_code), chr(bottom_code))


def render_spectrum(heights) -> tuple[str, str]:
    """Render 20 bar heights to the (top, bottom) 20-char display line pair."""
    cells = [bar_to_cells(h) for h in list(heights)[:NUM_BARS]]
    cells += [(_SPACE, _SPACE)] * (NUM_BARS - len(cells))
    return "".join(c[0] for c in cells), "".join(c[1] for c in cells)


def decay_heights(heights, step: int = 1) -> list[int]:
    """Decay every bar toward 0 by ``step`` (used when the audio feed is stale —
    so the bars drain instead of freezing on the last frame)."""
    return [max(0, int(h) - step) for h in heights]


# --- DSP helpers (audioviz; pure, numpy-free so they unit-test anywhere) ------
def log_band_edges(
    num_bands: int, sample_rate: float, n_fft: int,
    fmin: float = 50.0, fmax: float | None = None,
) -> list[int]:
    """``num_bands+1`` rFFT bin indices marking LOG-spaced band edges.

    Edges are forced strictly increasing where bins allow (so each band spans at
    least one bin until they run out at the top), clamped to the rFFT bin count.
    """
    n_bins = n_fft // 2 + 1
    nyq = sample_rate / 2.0
    fmax = min(fmax or nyq, nyq)
    fmin = max(1.0, min(fmin, fmax / 2))
    edges: list[int] = []
    prev = -1
    for i in range(num_bands + 1):
        frac = i / num_bands
        freq = fmin * (fmax / fmin) ** frac
        b = int(round(freq * n_fft / sample_rate))
        b = max(prev + 1, b)            # strictly increasing while bins remain
        b = min(b, n_bins - 1)
        edges.append(b)
        prev = b
    return edges


def bucketize(magnitudes, edges) -> list[float]:
    """Average ``magnitudes`` within each ``[edges[i], edges[i+1])`` band."""
    n = len(magnitudes)
    out: list[float] = []
    for i in range(len(edges) - 1):
        a = edges[i]
        b = min(max(edges[i + 1], a + 1), n)
        seg = magnitudes[a:b]
        out.append(float(sum(seg) / len(seg)) if len(seg) else 0.0)
    return out


def to_levels(
    values, gain: float = 1.0, max_bar: int = MAX_BAR, floor_db: float = -55.0,
) -> list[int]:
    """Map band magnitudes to integer bar heights 0..``max_bar`` on a dB scale.

    Each magnitude is scaled by ``gain`` then converted to dB; ``floor_db``..0 dB
    maps linearly onto 0..max_bar (clamped). A larger gain lifts quiet signals.
    Legacy fixed-gain mapping — the live path uses :func:`normalize_levels`.
    """
    out: list[int] = []
    for v in values:
        amp = max(float(v), 1e-9) * max(gain, 1e-6)
        db = 20.0 * math.log10(amp)
        norm = (db - floor_db) / (0.0 - floor_db)
        norm = max(0.0, min(1.0, norm))
        out.append(int(round(norm * max_bar)))
    return out


# --- auto-gain (volume-independent) -----------------------------------------
# The display normalizes each band against a running REFERENCE of recent
# BROADBAND loudness ("how loud is the audio right now"), so bars fill the range
# based on CONTENT, not absolute level — lowering system volume does NOT shrink
# them. The reference is the MEAN of the bands (`band_mean`), NOT a high
# percentile of the SAME frame's bands: a percentile reference equals the loudest
# bands, and "at ref -> top" then drops the median-and-below bands to the floor
# (bars "fill then sink"). With a broadband reference and a CENTERED map (a band
# AT ref -> a healthy mid-high bar, with HEADROOM above for louder bands and RANGE
# below for quieter ones), typical music SPREADS across the display. The SILENCE
# GATE on input RMS — not the reference — is what stops noise being amplified.
#
# TUNING GUIDE (the agent can't hear; tune these on glass):
#   bars SINK / collapse over time -> ref tracking too high a level: keep ref = band_mean,
#                                     and ensure AUTOGAIN_RELEASE is fast enough to recover
#   bars too SHORT overall         -> lower AUTOGAIN_RANGE_DB, or raise AUTOGAIN_HEADROOM_DB (center up)
#   bars CLIP at the top (all max) -> raise AUTOGAIN_RANGE_DB, or lower AUTOGAIN_HEADROOM_DB (center down)
#   whole display FLASHES / pumps  -> lower AUTOGAIN_ATTACK, or raise the decay factor (UI Smoothing)
#   PUMP + ~1-2s DELAY (pop/fall)  -> NOT the DSP: parec is block-buffering; ensure
#                                     audioviz.PAREC_LATENCY_MS is set (--latency-msec). (v0.9.6)
#   volume STILL shrinks the bars  -> lower REF_FLOOR (must sit BELOW quiet-music band levels)
#   silence shows noise            -> raise SILENCE_FLOOR_RMS
SILENCE_FLOOR_RMS = 0.0015   # input RMS below this = silence -> bars fall to ~0 (the noise gate)
AUTOGAIN_ATTACK = 0.4        # reference RISE fraction/frame toward a louder level (smooth, not instant)
AUTOGAIN_RELEASE = 0.95      # reference release/frame when the signal drops (~0.5-1s recovery @ ~43fps)
AUTOGAIN_RANGE_DB = 24.0     # dB BELOW the reference mapped down to 0 (a band -RANGE_DB under ref = empty)
AUTOGAIN_HEADROOM_DB = 9.0   # dB ABOVE the reference that reaches MAX_BAR (a band AT ref -> ~RANGE/(RANGE+HEADROOM)*MAX)
AUTOGAIN_PERCENTILE = 85.0   # percentile_peak() default (kept for utility/tests; NOT the ref target)
REF_FLOOR = 1e-4             # tiny epsilon ONLY (never divide by ~0); MUST be below quiet-music levels


def signal_rms(samples) -> float:
    """RMS of a sample chunk (the silence-floor metric). numpy-friendly."""
    n = len(samples)
    if not n:
        return 0.0
    return float((sum(float(x) * float(x) for x in samples) / n) ** 0.5)


def band_mean(bands) -> float:
    """Broadband loudness = the (arithmetic) MEAN band magnitude — the auto-gain
    REFERENCE target. It represents "how loud overall right now", so absolute
    volume cancels while typical per-band content still fills the display. The
    mean (not RMS, which over-weights the loud bands, nor a high percentile, which
    tracks only the loudest) sits near the middle of the spectrum, so the centered
    normalization spreads bars ACROSS the display instead of collapsing them to
    the loudest few ("fill then sink")."""
    vals = [float(b) for b in bands]
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def percentile_peak(bands, pct: float = AUTOGAIN_PERCENTILE) -> float:
    """The ``pct``-th percentile of the band magnitudes (linear interpolation).

    A utility (kept + tested); NOT used as the auto-gain reference target — that
    is :func:`band_energy` (a broadband measure), so the display doesn't collapse
    to the loudest bands."""
    vals = sorted(float(b) for b in bands)
    if not vals:
        return 0.0
    k = (len(vals) - 1) * (max(0.0, min(100.0, pct)) / 100.0)
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return vals[int(lo)]
    return vals[int(lo)] + (vals[int(hi)] - vals[int(lo)]) * (k - lo)


def update_ref(ref, peak, attack: float = AUTOGAIN_ATTACK,
               release: float = AUTOGAIN_RELEASE, ref_floor: float = REF_FLOOR) -> float:
    """Envelope-follow the auto-gain reference toward ``peak``.

    Rising: ``ref += (peak - ref) * attack`` — a SMOOTH attack, so a single
    transient (a kick) can't instantly inflate the reference and crush every bar
    for that frame (the pump/flash). Falling: ``ref *= release`` — slow, so it
    adapts over ~1-2s. ``ref_floor`` is just a divide-by-zero epsilon. Pass
    ``peak=0`` on silence so it releases (never ratchets up on noise)."""
    ref = float(ref)
    peak = float(peak)
    if peak > ref:
        ref += (peak - ref) * max(0.0, min(1.0, attack))   # smooth attack, not an instant snap
    else:
        ref *= release
    return max(ref, ref_floor)


def normalize_levels(bands, ref, sensitivity: float = 1.0, max_bar: int = MAX_BAR,
                     range_db: float = AUTOGAIN_RANGE_DB,
                     headroom_db: float = AUTOGAIN_HEADROOM_DB) -> list[int]:
    """Map band magnitudes to bar heights CENTERED on ``ref`` (broadband loudness).

    ``db_rel = 20*log10(band/ref)`` is mapped over ``[-range_db, +headroom_db]`` →
    ``[0, max_bar]``. So a band AT the reference lands at a healthy mid-high bar
    (``range_db/(range_db+headroom_db) * max_bar``), louder bands have HEADROOM to
    reach the top, and quieter bands spread DOWN to 0 — typical music fills across
    the display instead of collapsing to the loudest few bands. ``sensitivity``
    (1.0 = neutral; >1 fuller, <1 dimmer) shifts every band up/down. Volume-
    independent because ``ref`` tracks the signal — absolute level cancels (so
    ``REF_FLOOR`` must be below quiet-music levels, else low volume pins it).
    """
    ref = max(float(ref), REF_FLOOR)
    s = max(float(sensitivity), 1e-6)
    span = max(1e-6, float(range_db) + float(headroom_db))
    out: list[int] = []
    for v in bands:
        norm = (float(v) / ref) * s
        db = 20.0 * math.log10(max(norm, 1e-9))
        level = (db + range_db) / span * max_bar
        out.append(int(round(max(0.0, min(float(max_bar), level)))))
    return out


def decay_levels(prev, new, factor: float = 0.85) -> list[float]:
    """Attack-fast / release-slow smoothing: ``out = max(new, prev*factor)``.

    Bars jump UP instantly to a new peak but fall only by ``factor`` per frame,
    so they don't twitch. ``factor`` ~0.85 by default (configurable).
    """
    factor = max(0.0, min(0.999, factor))
    return [max(float(n), float(p) * factor) for n, p in zip(new, _pad(prev, new))]


def _pad(prev, new):
    prev = list(prev)
    if len(prev) < len(new):
        prev += [0.0] * (len(new) - len(prev))
    return prev


# --- socket endpoints --------------------------------------------------------
class SpectrumReceiver:
    """Daemon side: bind a unix DGRAM socket and drain to the LATEST frame.

    Non-blocking; :meth:`drain` reads every queued datagram and returns the last
    decoded frame (or None if none arrived), so a backlog can never lag the
    display — only the freshest audio frame is ever shown.
    """

    def __init__(self, path: str | None = None) -> None:
        self.path = path or SOCKET_PATH
        self._sock: socket.socket | None = None

    def open(self) -> None:
        # Remove a stale socket file from a prior run, then bind fresh.
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        directory = os.path.dirname(self.path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        sock.setblocking(False)
        sock.bind(self.path)
        self._sock = sock

    def drain(self) -> list[int] | None:
        """Return the LATEST queued frame's heights, or None if nothing arrived."""
        if self._sock is None:
            return None
        latest: list[int] | None = None
        while True:
            try:
                data, _ = self._sock.recvfrom(_RECV_BUF)
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                break
            frame = decode_frame(data)
            if frame is not None:
                latest = frame
        return latest

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
            try:
                os.unlink(self.path)
            except OSError:
                pass


class SpectrumSender:
    """audioviz side: connectionless sender of bar-height frames to the daemon.

    Drops silently if the daemon isn't listening (not in spectrum mode / not
    running) — the audio process never blocks or crashes on a missing reader.
    """

    def __init__(self, path: str | None = None) -> None:
        self.path = path or SOCKET_PATH
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self._sock.setblocking(False)

    def send(self, heights) -> None:
        try:
            self._sock.sendto(encode_frame(heights), self.path)
        except OSError:
            pass  # no listener / buffer full — newest-wins, just drop it

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass
