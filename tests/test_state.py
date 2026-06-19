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
    assert loaded["brightness"] == 3
    assert loaded["blank"] is False
    assert "updated_at" in loaded
    # Missing file is repaired on load.
    assert state_path.exists()


def test_round_trip_save_load(state_path):
    state.save_state(
        {"mode": "clock", "message": "hello", "brightness": 5, "blank": True}
    )
    loaded = state.load_state()
    assert loaded["message"] == "hello"
    assert loaded["brightness"] == 5
    assert loaded["blank"] is True


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
    assert loaded["brightness"] == 3  # filled from defaults
    assert loaded["blank"] is False
