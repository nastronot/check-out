"""Byte-sequence tests for VFDDriver, captured via --dry-run hex output."""

import pytest

from checkout import config
from checkout.driver import CURSOR_OFF, VFDDriver


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


def test_initialize_emits_init_sequence(driver, capsys):
    # Reset, extended-mode enable, disable vertical scroll — in order.
    driver.initialize()
    assert capture_bytes(capsys) == [0x1F, 0x00, 0x01, 0x11]


def test_show_full_40_cell_sequence(driver, capsys):
    driver.show("A" * 20, "B" * 20)
    data = capture_bytes(capsys)

    # No leading clear, no 0x27 special-case, no reposition.
    assert 0x1F not in data
    assert [0x10, 0x27] not in [data[i : i + 2] for i in range(len(data) - 1)]

    # 0x10 0x00 + 20-byte top
    assert data[0:2] == [0x10, 0x00]
    assert data[2:22] == [ord("A")] * 20
    # 0x10 0x14 + full 20-byte bottom
    assert data[22:24] == [0x10, 0x14]
    assert data[24:44] == [ord("B")] * 20
    # Cursor-off LAST, nothing after it.
    assert data[44] == CURSOR_OFF
    assert data[-1] == CURSOR_OFF
    assert len(data) == 2 + 20 + 2 + 20 + 1  # = 45


def test_show_truncates_bottom_to_20(driver, capsys):
    driver.show("T" * 20, "B" * 25)  # bottom too long
    data = capture_bytes(capsys)
    # Bottom chunk after 0x10 0x14 is exactly 20 'B' bytes, then cursor-off.
    assert data[22:24] == [0x10, 0x14]
    assert data[24:44] == [ord("B")] * 20
    assert data[44] == CURSOR_OFF
    assert len(data) == 45


def test_set_vertical_scroll_disable(driver, capsys):
    driver.set_vertical_scroll(False)
    assert capture_bytes(capsys) == [0x11]


def test_set_vertical_scroll_enable(driver, capsys):
    driver.set_vertical_scroll(True)
    assert capture_bytes(capsys) == [0x12]


def test_define_character_sequence(driver, capsys):
    rows = [0x1F, 0x11, 0x11, 0x1F, 0x04, 0x04, 0x04]
    driver.define_character(3, rows)
    # 0x03 <index> <7 row bytes> 0x00
    assert capture_bytes(capsys) == [0x03, 0x03, *rows, 0x00]


def test_define_character_masks_rows_to_low_5_bits(driver, capsys):
    # 0xFF must be masked to 0x1F so a row byte never looks like a control code.
    driver.define_character(0, [0xFF] * 7)
    assert capture_bytes(capsys) == [0x03, 0x00, *([0x1F] * 7), 0x00]


def test_define_character_validates(driver):
    with pytest.raises(ValueError):
        driver.define_character(9, [0] * 7)       # index out of range
    with pytest.raises(ValueError):
        driver.define_character(0, [0] * 6)       # wrong row count


def test_select_code_page_sequence(driver, capsys):
    driver.select_code_page(5)
    assert capture_bytes(capsys) == [0x02, 0x05]


def test_select_code_page_validates(driver):
    with pytest.raises(ValueError):
        driver.select_code_page(12)


def test_self_test_reruns_initialize(driver, capsys):
    driver.self_test()
    # 0x0F then the init sequence (1F 00 01 11).
    assert capture_bytes(capsys) == [0x0F, 0x1F, 0x00, 0x01, 0x11]


def test_reset_reruns_initialize(driver, capsys):
    driver.reset()
    # A reset that restores the initialized state == the init sequence.
    assert capture_bytes(capsys) == [0x1F, 0x00, 0x01, 0x11]


def test_set_brightness_dim(driver, capsys):
    driver.set_brightness("dim")
    assert capture_bytes(capsys) == [0x04, 0x20]


def test_set_brightness_bright(driver, capsys):
    driver.set_brightness("bright")
    assert capture_bytes(capsys) == [0x04, 0xFF]


def test_set_brightness_invalid_raises(driver):
    with pytest.raises(ValueError):
        driver.set_brightness("medium")


def test_blank_reinits_and_ends_in_cursor_hide(driver, capsys):
    # blank() leaves the display dark but in the known-good state (extended mode
    # + scroll off), so it re-emits the init sequence, then cursor-off LAST.
    driver.blank()
    data = capture_bytes(capsys)
    assert data == [0x1F, 0x00, 0x01, 0x11, 0x14]
    assert data[-1] == CURSOR_OFF


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
    assert drv._serial.buf[-1] == CURSOR_OFF
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
