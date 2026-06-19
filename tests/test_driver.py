"""Byte-sequence tests for VFDDriver, captured via --dry-run hex output."""

import pytest

from checkout import config
from checkout.driver import CMD_HIDE_CURSOR, VFDDriver


def capture_bytes(capsys) -> list[int]:
    """Flatten all 'TX ..' hex lines printed by the dry-run driver into ints."""
    out = capsys.readouterr().out
    data: list[int] = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("TX"):
            continue
        data.extend(int(tok, 16) for tok in line[2:].split())
    return data


@pytest.fixture
def driver():
    return VFDDriver(dry_run=True)


def test_show_visible_40th_cell_full_sequence(driver, capsys):
    # Left-justified so the 40th char is a VISIBLE glyph (uses the 0x27 path).
    driver.show("ABC", "Z" * 20)
    data = capture_bytes(capsys)

    # No leading clear.
    assert data[0] != 0x1F
    # 0x10 0x00 + 20-byte top
    assert data[0:2] == [0x10, 0x00]
    assert len(data[2:22]) == 20
    assert bytes(data[2:5]).decode() == "ABC"

    # 0x10 0x14 + first 19 bytes of bottom
    assert data[22:24] == [0x10, 0x14]
    assert data[24:43] == [ord("Z")] * 19

    # Visible 40th char: 0x10 0x27 <char> 0x10 0x00 (anchor), then 0x14 LAST.
    assert data[43:45] == [0x10, 0x27]
    assert data[45] == ord("Z")
    assert data[46:48] == [0x10, 0x00]
    assert data[48] == CMD_HIDE_CURSOR
    assert data[-1] == CMD_HIDE_CURSOR
    assert len(data) == 49


def test_show_space_40th_cell_skips_0x27(driver, capsys):
    # Centered clock-style content => the 40th char is a space.
    driver.show("date", "time")
    data = capture_bytes(capsys)

    # A space in the 40th cell would scroll, so 0x27 is NOT written at all.
    assert [0x10, 0x27] not in [data[i : i + 2] for i in range(len(data) - 1)]
    # Structure: 0x10 0x00 <20 top> 0x10 0x14 <19 bottom> 0x14, nothing more.
    assert data[0:2] == [0x10, 0x00]
    assert data[22:24] == [0x10, 0x14]
    assert data[-1] == CMD_HIDE_CURSOR
    assert len(data) == 2 + 20 + 2 + 19 + 1  # = 44


def test_show_never_emits_leading_clear(driver, capsys):
    for bottom in ("time", "Z" * 20):
        driver.show("top", bottom)
        data = capture_bytes(capsys)
        assert 0x1F not in data  # overwrite-in-place, never clear-then-write


def test_show_full_bottom_line_places_20th_char_at_0x27(driver, capsys):
    driver.show("T" * 20, "B" * 20)
    data = capture_bytes(capsys)
    # Locate the 0x10 0x27 marker; the next byte is the 20th bottom char.
    idx = next(
        i for i in range(len(data) - 1) if data[i] == 0x10 and data[i + 1] == 0x27
    )
    assert data[idx + 2] == ord("B")
    # The chunk written at 0x14 must be exactly 19 'B' bytes.
    start = next(
        i for i in range(len(data) - 1) if data[i] == 0x10 and data[i + 1] == 0x14
    )
    assert data[start + 2 : start + 21] == [ord("B")] * 19


def test_set_brightness_dim(driver, capsys):
    driver.set_brightness("dim")
    assert capture_bytes(capsys) == [0x04, 0x20]


def test_set_brightness_bright(driver, capsys):
    driver.set_brightness("bright")
    assert capture_bytes(capsys) == [0x04, 0xFF]


def test_set_brightness_invalid_raises(driver):
    with pytest.raises(ValueError):
        driver.set_brightness("medium")


def test_blank_ends_in_cursor_hide(driver, capsys):
    driver.blank()
    data = capture_bytes(capsys)
    assert data == [0x1F, 0x14]
    assert data[-1] == CMD_HIDE_CURSOR


class _FakeSerial:
    def __init__(self):
        self.buf = bytearray()

    def write(self, data):
        self.buf += data

    def close(self):
        pass


def test_debug_tx_logs_live_writes_and_still_writes_to_port(monkeypatch, capsys):
    """CHECKOUT_DEBUG_TX=1 hexdumps the real (non-dry-run) write path."""
    monkeypatch.setattr(config, "DEBUG_TX", True)
    # Build a live driver but inject a fake port instead of opening /dev/ttyUSB0.
    drv = VFDDriver.__new__(VFDDriver)
    drv.dry_run = False
    drv.port = "fake"
    drv.baud = 9600
    drv._serial = _FakeSerial()

    drv.show("AB", "CD")

    out = capsys.readouterr().out
    assert out.strip().startswith("TX ")  # hexdump emitted on the live path
    # The same bytes actually reached the port, ending in the cursor-hide.
    assert drv._serial.buf[-1] == CMD_HIDE_CURSOR
    assert drv._serial.buf[0:2] == bytes([0x10, 0x00])


def test_show_sanitizes_non_ascii(driver, capsys):
    driver.show("café", "x")
    data = capture_bytes(capsys)
    top = data[2:22]
    # 'é' is non-ASCII -> replaced with '?'
    assert bytes(top[:4]).decode() == "caf?"


def test_force_raw_mode_clears_opost_on_real_fd():
    """With a real fd, _force_raw_mode disables OPOST (and keeps CS8)."""
    import os
    import termios

    master, slave = os.openpty()
    try:
        # Turn OPOST ON first so we can observe the driver clearing it.
        attrs = termios.tcgetattr(slave)
        attrs[1] |= termios.OPOST
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        assert termios.tcgetattr(slave)[1] & termios.OPOST  # precondition

        drv = VFDDriver.__new__(VFDDriver)
        drv.dry_run = False
        drv.port = "pty"
        drv.baud = 9600

        class FakeSerial:
            def __init__(self, fd):
                self._fd = fd

            def fileno(self):
                return self._fd

        drv._serial = FakeSerial(slave)
        drv._force_raw_mode()

        after = termios.tcgetattr(slave)
        assert not (after[1] & termios.OPOST)  # output post-processing off
        assert after[2] & termios.CS8  # 8-bit chars preserved
    finally:
        os.close(master)
        os.close(slave)


def test_force_raw_mode_noop_in_dry_run():
    """Dry-run has no real fd; raw-mode setup must be a safe no-op."""
    drv = VFDDriver(dry_run=True)
    assert drv._serial is None
    drv._force_raw_mode()  # must not raise
