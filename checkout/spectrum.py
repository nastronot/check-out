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

# --- stereo layouts (v1.2.0) -------------------------------------------------
# Three layouts share the spectrum mode, picked by state ``spectrum_layout``:
#   full     — 20 bands, double-height, both rows = ONE mono spectrum (original).
#   stereo_v — top row = LEFT, bottom = RIGHT; each a 19-band spectrum ONE cell
#              tall (7 row-levels). Cell 0 of each row is an inverted L/R label.
#   stereo_h — top = LEFT, bottom = RIGHT; cell 0 = label, cells 1..19 = a single
#              horizontal LEVEL meter per channel at FINE resolution: 19 cells x 5
#              dot-columns = 95 horizontal steps (level 0..95).
# The Bars/Line STYLE applies across all layouts. Columns (the 5-per-cell h-res)
# apply only to stereo_h; stereo_v is inherently 7 vertical row-levels per cell.
LAYOUTS = ("full", "stereo_v", "stereo_h")
LAYOUT_FULL = 0          # frame tag: 20 heights 0..MAX_BAR (mono, double-height)
LAYOUT_STEREO_V = 1      # frame tag: 19 left + 19 right heights 0..7
LAYOUT_STEREO_H = 2      # frame tag: 2 levels (left, right), each 0..95
_LAYOUT_TAG = {"full": LAYOUT_FULL, "stereo_v": LAYOUT_STEREO_V, "stereo_h": LAYOUT_STEREO_H}
_TAG_LAYOUT = {tag: name for name, tag in _LAYOUT_TAG.items()}

STEREO_BANDS = 19                # data cells per channel row (cell 0 is the label)
STEREO_V_MAX = LEVELS_PER_CELL   # 7 — a stereo_v cell is one character tall
STEREO_H_CELL_COLS = 5           # 5 dot-columns per character cell
STEREO_H_MAX = STEREO_BANDS * STEREO_H_CELL_COLS  # 95 — the fine horizontal range

# --- socket / message protocol ----------------------------------------------
# Every frame is TAGGED: byte 0 = the layout tag, then a payload whose shape
# depends on the tag (full -> 20 bytes; stereo_v -> 19+19; stereo_h -> 2). Tiny +
# self-describing, so a single datagram is one whole frame and "newest wins" is
# natural (the daemon drains to the last datagram per loop). decode_frame returns
# a dict {"layout", ...channel data}; a wrong-length payload returns None (the
# daemon ignores it — never crashes on a malformed / mid-switch frame).
SOCKET_PATH = config.SPECTRUM_SOCKET
_RECV_BUF = 256


def _clampi(v, hi: int, lo: int = 0) -> int:
    return max(lo, min(hi, int(v)))


def encode_full(heights) -> bytes:
    """Tag 0: 20 heights (0..MAX_BAR) — the mono double-height frame."""
    vals = [_clampi(h, MAX_BAR) for h in list(heights)[:NUM_BARS]]
    vals += [0] * (NUM_BARS - len(vals))
    return bytes([LAYOUT_FULL, *vals])


def encode_stereo_v(left, right) -> bytes:
    """Tag 1: 19 LEFT + 19 RIGHT heights (0..STEREO_V_MAX)."""
    def chan(xs):
        vals = [_clampi(h, STEREO_V_MAX) for h in list(xs)[:STEREO_BANDS]]
        return vals + [0] * (STEREO_BANDS - len(vals))
    return bytes([LAYOUT_STEREO_V, *chan(left), *chan(right)])


def encode_stereo_h(level_l, level_r) -> bytes:
    """Tag 2: two overall levels (0..STEREO_H_MAX), left then right."""
    return bytes([LAYOUT_STEREO_H, _clampi(level_l, STEREO_H_MAX),
                  _clampi(level_r, STEREO_H_MAX)])


def encode_frame(layout="full", **data) -> bytes:
    """Encode the frame for ``layout`` (dispatches to the encode_* above)."""
    if layout == "stereo_v":
        return encode_stereo_v(data.get("left", []), data.get("right", []))
    if layout == "stereo_h":
        return encode_stereo_h(data.get("level_l", 0), data.get("level_r", 0))
    return encode_full(data.get("heights", []))


