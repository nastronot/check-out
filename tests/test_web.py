"""Backend endpoint tests for the FastAPI control surface (web/app.py).

Uses FastAPI's TestClient and the same tmp-file pattern as test_state.py: point
checkout.config at temp paths so the API reads/writes throwaway JSON.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from checkout import config, state
from web.app import app


@pytest.fixture
def paths(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    status_path = tmp_path / "status.json"
    monkeypatch.setattr(config, "STATE_PATH", str(state_path))
    monkeypatch.setattr(config, "STATUS_PATH", str(status_path))
    return state_path, status_path


@pytest.fixture
def client(paths):
    return TestClient(app)


def test_get_state_returns_full_schema(client):
    data = client.get("/api/state").json()
    # Backfilled defaults: every schema key present.
    for key in ("mode", "message", "brightness", "blank", "scroll", "code_page",
                "animation", "animation_params", "glyphs", "command"):
        assert key in data
    assert data["mode"] == "clock"


def test_put_state_merges_and_persists(client, paths):
    state_path, _ = paths
    r = client.put("/api/state", json={"mode": "message", "message": "HELLO"})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "message"
    assert body["message"] == "HELLO"
    # Persisted to disk in the daemon's format.
    on_disk = json.loads(state_path.read_text())
    assert on_disk["mode"] == "message"
    assert on_disk["message"] == "HELLO"
    # A second partial patch keeps prior fields (deep-merge, not replace).
    client.put("/api/state", json={"brightness": "bright"})
    after = client.get("/api/state").json()
    assert after["mode"] == "message"        # preserved
    assert after["brightness"] == "bright"   # updated


def test_put_state_nested_merge_keeps_siblings(client):
    client.put("/api/state", json={"animation_params": {"on_ms": 100}})
    data = client.get("/api/state").json()
    assert data["animation_params"]["on_ms"] == 100
    assert data["animation_params"]["off_ms"] == 500  # sibling default kept


def test_put_message_preserves_newline(client):
    # A two-line message round-trips with its '\n' intact (MessageFrame splits on it).
    client.put("/api/state", json={"message": "HELLO\nWORLD"})
    assert client.get("/api/state").json()["message"] == "HELLO\nWORLD"


def test_put_partial_glyphs_merges_one_slot(client):
    # The glyph editor pushes one slot at a time — other slots must survive.
    client.put(
        "/api/state",
        json={"glyphs": {"0": [1, 2, 3, 4, 5, 6, 7], "5": [7, 6, 5, 4, 3, 2, 1]}},
    )
    client.put("/api/state", json={"glyphs": {"3": [31, 0, 31, 0, 31, 0, 31]}})
    glyphs = client.get("/api/state").json()["glyphs"]
    assert glyphs["0"] == [1, 2, 3, 4, 5, 6, 7]  # preserved
    assert glyphs["5"] == [7, 6, 5, 4, 3, 2, 1]  # preserved
    assert glyphs["3"] == [31, 0, 31, 0, 31, 0, 31]  # merged in


def test_post_command_sets_new_id_each_call(client):
    first = client.post("/api/command", json={"action": "self_test"}).json()
    second = client.post("/api/command", json={"action": "reset", "args": {}}).json()
    assert first["command"]["action"] == "self_test"
    assert second["command"]["action"] == "reset"
    assert first["command"]["id"] != second["command"]["id"]
    # The latest command is reflected in state.
    assert client.get("/api/state").json()["command"]["id"] == second["command"]["id"]


def test_get_status_returns_status_json(client, paths):
    _, status_path = paths
    state.save_status({"alive": True, "mode": "clock", "top": "T", "bottom": "B"})
    body = client.get("/api/status").json()
    assert body["alive"] is True
    assert body["top"] == "T"
    assert body["mode"] == "clock"


def test_get_status_when_missing_is_not_alive(client):
    body = client.get("/api/status").json()
    assert body["alive"] is False


def test_health_fresh_status_is_alive(client):
    state.save_status({"alive": True, "mode": "clock"})  # stamps fresh updated_at
    health = client.get("/api/health").json()
    assert health["ok"] is True
    assert health["daemon_alive"] is True


def test_health_stale_status_is_not_alive(client, paths):
    _, status_path = paths
    old = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    status_path.write_text(json.dumps({"alive": True, "updated_at": old}))
    assert client.get("/api/health").json()["daemon_alive"] is False


def test_health_missing_status_is_not_alive(client):
    assert client.get("/api/health").json()["daemon_alive"] is False
