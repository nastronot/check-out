"""Bump bar web routes: the web WRITES bumpbar.json, reads the service's status."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from checkout import bumpbar_map as bm
from checkout import config
from web.app import app


@pytest.fixture
def paths(tmp_path, monkeypatch):
    m, s = tmp_path / "bumpbar.json", tmp_path / "bumpbar-status.json"
    monkeypatch.setattr(config, "BUMPBAR_PATH", str(m))
    monkeypatch.setattr(config, "BUMPBAR_STATUS_PATH", str(s))
    return m, s


@pytest.fixture
def client(paths):
    return TestClient(app)


def test_get_bumpbar_without_service(client):
    data = client.get("/api/bumpbar").json()
    assert data["installed"] is False and data["alive"] is False
    assert data["map"] == bm.default_map() and data["map_error"] is None
    assert data["shift"] == "shift" and data["layers"] == ["tap", "shift"]
    assert [b["id"] for b in data["buttons"]] == list(bm.BUTTONS)
    assert any(a["id"] == "lock" for a in data["actions"])


def test_get_bumpbar_with_fresh_status(client, paths):
    _, s = paths
    s.write_text(json.dumps({"alive": True, "connected": True,
                             "updated_at": datetime.now(timezone.utc).isoformat()}))
    data = client.get("/api/bumpbar").json()
    assert data["installed"] is True and data["alive"] is True
    assert data["status"]["connected"] is True


def test_get_bumpbar_stale_status_is_installed_but_not_alive(client, paths):
    _, s = paths
    old = datetime.now(timezone.utc) - timedelta(seconds=60)
    s.write_text(json.dumps({"alive": True, "updated_at": old.isoformat()}))
    data = client.get("/api/bumpbar").json()
    assert data["installed"] is True and data["alive"] is False


def test_get_bumpbar_corrupt_map_reports_error(client, paths):
    m, _ = paths
    m.write_text("{bad")
    data = client.get("/api/bumpbar").json()
    assert data["map"] == bm.default_map()
    assert "cannot read" in data["map_error"]


def test_put_map_saves(client, paths):
    m, _ = paths
    r = client.put("/api/bumpbar/map", json={"tap": {"next": "lock"}})
    assert r.status_code == 200 and r.json()["tap"]["next"] == "lock"
    assert json.loads(m.read_text())["tap"]["next"] == "lock"


@pytest.mark.parametrize("body", [{"tap": {"next": "rm_rf"}}, {"tap": {"shift": "lock"}}])
def test_put_map_rejects(client, body):
    assert client.put("/api/bumpbar/map", json=body).status_code == 400


def test_reset(client):
    client.put("/api/bumpbar/map", json={"tap": {"next": "lock"}})
    assert client.post("/api/bumpbar/map/reset").json() == bm.default_map()