def decode_frame(data) -> dict | None:
    """Decode a tagged frame to ``{"layout", ...}``, or None if malformed.

    Returns None on an empty buffer, an unknown tag, or a payload shorter than
    the tag requires — so the daemon safely ignores a torn / mid-layout-switch
    datagram instead of crashing or rendering garbage.
    """
    if not data:
        return None
    tag, body = data[0], data[1:]
    if tag == LAYOUT_FULL:
        if len(body) < NUM_BARS:
            return None
        return {"layout": "full",
                "heights": [_clampi(b, MAX_BAR) for b in body[:NUM_BARS]]}
    if tag == LAYOUT_STEREO_V:
        if len(body) < 2 * STEREO_BANDS:
            return None
        left = [_clampi(b, STEREO_V_MAX) for b in body[:STEREO_BANDS]]
        right = [_clampi(b, STEREO_V_MAX) for b in body[STEREO_BANDS:2 * STEREO_BANDS]]
        return {"layout": "stereo_v", "left": left, "right": right}
    if tag == LAYOUT_STEREO_H:
        if len(body) < 2:
            return None
        return {"layout": "stereo_h",
                "level_l": _clampi(body[0], STEREO_H_MAX),
                "level_r": _clampi(body[1], STEREO_H_MAX)}
    return None


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


def line_glyph(height: int) -> list[int]:
    """Editor-natural rows for a single-row LINE at ``height`` (the peak only).

    Unlike :func:`bar_glyph` (which fills the bottom ``height`` rows), this lights
    EXACTLY one row — the peak row at that height — full width (``0x1F``), every
    other row dark. The lit row mirrors bar_glyph's anchoring: row ``r`` is lit
    iff ``r == GLYPH_ROWS - height`` (so height 1 lights only the bottom row,
    height 7 only the top row). Heights therefore line up between the two styles.
    """
    h = max(0, min(GLYPH_ROWS, int(height)))
    if h == 0:
        return [0x00] * GLYPH_ROWS
    lit = GLYPH_ROWS - h
    return [0x1F if r == lit else 0x00 for r in range(GLYPH_ROWS)]


def line_glyphs() -> dict[int, list[int]]:
    """The 7 LINE glyphs keyed by slot (slot i -> a single line at height i+1)."""
    return {slot: line_glyph(slot + 1) for slot in BAR_GLYPH_SLOTS}


# The two swappable spectrum glyph sets (both occupy slots 0..6). The style
# toggle (state ``spectrum_style``) picks one; the daemon redefines the slots
# when it changes. This style/glyph-swap seam is what the stereo modes reuse.
SPECTRUM_STYLES = ("bars", "line")
_DEFAULT_STYLE = "bars"


def style_glyphs(style: str) -> dict[int, list[int]]:
    """The 7 height glyphs for ``style`` ("bars" filled / "line" single-row)."""
    return line_glyphs() if style == "line" else bar_glyphs()


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


def line_to_cells(height: int) -> tuple[str, str]:
    """Map a height 0..14 to ``(top_char, bottom_char)`` for the LINE style.

    Only the single PEAK row is lit (the slot holds a ``line_glyph``), and NOTHING
    below it — so unlike :func:`bar_to_cells`, once the peak moves up into the top
    cell the BOTTOM cell goes EMPTY:

    - height 1..7  → bottom cell = line glyph for that height, top empty.
    - height 8..14 → top cell = line glyph for ``height-7``, bottom EMPTY.
    - height 0     → both empty.

    The chars are the same glyph CODE bytes (slots 0..6) — but in LINE style those
    slots are defined as single-row line glyphs, so the same code renders a line.
    """
    h = max(0, min(MAX_BAR, int(height)))
    if h == 0:
        return (_SPACE, _SPACE)
    if h <= LEVELS_PER_CELL:                       # 1..7: line in bottom cell
        return (_SPACE, chr(GLYPH_CODES[h - 1]))
    # 8..14: the line is now in the TOP cell, bottom empties (nothing lit below).
    top_code = GLYPH_CODES[h - 1 - LEVELS_PER_CELL]
    return (chr(top_code), _SPACE)


def render_spectrum(heights, style: str = "bars") -> tuple[str, str]:
    """Render 20 bar heights to the (top, bottom) 20-char display line pair.

    ``style`` selects the cell mapping: ``"bars"`` (filled, bottom-anchored) or
    ``"line"`` (a single lit row per band). Both assume the matching glyph set is
    defined in slots 0..6 (the daemon swaps them when the style changes).
    """
    to_cells = line_to_cells if style == "line" else bar_to_cells
    cells = [to_cells(h) for h in list(heights)[:NUM_BARS]]
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

    def send(self, frame: bytes) -> None:
        """Send a pre-encoded tagged frame (bytes). The caller builds it with the
        ``encode_*`` helpers for the active layout; we just push the datagram."""
        try:
            self._sock.sendto(frame, self.path)
        except OSError:
            pass  # no listener / buffer full — newest-wins, just drop it

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass
