"""VFDDriver — the only component that emits raw bytes to the display.

Hardware is a salvaged IBM SurePOS 2x20 VFD (Futaba **M202MD10C** board) on a
WRITE-ONLY 9600 8N1 serial link. Only the documented command bytes below are
ever sent; nothing else in the app touches the port. See CLAUDE.md for the full
hardware reference.

The command table is the authoritative Futaba M202MD10C protocol, recovered from
the SNMetamorph ``FutabaVfdM202MD10C`` library source (our exact board) and
bench-confirmed on this unit. The earlier "39-cell / 0x27 phantom scroll / no
leading clear" findings were artifacts of a MISSING INITIALIZATION sequence (the
display was never put into extended mode, and vertical scroll was left on). With
the init sequence below all 40 cells are writable and addressing is the simple
linear ``col + row*20``.
"""

from __future__ import annotations

import re

from . import config

# --- Futaba M202MD10C protocol commands (authoritative, bench-confirmed) ------
# Named after the SNMetamorph FutabaVfdM202MD10C library's ProtocolCommands set.
EXTENDED_MODE = 0x00            # + 0x01 enable / 0x00 disable
SELECT_CODE_PAGE = 0x02         # + page byte (12 pages)        — wire later
DEFINE_CHARACTER = 0x03         # + index + 7 bytes + 0x00 (9 user glyphs) — later
DIMMING_MODE = 0x04            # + level byte (brightness)
PRINT_TICKER_TEXT = 0x05        # hardware ticker (top row); + text + 0x0D to start
TICKER_END = 0x0D               # terminates/starts the ticker buffer
TICKER_MAX = 45                 # hardware ticker buffer is 45 chars
BACKSPACE = 0x08
SELF_TEST = 0x0F
DISPLAY_POSITION = 0x10         # + position byte = col + row*20
DISABLE_VERTICAL_SCROLL = 0x11
ENABLE_VERTICAL_SCROLL = 0x12
CURSOR_ON = 0x13
CURSOR_OFF = 0x14
RESET = 0x1F

# Extended-mode sub-command bytes.
EXTENDED_ON = 0x01
EXTENDED_OFF = 0x00

# Mandatory init sequence (sent on every open/reconnect). Without the
# extended-mode enable (0x00 0x01) and scroll disable (0x11) the display scrolls
# when the 40th cell is written — that was the root cause of the old workarounds.
INIT_SEQUENCE = bytes([RESET, EXTENDED_MODE, EXTENDED_ON, DISABLE_VERTICAL_SCROLL])

# Brightness. FOUR distinct levels (bench-confirmed under extended mode), named
# after the SNMetamorph library's Dimming enum. The canonical state value is an
# index 0..3; the wire byte is 0x04 + the level byte below.
#   0 Minimum     0x20
#   1 Medium      0x40
#   2 AboveMedium 0x60
#   3 Maximum     0xFF
BRIGHTNESS_LEVELS = {0: 0x20, 1: 0x40, 2: 0x60, 3: 0xFF}
MAX_BRIGHTNESS = 3

# Legacy two-level strings (pre-v0.6.2) map onto the four-level index.
_LEGACY_BRIGHTNESS = {"dim": 0, "bright": 3}


def normalize_brightness(value) -> int:
    """Coerce a brightness value to a canonical index 0..3.

    Accepts the new int form (0..3), the legacy "dim"/"bright" strings, and
    numeric strings ("2"). Out-of-range / unrecognized values raise ValueError.
    """
    if isinstance(value, bool):  # bool is an int subclass — reject it explicitly
        raise ValueError(f"invalid brightness {value!r}")
    if isinstance(value, str):
        key = value.strip().lower()
        if key in _LEGACY_BRIGHTNESS:
            return _LEGACY_BRIGHTNESS[key]
        if key.lstrip("-").isdigit():
            value = int(key)
        else:
            raise ValueError(f"invalid brightness {value!r}")
    if isinstance(value, int) and 0 <= value <= MAX_BRIGHTNESS:
        return value
    raise ValueError(f"brightness must be an int 0..{MAX_BRIGHTNESS}, got {value!r}")

