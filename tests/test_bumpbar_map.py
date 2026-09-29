"""Bump bar buttons, key codes and the two-layer key map (bumpbar.json)."""

import json

import pytest

from checkout import bumpbar_map as bm


def test_buttons_grid_and_shift():
    assert bm.BUTTONS == ("decrease", "increase", "previous", "next", "print",
                          "shift", "rotate", "toggle", "recall", "serve")
    assert [b["id"] for b in bm.button_info()] == list(bm.BUTTONS)
    assert all({"id", "legend", "color"} <= set(b) for b in bm.button_info())


def test_keycodes_follow_matts_reading():
    # col 1 a-e top to bottom, col 2 f-j (evdev KEY_A=30 ... KEY_J=36)
    assert [bm.button_for(c) for c in (30, 48, 46, 32, 18)] == [
        "decrease", "previous", "print", "rotate", "recall"]
    assert [bm.button_for(c) for c in (33, 34, 35, 23, 36)] == [
        "increase", "next", "shift", "toggle", "serve"]
    assert bm.button_for(1) is None


def test_default_map_matches_spec():
    m = bm.default_map()
    assert m["tap"]["decrease"] == "brightness_down"
    assert m["tap"]["serve"] == "open_headline"
    assert m["shift"]["serve"] == "media_play_pause"
    assert m["shift"]["print"] == "none"
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
