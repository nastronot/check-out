"""Bump bar buttons, key codes and the two-layer key map (bumpbar.json)."""

import json

import pytest

from checkout import bumpbar_map as bm


def test_buttons_grid_and_shift():
    assert bm.BUTTONS == ("decrease", "increase", "previous", "next", "print",
                          "shift", "rotate", "toggle", "recall", "serve")
    assert [b["id"] for b in bm.button_info()] == list(bm.BUTTONS)
    assert all({"id", "legend", "color"} <= set(b) for b in bm.button_info())


def test_keycodes_follow_matts_reading_rotated():
    # The bar's own positions: col 1 a-e top to bottom, col 2 f-j (evdev
    # KEY_A=30 ... KEY_J=36). Mounted rotated 180°, each button sends the code
    # of the position diagonally opposite: DECREASE (top-left) sends j.
    assert bm.ROTATED
    assert [bm.button_for(c) for c in (36, 23, 35, 34, 33)] == [   # j i h g f
        "decrease", "previous", "print", "rotate", "recall"]
    assert [bm.button_for(c) for c in (18, 32, 46, 48, 30)] == [   # e d c b a
        "increase", "next", "shift", "toggle", "serve"]
    assert bm.button_for(1) is None


def test_keycodes_upright_mount():
    up = bm._keycodes(rotated=False)
    assert [up[c] for c in (30, 48, 46, 32, 18)] == [
        "decrease", "previous", "print", "rotate", "recall"]
    assert [up[c] for c in (33, 34, 35, 23, 36)] == [
        "increase", "next", "shift", "toggle", "serve"]


def test_default_map_matches_spec():
    m = bm.default_map()
    assert m["tap"]["decrease"] == "brightness_down"
    assert m["tap"]["serve"] == "open_headline"
    assert m["shift"]["serve"] == "media_play_pause"
    assert m["tap"]["print"] == "mode_cycle" and m["tap"]["rotate"] == "mode_option"
    assert m["tap"]["recall"] == "news_toggle"
    assert m["shift"]["print"] == "screenshot"
    for layer in bm.LAYERS:
        assert set(m[layer]) == set(bm.BUTTONS) - {bm.SHIFT}
    m["tap"]["decrease"] = "none"
    assert bm.default_map()["tap"]["decrease"] == "brightness_down"  # a copy


def test_validate_fills_missing_from_defaults():
    m = bm.validate_map({"tap": {"next": "volume_up"}})
    assert m["tap"]["next"] == "volume_up"
    assert m["tap"]["previous"] == "mode_prev"
    assert m["shift"] == bm.default_map()["shift"]


@pytest.mark.parametrize("bad", [
    [], {"tap": []}, {"tap": {"next": "rm_rf"}}, {"tap": {"shift": "none"}},
    {"tap": {"nope": "none"}}, {"other": {}}])
def test_validate_rejects(bad):
    with pytest.raises(bm.MapError):
        bm.validate_map(bad)


def test_load_missing_is_defaults(tmp_path):
    assert bm.load_map(str(tmp_path / "none.json")) == bm.default_map()


def test_load_map_bad_json_raises(tmp_path):
    p = tmp_path / "m.json"
    p.write_text("{nope")
    with pytest.raises(bm.MapError):
        bm.load_map(str(p))


def test_save_then_load_roundtrip(tmp_path):
    p = str(tmp_path / "m.json")
    saved = bm.save_map(p, {"shift": {"print": "lock"}})
    assert saved["shift"]["print"] == "lock"
    assert bm.load_map(p) == saved
    assert json.loads(open(p).read()) == saved


@pytest.mark.parametrize("bad", [{"tap": {"next": []}}, {"tap": {"next": None}}])
def test_validate_rejects_non_string_actions(bad):
    # A hand-edited file must raise MapError (kept-last-good), never TypeError.
    with pytest.raises(bm.MapError):
        bm.validate_map(bad)


def test_switch_toward_rj11_sends_k_to_t_for_the_same_keys():
    # Bench 2026-09-28: with the bottom switch toward the RJ11 jack every key
    # sends the letter 10 further on (NEXT g→q, PREVIOUS b→l, INCREASE f→p).
    # Both identities map to the same buttons, so the switch position is moot.
    k_to_t = (37, 38, 50, 49, 24, 25, 16, 19, 31, 20)   # k l m n o p q r s t
    a_to_j = (30, 48, 46, 32, 18, 33, 34, 35, 23, 36)   # a b c d e f g h i j
    for second, first in zip(k_to_t, a_to_j):
        assert bm.button_for(second) == bm.button_for(first)
    # rotated mount: q, l, p sit at ROTATE PAGES, TOGGLE SCREENS, RECALL
    assert (bm.button_for(16), bm.button_for(38), bm.button_for(25)) == (
        "rotate", "toggle", "recall")
