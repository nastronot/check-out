"""EpsonDriver — the HP LD220-HP in its EPSON command mode (factory default).

Bench facts (self-test screen, 2026-09-28): USB 03f0:3524 (pl2303), 9600 8N1,
firmware 6.6, command mode EPSON. Byte source: the OEM "VFD LD220 User Manual
V2.3" §4.1.2. See docs/hardware.md.

Frames carry user glyphs as the logical codes 0x15-0x1E (the IBM's real codes).
EPSON defines user glyphs AT printable codes, so each slot is parked on a
character check-out rarely shows; _sanitize maps logical -> parked codes, and
real occurrences of a parked character become a lookalike so they never draw a
glyph by accident.
"""

from __future__ import annotations

from .driver import (
    COLS,
    GLYPH_CODES,
    GLYPH_PIXEL_MASK,
    GLYPH_ROWS,
    MAX_USER_GLYPHS,
    POS_MAX,
    ROWS,
    SerialDriver,
    _pad,
    normalize_brightness,
)

ESC = 0x1B
US = 0x1F

INIT = bytes([ESC, 0x40])                 # ESC @ — also erases user glyphs
OVERWRITE_MODE = bytes([US, 0x01])
VERTICAL_SCROLL_MODE = bytes([US, 0x02])
CURSOR_HIDE = bytes([US, 0x43, 0x00])
USER_SET_ON = bytes([ESC, 0x25, 0x01])
CLEAR = bytes([0x0C])
SELF_TEST = bytes([US, 0x40])
INIT_SEQUENCE = INIT + OVERWRITE_MODE + CURSOR_HIDE + USER_SET_ON

# Slot 0..8 -> the printable code it is parked on.
PARKED_CODES = (0x60, 0x7B, 0x7C, 0x7D, 0x7E, 0x5E, 0x5C, 0x5B, 0x5D)
_LOGICAL_TO_WIRE = dict(zip(GLYPH_CODES, PARKED_CODES))
_LOOKALIKE = {
    0x60: "'", 0x7B: "(", 0x5B: "(", 0x7D: ")", 0x5D: ")",
    0x7C: "!", 0x7E: "-", 0x5E: " ", 0x5C: "/",
}
_REPLACEMENT = ord("?")

GLYPH_COLS = 5
GLYPH_WIDTH_BYTE = 0x05  # the "a" byte before each character's 5 column bytes

_MERGE_GAP = 4                        # a cursor move is 4 bytes here, not 2
_FULL_FRAME_BYTES = ROWS * (4 + COLS)  # 48


def _sanitize(text: str) -> bytes:
    out = bytearray()
    for ch in text:
        o = ord(ch)
        if o in _LOGICAL_TO_WIRE:
            out.append(_LOGICAL_TO_WIRE[o])
        elif o in _LOOKALIKE:
            out.append(ord(_LOOKALIKE[o]))
        elif 0x20 <= o <= 0x7E:
            out.append(o)
        else:
            out.append(_REPLACEMENT)
    return bytes(out)


def _goto(pos: int) -> bytes:
    """US $ x y — 1-based column and row."""
    return bytes([US, 0x24, pos % COLS + 1, pos // COLS + 1])


def _columns(rows) -> bytes:
    """7 editor rows (low 5 bits = columns 1..5) -> 5 column bytes, bit 7 = top.

    ASSUMED Epson convention — bench check 2 confirms or corrects it.
    """
    return bytes(
        sum(((rows[r] >> c) & 1) << (7 - r) for r in range(GLYPH_ROWS))
        for c in range(GLYPH_COLS)
    )


class EpsonDriver(SerialDriver):
    """HP LD220-HP, EPSON command mode. Same public surface as VFDDriver."""

    DISPLAY = "hp"
    LABEL = "HP LD220 2×20 VFD"

    def initialize(self) -> None:
        """ESC @, overwrite mode, cursor off, user glyph set on.

        ESC @ erases user glyphs; the daemon redefines them after any
        initialize (reconnect / reset / self-test invalidate its caches).
        """
        self._write(INIT_SEQUENCE)

    def glyphs_loaded(self) -> None:
        """After defining glyphs: switch the user set on. NOT initialize()."""
        self._write(USER_SET_ON)

    def clear(self) -> None:
        self._write(CLEAR)

    def reset(self) -> None:
        self.initialize()

    def write_at(self, pos: int, text: str) -> None:
        if not (0 <= pos <= POS_MAX):
            raise ValueError(f"position {pos} out of range 0..{POS_MAX}")
        self._write(_goto(pos) + _sanitize(text))

    def show(self, top: str, bottom: str) -> None:
        self._write(_goto(0) + _sanitize(_pad(top)) + _goto(COLS) + _sanitize(_pad(bottom)))

    def show_changes(self, old: tuple[str, str], new: tuple[str, str]) -> None:
        """Rewrite only changed cells, as VFDDriver.show_changes (gap 4 here)."""
        before = _sanitize(_pad(old[0])) + _sanitize(_pad(old[1]))
        after = _sanitize(_pad(new[0])) + _sanitize(_pad(new[1]))
        runs: list[list[int]] = []
        for pos in range(ROWS * COLS):
            if before[pos] == after[pos]:
                continue
            last = runs[-1] if runs else None
            if last and pos - last[1] <= _MERGE_GAP and pos // COLS == last[0] // COLS:
                last[1] = pos + 1
            else:
                runs.append([pos, pos + 1])
        if not runs:
            return
        buf = bytearray()
        for start, end in runs:
            buf += _goto(start) + after[start:end]
        if len(buf) >= _FULL_FRAME_BYTES:
            self.show(*new)
        else:
            self._write(bytes(buf))

    def show_bottom(self, bottom: str) -> None:
        self._write(_goto(COLS) + _sanitize(_pad(bottom)))

    def start_ticker(self, text: str) -> None:
        """No hardware ticker on the HP: show the first 20 chars on the top row."""
        self._write(_goto(0) + _sanitize(_pad(text)))

    def set_brightness(self, level) -> None:
        self._write(bytes([US, 0x58, normalize_brightness(level) + 1]))

    def set_vertical_scroll(self, enabled: bool) -> None:
        self._write(VERTICAL_SCROLL_MODE if enabled else OVERWRITE_MODE)

    def define_character(self, slot_index: int, rows) -> None:
        """ESC & 1 c c 05 p1..p5 — one glyph at its parked code."""
        if not (0 <= slot_index < MAX_USER_GLYPHS):
            raise ValueError(f"glyph slot {slot_index} out of range 0..{MAX_USER_GLYPHS - 1}")
        rows = list(rows)
        if len(rows) != GLYPH_ROWS:
            raise ValueError(f"glyph needs exactly {GLYPH_ROWS} rows, got {len(rows)}")
        try:
            rows = [int(r) & GLYPH_PIXEL_MASK for r in rows]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"glyph rows must be ints: {exc}") from None
        code = PARKED_CODES[slot_index]
        self._write(bytes([ESC, 0x26, 0x01, code, code, GLYPH_WIDTH_BYTE]) + _columns(rows))

    def select_code_page(self, page) -> None:
        """ESC t 0 only: the manual's other page numbers are unconfirmed."""
        if page not in ("default", 0):
            raise ValueError(f"the HP driver supports code page 0 only, got {page!r}")
        self._write(bytes([ESC, 0x74, 0x00]))

    def self_test(self) -> None:
        self._write(SELF_TEST)
        self.initialize()

    def blank(self) -> None:
        """FF clears the glass; glyph definitions survive (bench check 5)."""
        self._write(CLEAR)
