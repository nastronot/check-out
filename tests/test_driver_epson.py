"""Byte-sequence tests for EpsonDriver (HP LD220-HP, EPSON mode), via dry-run."""

import pytest

from checkout.driver import GLYPH_CODES, VFDDriver
from checkout.driver_epson import GLYPH_FIRST, EpsonDriver


def tx(capsys) -> list[int]:
    data: list[int] = []
    for line in capsys.readouterr().out.splitlines():
        line = line.strip()
        if line.startswith("TX"):
            data.extend(int(t, 16) for t in line[2:].split())
    return data


@pytest.fixture
def hp():
    return EpsonDriver(dry_run=True)


def test_identity():
    assert EpsonDriver.DISPLAY == "hp"
    assert EpsonDriver.LABEL == "HP LD220 2×20 VFD"
    assert VFDDriver.DISPLAY == "ibm"


def test_initialize(hp, capsys):
    hp.initialize()
    # ESC @ · US 01 overwrite · US C 0 cursor off · ESC % 0 user set OFF (it is
    # switched on only around glyph cells)
    assert tx(capsys) == [0x1B, 0x40, 0x1F, 0x01, 0x1F, 0x43, 0x00, 0x1B, 0x25, 0x00]


def test_show_positions_each_row_one_based(hp, capsys):
    hp.show("A" * 20, "B" * 20)
    assert tx(capsys) == ([0x1F, 0x24, 1, 1] + [0x41] * 20
                          + [0x1F, 0x24, 1, 2] + [0x42] * 20)


def test_show_pads_and_truncates(hp, capsys):
    hp.show("hi", "x" * 30)
    data = tx(capsys)
    assert len(data) == 48
    assert data[4:6] == [ord("h"), ord("i")] and data[6:24] == [0x20] * 18


def test_show_changes_one_cell(hp, capsys):
    hp.show_changes(("A" * 20, "B" * 20), ("A" * 5 + "Z" + "A" * 14, "B" * 20))
    assert tx(capsys) == [0x1F, 0x24, 6, 1, ord("Z")]


def test_show_changes_nothing(hp, capsys):
    hp.show_changes(("a", "b"), ("a", "b"))
    assert tx(capsys) == []


def test_show_changes_bottom_row(hp, capsys):
    hp.show_changes(("", ""), ("", "   X"))
    assert tx(capsys) == [0x1F, 0x24, 4, 2, ord("X")]


def test_show_changes_merges_within_gap_of_4(hp, capsys):
    # cells 0 and 5 differ (gap 4) -> one run 0..5
    hp.show_changes(("", ""), ("X    Y", ""))
    assert tx(capsys) == [0x1F, 0x24, 1, 1] + [ord(c) for c in "X    Y"]


def test_show_changes_splits_beyond_gap(hp, capsys):
    hp.show_changes(("", ""), ("X     Y", ""))  # gap 5
    assert tx(capsys) == [0x1F, 0x24, 1, 1, ord("X"), 0x1F, 0x24, 7, 1, ord("Y")]


def test_show_changes_never_crosses_rows(hp, capsys):
    hp.show_changes(("", ""), (" " * 19 + "X", "Y"))
    assert tx(capsys) == [0x1F, 0x24, 20, 1, ord("X"), 0x1F, 0x24, 1, 2, ord("Y")]


def test_show_changes_falls_back_to_full_frame(hp, capsys):
    hp.show_changes(("", ""), ("X" * 20, "Y" * 20))
    assert len(tx(capsys)) == 48


def test_show_bottom(hp, capsys):
    hp.show_bottom("B")
    assert tx(capsys) == [0x1F, 0x24, 1, 2, ord("B")] + [0x20] * 19


def test_brightness_index_to_1_4(hp, capsys):
    for i in range(4):
        hp.set_brightness(i)
    assert tx(capsys) == [0x1F, 0x58, 1, 0x1F, 0x58, 2, 0x1F, 0x58, 3, 0x1F, 0x58, 4]


def test_brightness_legacy_and_range(hp, capsys):
    hp.set_brightness("dim")
    assert tx(capsys) == [0x1F, 0x58, 1]
    with pytest.raises(ValueError):
        hp.set_brightness(4)


def test_glyph_cells_switch_the_user_set_on_around_them(hp, capsys):
    hp.show("A" + chr(GLYPH_CODES[0]) + chr(GLYPH_CODES[8]) + "B", "")
    data = tx(capsys)
    # A, ON, '0', '8', B + padding (letters/spaces are not redefined, so the set
    # stays on), then OFF before the row ends
    assert data[:30] == ([0x1F, 0x24, 1, 1, ord("A"), 0x1B, 0x25, 0x01, 0x30, 0x38,
                          ord("B")] + [0x20] * 16 + [0x1B, 0x25, 0x00])


def test_every_write_ends_with_the_user_set_off(hp, capsys):
    hp.show(chr(GLYPH_CODES[3]) * 20, chr(GLYPH_CODES[3]) * 20)
    data = tx(capsys)
    assert data == ([0x1F, 0x24, 1, 1, 0x1B, 0x25, 0x01] + [0x33] * 20 + [0x1B, 0x25, 0x00]
                    + [0x1F, 0x24, 1, 2, 0x1B, 0x25, 0x01] + [0x33] * 20 + [0x1B, 0x25, 0x00])


