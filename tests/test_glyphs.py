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


def test_degree_is_a_small_ring_at_the_top():
    assert _draw(glyphs.DEGREE) == [
        ".#...", "#.#..", ".#...", ".....", ".....", ".....", ".....",   # hugs the number
    ]


def test_label_glyph_returns_a_copy():
    g = glyphs.label_glyph("H")
    g[0] = 0
    assert glyphs.LABEL_H[0] == 31


def test_bar_lights_whole_columns():
    assert glyphs.bar(4) == [8] * 7
    assert glyphs.bar(2, 3, 4, 5) == [30] * 7


def test_news_banner_bars_match_the_drawn_slots():
    # {g2}{g3}{g5}{g0} NEWS ALERT {g6}{g4}{g3}{g7} as drawn in the glyph editor
    assert [r[0] for r in glyphs.NEWS_BANNER_LEFT] == [30, 14, 12, 8]
    assert [r[0] for r in glyphs.NEWS_BANNER_RIGHT] == [2, 6, 14, 15]
