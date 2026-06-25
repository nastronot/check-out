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
    assert loaded["brightness"] == 3  # int 0..3, default Maximum
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
    assert loaded["animation_params"] == {"on_ms": 500, "off_ms": 500, "step_ms": 200}
    assert loaded["glyphs"] == {}
    assert loaded["command"] == {"id": None, "action": None, "args": {}}
    assert loaded["align_top"] == "center"
    assert loaded["align_bottom"] == "center"


def test_marquee_and_scroll_fields_default(state_path):
    loaded = state.load_state()
    assert loaded["marquee_text"] == ""
    assert loaded["marquee_bottom"] == "static"  # static-only now (was "clock")
    assert loaded["marquee_bottom_text"] == ""
    assert loaded["scroll_top_source"] == "message"
    assert loaded["scroll_bottom_source"] == "message"
    assert loaded["scroll_top"] is True
    assert loaded["scroll_bottom"] is False
    assert loaded["scroll_dir_top"] == "left"
    assert loaded["scroll_dir_bottom"] == "left"


def test_marquee_bottom_clock_normalizes_to_static(state_path):
    import json

    # A legacy marquee_bottom="clock" is tolerated but normalized to static-only.
    state_path.write_text(json.dumps({"mode": "marquee", "marquee_bottom": "clock"}))
    loaded = state.load_state()
    assert loaded["marquee_bottom"] == "static"


def test_scroll_sources_validate_and_default(state_path):
    import json

    state_path.write_text(
        json.dumps(
            {
                "scroll_top_source": "clock",     # valid -> kept
                "scroll_bottom_source": "bogus",  # invalid -> default "message"
            }
        )
    )
    loaded = state.load_state()
    assert loaded["scroll_top_source"] == "clock"
    assert loaded["scroll_bottom_source"] == "message"


def test_spectrum_audio_fields_default(state_path):
    loaded = state.load_state()
    assert loaded["audio_source"] == "system"
    assert loaded["audio_device"] is None
    assert loaded["audio_gain"] == 1.0
    assert loaded["audio_decay"] == 0.85


def test_spectrum_audio_fields_validate_and_merge(state_path):
    import json

    state_path.write_text(
        json.dumps(
            {
                "mode": "spectrum",
                "audio_source": "bogus",   # -> "system"
                "audio_gain": 99,          # clamped to 20
                "audio_decay": -1,         # clamped to 0.0
                "audio_device": "Monitor of Speakers",
            }
        )
    )
    loaded = state.load_state()
    assert loaded["mode"] == "spectrum"
    assert loaded["audio_source"] == "system"
    assert loaded["audio_gain"] == 20.0
    assert loaded["audio_decay"] == 0.0
    assert loaded["audio_device"] == "Monitor of Speakers"


def test_audio_decay_zero_passes_through(state_path):
    """A valid 0.0 (snappy) is accepted as-is — not pinned to a 0.5 floor."""
    import json

    state_path.write_text(json.dumps({"mode": "spectrum", "audio_decay": 0.0}))
    assert state.load_state()["audio_decay"] == 0.0


def test_legacy_ticker_mode_migrates_to_scroll(state_path):
    import json

    state_path.write_text(json.dumps({"mode": "ticker", "message": "X"}))
    loaded = state.load_state()
    assert loaded["mode"] == "scroll"  # legacy "ticker" -> "scroll"
    assert loaded["message"] == "X"
    # And it self-heals on disk (written back as "scroll").
    assert json.loads(state_path.read_text())["mode"] == "scroll"


def test_marquee_mode_round_trips(state_path):
    state.save_state(
        {"mode": "marquee", "marquee_text": "NEWS", "marquee_bottom": "static",
         "marquee_bottom_text": "12:00"}
    )
    loaded = state.load_state()
    assert loaded["mode"] == "marquee"
    assert loaded["marquee_text"] == "NEWS"
    assert loaded["marquee_bottom"] == "static"
    assert loaded["marquee_bottom_text"] == "12:00"


def test_pulse_animation_and_step_ms_accepted(state_path):
    import json

    state_path.write_text(
        json.dumps({"animation": "pulse", "animation_params": {"step_ms": 120}})
    )
    loaded = state.load_state()
    assert loaded["animation"] == "pulse"
    # Partial animation_params merges: step_ms set, on_ms/off_ms keep defaults.
    assert loaded["animation_params"]["step_ms"] == 120
    assert loaded["animation_params"]["on_ms"] == 500


def test_partial_write_backfills_alignment_and_keeps_set_value(state_path):
    import json

    state_path.write_text(json.dumps({"align_bottom": "right"}))
    loaded = state.load_state()
    assert loaded["align_bottom"] == "right"   # set value kept
    assert loaded["align_top"] == "center"     # missing key backfilled


def test_round_trip_save_load(state_path):
    state.save_state(
        {"mode": "message", "message": "hello", "brightness": 1, "blank": True}
    )
    loaded = state.load_state()
    assert loaded["mode"] == "message"
    assert loaded["message"] == "hello"
    assert loaded["brightness"] == 1
    assert loaded["blank"] is True


def test_legacy_brightness_string_migrates_to_int_and_persists(state_path):
    import json

    # A pre-v0.6.2 file with "bright" -> migrates to 3 on load AND self-heals on disk.
    state_path.write_text(json.dumps({"brightness": "bright"}))
    loaded = state.load_state()
    assert loaded["brightness"] == 3
    assert json.loads(state_path.read_text())["brightness"] == 3  # written back
    # "dim" -> 0.
    state_path.write_text(json.dumps({"brightness": "dim"}))
    assert state.load_state()["brightness"] == 0


def test_invalid_brightness_falls_back_to_default(state_path):
    import json

    state_path.write_text(json.dumps({"brightness": "neon"}))
    assert state.load_state()["brightness"] == 3  # default Maximum


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
    assert loaded["animation_params"] == {"on_ms": 100, "off_ms": 500, "step_ms": 200}


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
    assert loaded["brightness"] == 3  # filled from defaults (Maximum)
    assert loaded["blank"] is False
