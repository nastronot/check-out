"""VFDDriver — the only component that emits raw bytes to the display.

Hardware is a salvaged IBM SurePOS 2x20 VFD on a WRITE-ONLY 9600 8N1 serial link.
Only the bench-confirmed command bytes below are ever sent; nothing else in the
app touches the port. See CLAUDE.md for the full hardware reference.
"""

from __future__ import annotations

from . import config

# --- Confirmed command bytes (single-byte control codes; NOT ESC/POS) --------
CMD_CLEAR = 0x1F          # clear whole display
CMD_SET_CURSOR = 0x10     # followed by ONE position byte
CMD_HIDE_CURSOR = 0x14    # hides the cursor; see "any write re-enables it" below

# Brightness is TWO discrete levels only (bench-confirmed). It is NOT a 0-255
# scale and NOT four levels — other level bytes are ignored by the display.
# Applies live (no redraw needed).
BRIGHTNESS = {"dim": b"\x04\x20", "bright": b"\x04\xff"}

# Display geometry / addressing (position = line*20 + col).
COLS = config.COLS
ROWS = config.ROWS
POS_TOP = 0x00            # top line starts here
POS_BOTTOM = 0x14         # bottom line starts here (20)
POS_MAX = ROWS * COLS - 1  # 0x27 — the 40th cell (bottom-right)

# Printable ASCII window. Anything outside is replaced so we never accidentally
# emit a control byte (e.g. a stray 0x1F would clear the display).
_PRINTABLE_MIN = 0x20
_PRINTABLE_MAX = 0x7E
_REPLACEMENT = "?"
_SPACE = 0x20  # a space in the 40th cell (0x27) doesn't anchor the cursor


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
        """Open the serial port (no-op in dry-run)."""
        if self.dry_run:
            return
        import serial  # imported lazily so dry-run needs no pyserial

        try:
            self._serial = serial.Serial(self.port, self.baud, timeout=0)
        except (serial.SerialException, OSError) as exc:
            raise VFDError(f"could not open {self.port}: {exc}") from exc
        # Re-assert raw mode on every open (a fresh open resets termios).
        self._force_raw_mode()

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
        """Clear the whole display (0x1F)."""
        self._write(bytes([CMD_CLEAR]))

    def write_at(self, pos: int, text: str) -> None:
        """Set the cursor to ``pos`` then write sanitized ASCII text.

        ``pos`` is a linear address 0x00–0x27 (line*20 + col).
        """
        if not (POS_TOP <= pos <= POS_MAX):
            raise ValueError(f"position {pos:#04x} out of range 0x00–{POS_MAX:#04x}")
        self._write(bytes([CMD_SET_CURSOR, pos]) + _sanitize(text))

    def _hide_cursor(self, buf: bytearray) -> None:
        """Append the cursor-hide byte (0x14) to ``buf``.

        CRITICAL: 0x14 hides the cursor, but ANY subsequent write RE-ENABLES it.
        There is no persistent "cursor off" and no separate "cursor on" byte.
        Therefore this MUST be the LAST byte of every frame update, after all
        positioning and text. Do not remove or reorder it.
        """
        buf.append(CMD_HIDE_CURSOR)

    def show(self, top: str, bottom: str) -> None:
        """Overwrite both lines in place as a single buffered write.

        NO leading 0x1F clear — a clear immediately before a full-frame write
        scrolls the display (bench-verified). Overwrite-in-place is correct;
        clear-then-write is not.

        Emits (for a VISIBLE 40th char):

            0x10 0x00  <top: 20 ASCII bytes>
            0x10 0x14  <bottom: first 19 ASCII bytes>   # cells 0x14..0x26
            0x10 0x27  <bottom: 20th ASCII byte>         # the 40th cell
            0x10 0x00  # reposition — anchors the cursor, suppresses the scroll
            0x14       # hide cursor — MUST be last

        The 40th cell (0x27) is special: writing it auto-advances the cursor PAST
        the end, which scrolls the whole display up. A reposition (0x10 0x00)
        immediately after re-anchors and suppresses that scroll — BUT only when a
        VISIBLE glyph was written; writing a SPACE (0x20) into 0x27 does NOT
        anchor the cursor, so the reposition fires too late and it still scrolls
        (bench-verified).

        Therefore the 40th cell is written conditionally:
          - 40th char visible  -> write it at 0x27, then reposition (0x10 0x00).
          - 40th char is space -> DON'T touch 0x27 at all. After the 19-char write
            the cursor sits at 0x27 without advancing past the end, so no scroll.

        DEFAULT/limitation: usable width is effectively 39 cells whenever the 40th
        char is a space — we never write a space to 0x27. Most content (the
        centered clock) has a space there anyway, so this is invisible in
        practice and guaranteed not to scroll. CAVEAT: if a prior frame wrote a
        visible glyph at 0x27 and the new frame's 40th char is a space, the old
        glyph is left in place (we can't blank it without writing a space, which
        scrolls). Acceptable for current content; revisit if a frame needs to
        toggle the 40th cell from glyph to blank.

        The top line never needs this treatment: its 20-char write auto-advances
        to 0x14, which we immediately overwrite with an explicit position command
        before the cursor can scroll.

        Built as one buffer + one serial write so there's no flicker and the
        cursor-hide is reliably the final byte.
        """
        top_b = _sanitize(_pad(top))      # exactly 20 bytes
        bottom_b = _sanitize(_pad(bottom))  # exactly 20 bytes
        cell40 = bottom_b[19]             # the 40th-cell byte (int)

        buf = bytearray()
        buf += bytes([CMD_SET_CURSOR, POS_TOP])
        buf += top_b
        buf += bytes([CMD_SET_CURSOR, POS_BOTTOM])
        buf += bottom_b[:19]                       # cells 0x14..0x26
        if cell40 != _SPACE:
            buf += bytes([CMD_SET_CURSOR, POS_MAX])  # 0x27, the 40th cell
            buf += bytes([cell40])                   # a VISIBLE glyph
            buf += bytes([CMD_SET_CURSOR, POS_TOP])  # anchor + suppress scroll
        # else: leave 0x27 untouched — a space there would scroll, not anchor.
        self._hide_cursor(buf)
        self._write(bytes(buf))

    def set_brightness(self, level: str) -> None:
        """Set display brightness to "dim" or "bright" (two discrete levels).

        Raises ValueError for any other value — there is no 0-255 API. Applies
        live and is independent of the cursor/scroll handling in show().
        """
        try:
            self._write(BRIGHTNESS[level])
        except KeyError:
            raise ValueError(
                f"brightness must be one of {sorted(BRIGHTNESS)}, got {level!r}"
            ) from None

    def blank(self) -> None:
        """Clear the display and leave it dark, with no cursor block remaining."""
        buf = bytearray([CMD_CLEAR])
        self._hide_cursor(buf)  # 0x14 last, so no cursor block on the dark screen
        self._write(bytes(buf))
