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

from . import config

# --- Futaba M202MD10C protocol commands (authoritative, bench-confirmed) ------
# Named after the SNMetamorph FutabaVfdM202MD10C library's ProtocolCommands set.
EXTENDED_MODE = 0x00            # + 0x01 enable / 0x00 disable
SELECT_CODE_PAGE = 0x02         # + page byte (12 pages)        — wire later
DEFINE_CHARACTER = 0x03         # + index + 7 bytes + 0x00 (9 user glyphs) — later
DIMMING_MODE = 0x04            # + level byte (brightness)
PRINT_TICKER_TEXT = 0x05        # hardware ticker, 45-char buffer — wire later
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

# Brightness. Two confirmed discrete levels (dim/bright). The library claims 4
# levels and extended mode may expose more; left at the two confirmed values for
# now. TODO: retest the intermediate level bytes under extended mode.
BRIGHTNESS = {"dim": b"\x04\x20", "bright": b"\x04\xff"}

# Display geometry / addressing (position = col + row*20, row 0 = top).
COLS = config.COLS
ROWS = config.ROWS
POS_TOP = 0x00            # top line starts here
POS_BOTTOM = 0x14         # bottom line starts here (20)
POS_MAX = ROWS * COLS - 1  # 0x27 — the 40th cell (now fully writable)

# Printable ASCII window. Anything outside is replaced so we never accidentally
# emit a control byte (e.g. a stray 0x1F would reset the display).
_PRINTABLE_MIN = 0x20
_PRINTABLE_MAX = 0x7E
_REPLACEMENT = "?"


class VFDError(Exception):
    """Raised on a serial write failure (e.g. USB adapter unplugged).

    The daemon catches this to drive its reconnect/backoff loop.
    """


def _sanitize(text: str) -> bytes:
    """Map a string to safe printable-ASCII bytes.

    Non-encodable or non-printable characters become ``?`` so the byte stream
    can never contain a control code that the display would interpret.
    """
    out = bytearray()
    for ch in text:
        o = ord(ch)
        if _PRINTABLE_MIN <= o <= _PRINTABLE_MAX:
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
        """Reset the whole display (0x1F).

        NOTE: a bare reset also drops extended mode and re-enables scroll. Use
        :meth:`blank` for a safe dark screen, or call :meth:`initialize` after.
        """
        self._write(bytes([RESET]))

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

    def set_brightness(self, level: str) -> None:
        """Set display brightness to "dim" or "bright" (two confirmed levels).

        Raises ValueError for any other value. Applies live (no redraw needed)
        and is independent of show().
        """
        try:
            self._write(BRIGHTNESS[level])
        except KeyError:
            raise ValueError(
                f"brightness must be one of {sorted(BRIGHTNESS)}, got {level!r}"
            ) from None

    def set_vertical_scroll(self, enabled: bool) -> None:
        """Enable (0x12) or disable (0x11) hardware vertical scroll.

        Normal frames run with scroll DISABLED (set by initialize()). Enabling
        it makes writing past the last cell scroll the display up — useful later
        for ticker/marquee effects.
        """
        self._write(
            bytes([ENABLE_VERTICAL_SCROLL if enabled else DISABLE_VERTICAL_SCROLL])
        )

    def self_test(self) -> None:
        """Trigger the display's built-in self-test (0x0F)."""
        self._write(bytes([SELF_TEST]))

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
