"""The shared hand-drawn label/icon bitmaps."""

from checkout import glyphs, spectrum


def _draw(rows):
    return ["".join("#" if r >> c & 1 else "." for c in range(5)) for r in rows]


def test_l_and_r_are_unchanged_by_the_move():
    assert glyphs.LABEL_L == [31, 29, 29, 29, 29, 17, 31]
    assert glyphs.LABEL_R == [31, 17, 21, 25, 21, 21, 31]
    # spectrum re-exports the same values
    assert spectrum.LABEL_L == glyphs.LABEL_L
    assert spectrum.label_glyph("R") == glyphs.LABEL_R


def test_h_is_an_inverted_h():
    assert _draw(glyphs.LABEL_H) == [
        "#####", "#.#.#", "#.#.#", "#...#", "#.#.#", "#.#.#", "#####",
    ]


def test_c_is_an_inverted_c():
    assert _draw(glyphs.LABEL_C) == [
        "#####", "#...#", "#.#.#", "#.###", "#.#.#", "#...#", "#####",
    ]


def test_label_glyph_returns_a_copy():
    g = glyphs.label_glyph("H")
    g[0] = 0
    assert glyphs.LABEL_H[0] == 31