def test_real_digits_after_a_glyph_switch_the_set_off_first(hp, capsys):
    hp.show(chr(GLYPH_CODES[0]) + "5", "")
    assert tx(capsys)[4:12] == [0x1B, 0x25, 0x01, 0x30, 0x1B, 0x25, 0x00, ord("5")]


def test_punctuation_prints_as_itself(hp, capsys):
    hp.show("`{[}]|~^\\", "")
    assert bytes(tx(capsys)[4:13]).decode() == "`{[}]|~^\\"


def test_non_printables_become_question_marks(hp, capsys):
    hp.show("\x1b\x0cé\x00", "")
    assert tx(capsys)[4:8] == [ord("?")] * 4


def test_no_control_byte_escapes_from_text(hp, capsys):
    # Only ESC % 0/1 (user set) and US $ x y (cursor) may appear; text bytes are
    # printable. Walk the stream and reject any other control byte.
    hp.show("".join(chr(i) for i in range(20)), "".join(chr(i) for i in range(20, 40)))
    hp.show("".join(chr(i) for i in range(128, 148)), "".join(chr(i) for i in range(0x15, 0x1F)))
    data = tx(capsys)
    i = 0
    while i < len(data):
        if data[i] == 0x1F:
            assert data[i + 1] == 0x24
            i += 4
        elif data[i] == 0x1B:
            assert data[i + 1] == 0x25 and data[i + 2] in (0, 1)
            i += 3
        else:
            assert 0x20 <= data[i] <= 0x7E, hex(data[i])
            i += 1


def test_define_character_only_stores(hp, capsys):
    hp.define_character(0, [0x01, 0, 0, 0, 0, 0, 0x10])
    assert tx(capsys) == []


def test_glyphs_loaded_sends_all_nine_in_one_command(hp, capsys):
    # One ESC & per load: each ESC & REPLACES the whole set on the bench unit.
    # Columns: bit 0 = top row, no width byte (bench 2026-09-28).
    hp.define_character(0, [0x01, 0, 0, 0, 0, 0, 0x10])  # top-left + bottom-right
    hp.define_character(8, [0x1F] * 7)
    hp.glyphs_loaded()
    data = tx(capsys)
    assert data[:5] == [0x1B, 0x26, 0x01, 0x30, 0x38]
    assert len(data) == 5 + 9 * 5
    assert data[5:10] == [0x01, 0x00, 0x00, 0x00, 0x40]
    assert data[10:45] == [0] * 35
    assert data[45:50] == [0x7F] * 5


def test_glyphs_survive_in_the_driver_across_loads(hp, capsys):
    # A mode set redefines only some slots; the others must be re-sent intact.
    hp.define_character(2, [0x1F] * 7)
    hp.glyphs_loaded()
    hp.define_character(0, [0x01] * 7)
    hp.glyphs_loaded()
    last = tx(capsys)[50:]
    assert last[5:10] == [0x7F, 0, 0, 0, 0]
    assert last[15:20] == [0x7F] * 5


def test_define_character_validates(hp):
    with pytest.raises(ValueError):
        hp.define_character(9, [0] * 7)
    with pytest.raises(ValueError):
        hp.define_character(0, [0] * 6)
    with pytest.raises(ValueError):
        hp.define_character(0, ["x"] * 7)


def test_blank_is_clear(hp, capsys):
    hp.blank()
    assert tx(capsys) == [0x0C]


def test_reset_and_self_test(hp, capsys):
    hp.reset()
    init = [0x1B, 0x40, 0x1F, 0x01, 0x1F, 0x43, 0x00, 0x1B, 0x25, 0x00]
    assert tx(capsys) == init
    hp.self_test()
    assert tx(capsys) == [0x1F, 0x40] + init


def test_vertical_scroll(hp, capsys):
    hp.set_vertical_scroll(True)
    hp.set_vertical_scroll(False)
    assert tx(capsys) == [0x1F, 0x02, 0x1F, 0x01]


def test_code_page_only_default(hp, capsys):
    hp.select_code_page("default")
    hp.select_code_page(0)
    assert tx(capsys) == [0x1B, 0x74, 0x00, 0x1B, 0x74, 0x00]
    with pytest.raises(ValueError):
        hp.select_code_page("cp850")


def test_start_ticker_shows_text_on_top_row(hp, capsys):
    hp.start_ticker("HELLO")
    assert tx(capsys) == [0x1F, 0x24, 1, 1] + [ord(c) for c in "HELLO"] + [0x20] * 15


def test_write_at_and_clear(hp, capsys):
    hp.write_at(21, "X")
    hp.clear()
    assert tx(capsys) == [0x1F, 0x24, 2, 2, ord("X"), 0x0C]
    with pytest.raises(ValueError):
        hp.write_at(40, "X")


def test_same_public_surface_as_ibm():
    def public(cls):
        return {n for n in dir(cls) if not n.startswith("_") and callable(getattr(cls, n))}
    assert public(EpsonDriver) == public(VFDDriver)
