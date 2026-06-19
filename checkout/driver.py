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
        """Send raw bytes; print hex in dry-run, else write to the port."""
        if self.dry_run:
            print("TX " + " ".join(f"{b:02X}" for b in data))
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

        Emits this exact sequence (no 0x1F clear, so no flash):

            0x10 0x00  <top: 20 ASCII bytes>
            0x10 0x14  <bottom: first 19 ASCII bytes>   # cells 0x14..0x26
            0x10 0x27  <bottom: 20th ASCII byte>         # the 40th cell
            0x10 0x00  # reposition to SUPPRESS the scroll the 40th write causes
            0x14       # hide cursor — MUST be last

        Why the bottom line is split 19+1: writing the last cell (0x27) auto-
        advances the cursor PAST the end, which scrolls the whole display up and
        loses the top line. Re-anchoring with a reposition (0x10 0x00) right
        after suppresses that scroll while preserving content. The top line does
        NOT need the split: its auto-advance lands on 0x14, which we immediately
        overwrite with a position command anyway.

        Built as one buffer + one serial write so there's no flicker and the
        cursor-hide is reliably the final byte.
        """
        top_b = _sanitize(_pad(top))      # exactly 20 bytes
        bottom_b = _sanitize(_pad(bottom))  # exactly 20 bytes

        buf = bytearray()
        buf += bytes([CMD_SET_CURSOR, POS_TOP])
        buf += top_b
        buf += bytes([CMD_SET_CURSOR, POS_BOTTOM])
        buf += bottom_b[:19]                       # cells 0x14..0x26
        buf += bytes([CMD_SET_CURSOR, POS_MAX])    # 0x27, the 40th cell
        buf += bottom_b[19:20]                     # the 20th char of the bottom
        buf += bytes([CMD_SET_CURSOR, POS_TOP])    # suppress the 40th-cell scroll
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
