"""EpsonDriver — the HP LD220-HP in its EPSON command mode (factory default).

Bench facts (self-test screen, 2026-09-28): USB 03f0:3524 (pl2303), 9600 8N1,
firmware 6.6, command mode EPSON. Byte source: the OEM "VFD LD220 User Manual
V2.3" §4.1.2, corrected on the bench. See docs/hardware.md.

User glyphs, as the bench unit actually behaves:
  * Each ``ESC &`` define REPLACES the whole user set, so all 9 glyphs are sent
    in ONE command over a contiguous code range: slot n lives at ``'0' + n``.
    ``define_character`` only stores a bitmap; ``glyphs_loaded`` sends the set.
  * ``ESC % 1`` / ``ESC % 0`` (user set on/off) applies to characters as they
    are WRITTEN, not to what is already on the glass. So every write switches
    the set on only around glyph cells and ends with it off: a real digit in
    text always prints as a digit.
Frames carry glyphs as the logical codes 0x15-0x1E (the IBM's real codes);
``_cells`` maps them to the '0'..'8' wire codes.
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
USER_SET_OFF = bytes([ESC, 0x25, 0x00])
CLEAR = bytes([0x0C])
SELF_TEST = bytes([US, 0x40])
INIT_SEQUENCE = INIT + OVERWRITE_MODE + CURSOR_HIDE + USER_SET_OFF

# Slot n is defined at, and displayed as, the code GLYPH_FIRST + n ('0'..'8').
GLYPH_FIRST = 0x30
GLYPH_LAST = GLYPH_FIRST + MAX_USER_GLYPHS - 1
_LOGICAL_TO_WIRE = {code: GLYPH_FIRST + i for i, code in enumerate(GLYPH_CODES)}
_REPLACEMENT = ord("?")

GLYPH_COLS = 5
_EMPTY_GLYPH = bytes(GLYPH_COLS)

_MERGE_GAP = 4  # a cursor move is 4 bytes here, not 2


def _cells(text: str) -> list[tuple[int, bool]]:
    """Text -> (wire code, is_glyph) per cell. Non-printables become '?'."""
    out = []
    for ch in text:
        o = ord(ch)
        if o in _LOGICAL_TO_WIRE:
            out.append((_LOGICAL_TO_WIRE[o], True))
        elif 0x20 <= o <= 0x7E:
            out.append((o, False))
        else:
            out.append((_REPLACEMENT, False))
    return out


def _encode(cells: list[tuple[int, bool]]) -> bytes:
    """Cells -> bytes, with the user set on only where a glyph needs it.

    The set stays on across letters and spaces (they are not redefined) and is
    switched off before a real '0'..'8' and at the end, so every write leaves it
    off.
    """
    buf = bytearray()
    on = False
    for code, glyph in cells:
        if glyph and not on:
            buf += USER_SET_ON
            on = True
        elif not glyph and on and GLYPH_FIRST <= code <= GLYPH_LAST:
            buf += USER_SET_OFF
            on = False
        buf.append(code)
    if on:
        buf += USER_SET_OFF
    return bytes(buf)


def _goto(pos: int) -> bytes:
    """US $ x y — 1-based column and row."""
    return bytes([US, 0x24, pos % COLS + 1, pos // COLS + 1])


def _columns(rows) -> bytes:
    """7 editor rows (low 5 bits = columns 1..5) -> 5 column bytes, bit 0 = top.

    Bench-confirmed 2026-09-28 (NOT the Epson DM-D convention of bit 7 = top).
    """
    return bytes(
        sum(((rows[r] >> c) & 1) << r for r in range(GLYPH_ROWS))
        for c in range(GLYPH_COLS)
    )


class EpsonDriver(SerialDriver):
    """HP LD220-HP, EPSON command mode. Same public surface as VFDDriver."""

    DISPLAY = "hp"
    LABEL = "HP LD220 2×20 VFD"

    def __init__(self, *args, **kwargs) -> None:
        # The driver's copy of the 9 bitmaps: glyphs_loaded() always re-sends all
        # of them, since one define replaces the whole set on the display.
        self._glyphs = [_EMPTY_GLYPH] * MAX_USER_GLYPHS
        super().__init__(*args, **kwargs)

    def initialize(self) -> None:
        """ESC @, overwrite mode, cursor off, user set off.

        ESC @ erases user glyphs; the daemon redefines them after any
        initialize (reconnect / reset / self-test invalidate its caches).
        """
        self._write(INIT_SEQUENCE)

    def glyphs_loaded(self) -> None:
        """Send all 9 stored glyphs in ONE define: ESC & 1 '0' '8' + 45 bytes."""
        self._write(bytes([ESC, 0x26, 0x01, GLYPH_FIRST, GLYPH_LAST]) + b"".join(self._glyphs))

    def _frame(self, top: str, bottom: str) -> bytes:
        return (_goto(0) + _encode(_cells(_pad(top)))
                + _goto(COLS) + _encode(_cells(_pad(bottom))))

    def clear(self) -> None:
        self._write(CLEAR)

    def reset(self) -> None:
        self.initialize()

    def write_at(self, pos: int, text: str) -> None:
        if not (0 <= pos <= POS_MAX):
            raise ValueError(f"position {pos} out of range 0..{POS_MAX}")
        self._write(_goto(pos) + _encode(_cells(text)))

    def show(self, top: str, bottom: str) -> None:
        self._write(self._frame(top, bottom))

    def show_changes(self, old: tuple[str, str], new: tuple[str, str]) -> None:
        """Rewrite only changed cells, as VFDDriver.show_changes (gap 4 here)."""
        before = _cells(_pad(old[0])) + _cells(_pad(old[1]))
        after = _cells(_pad(new[0])) + _cells(_pad(new[1]))
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
            buf += _goto(start) + _encode(after[start:end])
        full = self._frame(*new)
        self._write(full if len(buf) >= len(full) else bytes(buf))

    def show_bottom(self, bottom: str) -> None:
        self._write(_goto(COLS) + _encode(_cells(_pad(bottom))))

    def start_ticker(self, text: str) -> None:
        """No hardware ticker on the HP: show the first 20 chars on the top row."""
        self._write(_goto(0) + _encode(_cells(_pad(text))))

    def set_brightness(self, level) -> None:
        self._write(bytes([US, 0x58, normalize_brightness(level) + 1]))

    def set_vertical_scroll(self, enabled: bool) -> None:
        self._write(VERTICAL_SCROLL_MODE if enabled else OVERWRITE_MODE)

    def define_character(self, slot_index: int, rows) -> None:
        """Store glyph ``slot_index``; nothing is sent until glyphs_loaded()."""
        if not (0 <= slot_index < MAX_USER_GLYPHS):
            raise ValueError(f"glyph slot {slot_index} out of range 0..{MAX_USER_GLYPHS - 1}")
        rows = list(rows)
        if len(rows) != GLYPH_ROWS:
            raise ValueError(f"glyph needs exactly {GLYPH_ROWS} rows, got {len(rows)}")
        try:
            rows = [int(r) & GLYPH_PIXEL_MASK for r in rows]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"glyph rows must be ints: {exc}") from None
        self._glyphs[slot_index] = _columns(rows)

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