# User-defined characters (bench-confirmed). 9 glyph slots live at NON-CONTIGUOUS
# character codes (0x1B is skipped). slot index 0..8 -> the code byte, used BOTH
# to define the glyph (0x03 <code> ...) and to display it (write the code byte).
GLYPH_CODES = (0x15, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x1C, 0x1D, 0x1E)
MAX_USER_GLYPHS = len(GLYPH_CODES)  # 9
GLYPH_ROWS = 7
# Bitmap encoding (bench-confirmed): 7 row bytes, top row first. The display
# reads the 5 columns from bits 3-7 of each byte:
#   column 1 (leftmost)  = bit 3 (0x08) ... column 5 (rightmost) = bit 7 (0x80).
# The PUBLIC api takes editor-natural rows where the LOW 5 bits = columns 1..5
# (bit0=col1 ... bit4=col5); each row is translated to the wire byte by <<3.
#   hw_byte = (row & 0x1F) << 3   (e.g. 0x1F -> 0xF8, 0x01 -> 0x08, 0x10 -> 0x80)
GLYPH_PIXEL_MASK = 0x1F
GLYPH_COL_SHIFT = 3

# Code pages (SelectCodePage 0x02 + page byte). 12 pages total (0..11); names
# from the SNMetamorph library. select_code_page() accepts a name below or a raw
# int 0..11. Pages 6..11 exist per the library but are not yet identified on our
# unit, so only the confirmed names are mapped here.
CODE_PAGES = {
    "default": 0,
    "japanese": 1,   # CP897
    "cp850": 2,      # Western Europe (Fr/De/Es/Pt)
    "cp852": 3,      # Central Europe (Latin-2)
    "cp855": 4,      # Cyrillic
    "cp857": 5,      # Turkish
}
NUM_CODE_PAGES = 12

# Display geometry / addressing (position = col + row*20, row 0 = top).
COLS = config.COLS
ROWS = config.ROWS
POS_TOP = 0x00            # top line starts here
POS_BOTTOM = 0x14         # bottom line starts here (20)
POS_MAX = ROWS * COLS - 1  # 0x27 — the 40th cell (now fully writable)

# Printable ASCII window. Anything outside is replaced so we never accidentally
# emit a control byte (e.g. a stray 0x1F would reset the display). The user-glyph
# codes (0x15-0x1E) sit below this window but are legitimate display characters,
# so they are allowed through explicitly.
_PRINTABLE_MIN = 0x20
_PRINTABLE_MAX = 0x7E
_REPLACEMENT = "?"
_GLYPH_CODE_SET = frozenset(GLYPH_CODES)

# {g0}..{g8} placeholders in message text -> the glyph code char for that slot.
_GLYPH_PLACEHOLDER_RE = re.compile(r"\{g([0-8])\}")


class VFDError(Exception):
    """Raised on a serial write failure (e.g. USB adapter unplugged).

    The daemon catches this to drive its reconnect/backoff loop.
    """


def glyph_code(slot_index: int) -> int:
    """Return the character-code byte that displays user glyph ``slot_index`` (0..8).

    The codes are non-contiguous (0x1B is skipped), so this is the canonical map
    from slot to wire byte — use it both to define and to display a glyph.
    """
    if not (0 <= slot_index < MAX_USER_GLYPHS):
        raise ValueError(
            f"glyph slot {slot_index} out of range 0..{MAX_USER_GLYPHS - 1}"
        )
    return GLYPH_CODES[slot_index]


def apply_glyph_placeholders(text: str) -> str:
    """Replace ``{g0}``..``{g8}`` in ``text`` with the glyph code char for each slot.

    Lets users mix custom glyphs into a message; the substituted char survives
    :func:`_sanitize` (glyph codes are allow-listed) and renders the user glyph.
    """
    return _GLYPH_PLACEHOLDER_RE.sub(
        lambda m: chr(GLYPH_CODES[int(m.group(1))]), text
    )


