"""Unit tests for the atomic JSON state module."""

import os

import pytest

from checkout import config, state


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    """Point the state module at a temp file for each test."""
    path = tmp_path / "state.json"
    monkeypatch.setattr(config, "STATE_PATH", str(path))
    return path


def test_defaults_on_missing_file(state_path):
    assert not state_path.exists()
    loaded = state.load_state()
    assert loaded["mode"] == "clock"
    assert loaded["message"] == ""
    assert loaded["brightness"] == "dim"
    assert loaded["blank"] is False
    assert "updated_at" in loaded
    # Missing file is repaired on load.
    assert state_path.exists()


def test_defaults_include_full_phase2_schema(state_path):
    loaded = state.load_state()
    assert loaded["scroll"] is False
    assert loaded["code_page"] == 0
    assert loaded["scroll_speed_ms"] == 300
    assert loaded["animation"] == "none"
    assert loaded["animation_params"] == {"on_ms": 500, "off_ms": 500}
    assert loaded["glyphs"] == {}
    assert loaded["command"] == {"id": None, "action": None, "args": {}}
    assert loaded["align_top"] == "center"
    assert loaded["align_bottom"] == "center"


def test_partial_write_backfills_alignment_and_keeps_set_value(state_path):
    import json

    state_path.write_text(json.dumps({"align_bottom": "right"}))
    loaded = state.load_state()
    assert loaded["align_bottom"] == "right"   # set value kept
    assert loaded["align_top"] == "center"     # missing key backfilled


def test_round_trip_save_load(state_path):
    state.save_state(
        {"mode": "message", "message": "hello", "brightness": "bright", "blank": True}
    )
    loaded = state.load_state()
    assert loaded["mode"] == "message"
    assert loaded["message"] == "hello"
    assert loaded["brightness"] == "bright"
    assert loaded["blank"] is True


def test_partial_nested_command_is_merged_not_replaced(state_path):
    import json

    # A web write that only sets command.id must keep default action/args.
    state_path.write_text(json.dumps({"command": {"id": "abc"}}))
    loaded = state.load_state()
    assert loaded["command"] == {"id": "abc", "action": None, "args": {}}


def test_partial_nested_animation_params_merged(state_path):
    import json

    state_path.write_text(json.dumps({"animation_params": {"on_ms": 100}}))
    loaded = state.load_state()
    assert loaded["animation_params"] == {"on_ms": 100, "off_ms": 500}


def test_status_round_trip(tmp_path, monkeypatch):
    path = tmp_path / "status.json"
    monkeypatch.setattr(config, "STATUS_PATH", str(path))
    state.save_status(
        {"alive": True, "mode": "clock", "top": "T", "bottom": "B"}
    )
    import json

    data = json.loads(path.read_text())
    assert data["alive"] is True
    assert data["top"] == "T"
    assert "updated_at" in data
    leftovers = [p for p in os.listdir(path.parent) if p.startswith(".status-")]
    assert leftovers == []


def test_atomic_replace_leaves_no_temp(state_path):
    state.save_state(state.defaults())
    leftovers = [p for p in os.listdir(state_path.parent) if p.startswith(".state-")]
    assert leftovers == []


def test_corrupt_file_falls_back_to_defaults(state_path):
    state_path.write_text("{ this is not valid json ")
    loaded = state.load_state()
    assert loaded["mode"] == "clock"
    # The corrupt file is overwritten with valid defaults.
    import json

    assert json.loads(state_path.read_text())["mode"] == "clock"


def test_non_object_root_falls_back(state_path):
    state_path.write_text("[1, 2, 3]")
    loaded = state.load_state()
    assert loaded["mode"] == "clock"


def test_missing_keys_filled_from_defaults(state_path):
    import json

    state_path.write_text(json.dumps({"message": "partial"}))
    loaded = state.load_state()
    assert loaded["message"] == "partial"
    assert loaded["brightness"] == "dim"  # filled from defaults
    assert loaded["blank"] is False
