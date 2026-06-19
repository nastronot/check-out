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


def test_show_full_byte_sequence(driver, capsys):
    driver.show("ABC", "XYZ")
    data = capture_bytes(capsys)

    # 0x10 0x00 + 20-byte top
    assert data[0:2] == [0x10, 0x00]
    top = data[2:22]
    assert len(top) == 20
    assert bytes(top[:3]).decode() == "ABC"

    # 0x10 0x14 + first 19 bytes of bottom
    assert data[22:24] == [0x10, 0x14]
    bottom19 = data[24:43]
    assert len(bottom19) == 19
    assert bytes(bottom19[:3]).decode() == "XYZ"

    # 0x10 0x27 + the 20th bottom byte
    assert data[43:45] == [0x10, 0x27]
    assert data[45] == ord(" ")  # 20th char of "XYZ" padded is a space

    # 0x10 0x00 scroll-suppress reposition, then 0x14 hide cursor LAST
    assert data[46:48] == [0x10, 0x00]
    assert data[48] == CMD_HIDE_CURSOR
    assert data[-1] == CMD_HIDE_CURSOR
    assert len(data) == 49


def test_show_ends_with_cursor_hide_and_has_scroll_suppress_pair(driver, capsys):
    driver.show("date", "time")
    data = capture_bytes(capsys)
    assert data[-1] == 0x14  # cursor-hide is the final byte
    # The 0x10 0x27 (40th cell) ... 0x10 0x00 (reposition) pair is present.
    assert [0x10, 0x27] == data[-6:-4]
    assert [0x10, 0x00] == data[-3:-1]


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