def _sanitize(text: str) -> bytes:
    """Map a string to safe display bytes.

    Printable ASCII and the user-glyph codes pass through; anything else becomes
    ``?`` so the byte stream can never contain a control code the display would
    interpret.
    """
    out = bytearray()
    for ch in text:
        o = ord(ch)
        if _PRINTABLE_MIN <= o <= _PRINTABLE_MAX or o in _GLYPH_CODE_SET:
            out.append(o)
        else:
            out.append(ord(_REPLACEMENT))
    return bytes(out)


def _pad(text: str) -> str:
    """Pad/truncate to exactly COLS chars (driver-side safety net)."""
    return text[:COLS].ljust(COLS)


class VFDDriver:
    """Owns the serial port and all outgoing command bytes.

    Use as a context manager so the port is always closed::

        with VFDDriver() as vfd:
            vfd.show("hello", "world")

    ``dry_run=True`` prints the outgoing byte stream as hex instead of opening
    the port, so the logic is exercisable on any machine with no display.
    """

    def __init__(
        self,
        port: str | None = None,
        baud: int | None = None,
        dry_run: bool = False,
    ) -> None:
        self.port = port if port is not None else config.PORT
        self.baud = baud if baud is not None else config.BAUD
        self.dry_run = dry_run
        self._serial = None
        if not dry_run:
            self.open()

    # --- lifecycle -----------------------------------------------------------
    def open(self) -> None:
        """Open the serial port and initialize the display (no-op in dry-run)."""
        if self.dry_run:
            return
        import serial  # imported lazily so dry-run needs no pyserial

        try:
            self._serial = serial.Serial(self.port, self.baud, timeout=0)
        except (serial.SerialException, OSError) as exc:
            raise VFDError(f"could not open {self.port}: {exc}") from exc
        # Re-assert raw mode on every open (a fresh open resets termios).
        self._force_raw_mode()
        # Put the display into the known-good state (extended mode, no scroll).
        self.initialize()

    def initialize(self) -> None:
        """Send the mandatory init sequence: reset, extended-mode on, scroll off.

        Bytes: ``0x1F 0x00 0x01 0x11``. This MUST run on every open/reconnect —
        without extended mode + scroll-disable the display scrolls when the
        bottom-right cell is written. One buffered write.
        """
        self._write(INIT_SEQUENCE)

    def _force_raw_mode(self) -> None:
        """Disable the tty line discipline's OUTPUT post-processing.

        WHY: without this the kernel "cooks" outgoing bytes (OPOST/ONLCR maps
        NL->CR-NL, etc.) on the way to the display, injecting bytes that
        advance the cursor and scroll the VFD. Our byte sequence is correct;
        the kernel was mangling it. Clearing OPOST (full raw mode) makes pyserial
        send exactly the bytes we write. Baud (ispeed/ospeed) is left untouched,
        so 9600 8N1 survives.
        """
        if self._serial is None:
            return
        import termios

        try:
            fd = self._serial.fileno()
            attrs = termios.tcgetattr(fd)
            # indices: [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]
            attrs[0] &= ~(
                termios.IGNBRK | termios.BRKINT | termios.PARMRK | termios.ISTRIP
                | termios.INLCR | termios.IGNCR | termios.ICRNL | termios.IXON
            )
            attrs[1] &= ~termios.OPOST  # <-- critical: no output post-processing
            attrs[2] |= termios.CS8
            attrs[3] &= ~(
                termios.ECHO | termios.ECHONL | termios.ICANON
                | termios.ISIG | termios.IEXTEN
            )
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
        except (termios.error, OSError, AttributeError) as exc:
            raise VFDError(f"could not set raw mode on {self.port}: {exc}") from exc

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None

    def __enter__(self) -> "VFDDriver":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # --- low-level write -----------------------------------------------------
    def _write(self, data: bytes) -> None:
        """Send raw bytes as a single write.

        Logs the outgoing bytes as hex when in dry-run, or when
        ``CHECKOUT_DEBUG_TX=1`` on a live run (so the real on-the-wire stream can
        be checked against the known-good frame). ``flush=True`` so the hexdump
        is captured even when stdout is piped to a file.
        """
        if self.dry_run or config.DEBUG_TX:
            print("TX " + " ".join(f"{b:02X}" for b in data), flush=True)
        if self.dry_run:
            return
        if self._serial is None:
            raise VFDError("serial port is not open")
        import serial

        try:
            self._serial.write(data)
        except (serial.SerialException, OSError) as exc:
            raise VFDError(f"write to {self.port} failed: {exc}") from exc

    # --- public command surface ----------------------------------------------
    def clear(self) -> None:
        """Emit a bare reset (0x1F) with no re-init — raw primitive.

        NOTE: a bare reset also drops extended mode and re-enables scroll. Use
        :meth:`blank` for a safe dark screen, :meth:`reset` for a reset that
        restores the initialized state, or call :meth:`initialize` after.
        """
        self._write(bytes([RESET]))

    def reset(self) -> None:
        """Hard-reset the display and restore the initialized state.

        A bare reset (0x1F) drops extended mode and re-enables vertical scroll,
        so we immediately re-run the init sequence. Net effect: the display is
        reset and ready for show() (extended mode on, scroll off). The init
        sequence already begins with 0x1F, so this is exactly that sequence.
        """
        self.initialize()

    def write_at(self, pos: int, text: str) -> None:
        """Set the cursor to ``pos`` then write sanitized ASCII text.

        ``pos`` is a linear address 0x00–0x27 (col + row*20).
        """
        if not (POS_TOP <= pos <= POS_MAX):
            raise ValueError(f"position {pos:#04x} out of range 0x00–{POS_MAX:#04x}")
        self._write(bytes([DISPLAY_POSITION, pos]) + _sanitize(text))

    def show(self, top: str, bottom: str) -> None:
        """Overwrite both lines in place as a single buffered write.

        With the display correctly initialized (extended mode + scroll off) all
        40 cells are writable and the sequence is simply::

            0x10 0x00  <top: 20 ASCII bytes>     # cells 0x00..0x13
            0x10 0x14  <bottom: 20 ASCII bytes>   # cells 0x14..0x27
            0x14       # cursor off — MUST be the final byte

        Both lines are a full 20 chars. There is NO leading clear, NO 0x27
        special-casing, and NO anchor/reposition trick — those were workarounds
        for the missing init sequence and are gone.

        ``0x14`` (cursor off) must be LAST: any write after it re-enables the
        cursor block. Built as one buffer + one serial write so there is no
        flicker and the cursor-hide is reliably the final byte.
        """
        top_b = _sanitize(_pad(top))         # exactly 20 bytes
        bottom_b = _sanitize(_pad(bottom))   # exactly 20 bytes

        buf = bytearray()
        buf += bytes([DISPLAY_POSITION, POS_TOP])
        buf += top_b
        buf += bytes([DISPLAY_POSITION, POS_BOTTOM])
        buf += bottom_b
        buf.append(CURSOR_OFF)  # MUST be last — any later write re-shows cursor
        self._write(bytes(buf))

    def show_bottom(self, bottom: str) -> None:
        """Update ONLY the bottom row, leaving the top untouched.

        Emits ``0x10 0x14 <20 ASCII bytes> 0x14``. Bench-confirmed that writing
        the bottom row does NOT disturb a running hardware ticker on the top row,
        so this is how marquee mode refreshes its clock/static bottom line without
        re-kicking the ticker.
        """
        bottom_b = _sanitize(_pad(bottom))   # exactly 20 bytes
        buf = bytes([DISPLAY_POSITION, POS_BOTTOM]) + bottom_b + bytes([CURSOR_OFF])
        self._write(buf)

    def start_ticker(self, text: str) -> None:
        """Start the autonomous HARDWARE ticker on the TOP row (0x05 ... 0x0D).

        Emits ``0x05 <text, truncated to 45 chars> 0x0D``. The display then
        scrolls that text on the top row by itself at its FIXED medium speed —
        there is no hardware speed control (bench-confirmed; the SNMetamorph
        library's ticker API takes no speed arg). The caller must have the
        display initialized first (extended mode); re-init + re-start after any
        reset/self-test/reconnect.
        """
        payload = _sanitize(text)[:TICKER_MAX]
        self._write(bytes([PRINT_TICKER_TEXT]) + payload + bytes([TICKER_END]))

    def set_brightness(self, level) -> None:
        """Set display brightness to one of FOUR levels.

        ``level`` is the canonical index 0..3 (Minimum/Medium/AboveMedium/Maximum)
        or a legacy "dim"/"bright" string; it is normalized first. Emits
        ``0x04 <level byte>``. Raises ValueError on an out-of-range value. Applies
        live (no redraw needed) and is independent of show().
        """
        index = normalize_brightness(level)
        self._write(bytes([DIMMING_MODE, BRIGHTNESS_LEVELS[index]]))

    def set_vertical_scroll(self, enabled: bool) -> None:
        """Enable (0x12) or disable (0x11) hardware vertical scroll.

        Normal frames run with scroll DISABLED (set by initialize()). Enabling
        it makes writing past the last cell scroll the display up — useful later
        for ticker/marquee effects.
        """
        self._write(
            bytes([ENABLE_VERTICAL_SCROLL if enabled else DISABLE_VERTICAL_SCROLL])
        )

    def define_character(self, slot_index: int, rows) -> None:
        """Define user glyph ``slot_index`` (0..8) from 7 rows (DefineCharacter).

        Emits ``0x03 <code> <7 translated row bytes> 0x00`` where ``code`` is
        ``GLYPH_CODES[slot_index]`` (the non-contiguous slot byte).

        ``rows`` is the glyph as 7 ints, top row first, in the editor-natural
        convention: the LOW 5 bits are columns 1..5 (bit0=col1 ... bit4=col5).
        The display reads columns from bits 3-7, so each row is translated to the
        wire byte by ``(row & 0x1F) << 3`` (e.g. 0x1F -> 0xF8, full row).

        The caller should re-run initialize() afterward — defining a character
        may reset the display's extended-mode/scroll state.
        """
        if not (0 <= slot_index < MAX_USER_GLYPHS):
            raise ValueError(
                f"glyph slot {slot_index} out of range 0..{MAX_USER_GLYPHS - 1}"
            )
        rows = list(rows)
        if len(rows) != GLYPH_ROWS:
            raise ValueError(f"glyph needs exactly {GLYPH_ROWS} rows, got {len(rows)}")
        try:
            wire = bytes(
                ((int(r) & GLYPH_PIXEL_MASK) << GLYPH_COL_SHIFT) for r in rows
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(f"glyph rows must be ints: {exc}") from None
        code = GLYPH_CODES[slot_index]
        self._write(bytes([DEFINE_CHARACTER, code]) + wire + bytes([0x00]))

    def select_code_page(self, page) -> None:
        """Select a character code page — ``0x02 <page>``.

        ``page`` may be a name from :data:`CODE_PAGES` (e.g. ``"cp850"``) or a raw
        int 0..11.
        """
        if isinstance(page, str):
            try:
                page = CODE_PAGES[page.lower()]
            except KeyError:
                raise ValueError(
                    f"unknown code page {page!r}; known names: {sorted(CODE_PAGES)}"
                ) from None
        if not (0 <= page < NUM_CODE_PAGES):
            raise ValueError(f"code page {page} out of range 0..{NUM_CODE_PAGES - 1}")
        self._write(bytes([SELECT_CODE_PAGE, page]))

    def self_test(self) -> None:
        """Trigger the display's built-in self-test (0x0F), then re-initialize.

        The self-test leaves the display in an unknown state (extended mode /
        scroll may be reset), so the init sequence is re-run afterward to restore
        the known-good state before the next show().
        """
        self._write(bytes([SELF_TEST]))
        self.initialize()

    def blank(self) -> None:
        """Clear the display to a dark screen, left in the known-good state.

        Emits the full init sequence (reset + extended mode + scroll off) so the
        display is never left in scroll mode after a blank, then cursor-off
        (0x14) LAST so no cursor block lingers on the dark screen. The next
        show() therefore holds a full 40-char frame without re-initializing.
        """
        buf = bytearray(INIT_SEQUENCE)
        buf.append(CURSOR_OFF)  # last, so the dark screen has no cursor block
        self._write(bytes(buf))
