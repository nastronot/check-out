"""Tests for the web-owned message/glyph library (web/library.py + endpoints)."""

import json

import pytest
from fastapi.testclient import TestClient

from checkout import config
from web.app import app


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setattr(config, "STATUS_PATH", str(tmp_path / "status.json"))
    monkeypatch.setattr(config, "LIBRARY_PATH", str(tmp_path / "library.json"))
    return tmp_path


@pytest.fixture
def client(paths):
    return TestClient(app)


def test_empty_library(client):
    data = client.get("/api/library").json()
    assert data == {"messages": [], "glyphs": []}


def test_save_list_delete_message(client, paths):
    r = client.post(
        "/api/library/messages",
        json={
            "name": "Greeting",
            "message": "HELLO\nARDA",
            "mode": "message",
            "align_top": "right",
            "align_bottom": "left",
            "brightness": 2,
            "glyphs": {"0": [31, 0, 0, 0, 0, 0, 0]},
        },
    )
    assert r.status_code == 200
    item = r.json()
    assert item["name"] == "Greeting"
    assert item["glyphs"]["0"] == [31, 0, 0, 0, 0, 0, 0]
    mid = item["id"]

    # Persisted to library.json (atomic, no temp left behind).
    on_disk = json.loads((paths / "library.json").read_text())
    assert on_disk["messages"][0]["id"] == mid
    assert not [p for p in paths.iterdir() if p.name.startswith(".library-")]

    assert len(client.get("/api/library").json()["messages"]) == 1

    assert client.delete(f"/api/library/messages/{mid}").status_code == 200
    assert client.get("/api/library").json()["messages"] == []
    assert client.delete(f"/api/library/messages/{mid}").status_code == 404


def test_recall_message_writes_state_with_glyphs(client):
    saved = client.post(
        "/api/library/messages",
        json={
            "name": "Temp",
            "message": "TEMP {g0}C",
            "mode": "message",
            "align_top": "left",
            "brightness": 1,
            "glyphs": {"0": [14, 17, 17, 17, 14, 4, 14]},
        },
    ).json()

    state = client.post(f"/api/library/messages/{saved['id']}/recall").json()
    assert state["mode"] == "message"
    assert state["message"] == "TEMP {g0}C"
    assert state["align_top"] == "left"
    assert state["brightness"] == 1
    # The message's glyphs landed in live state so the daemon defines them.
    assert state["glyphs"]["0"] == [14, 17, 17, 17, 14, 4, 14]


def test_recall_missing_message_404(client):
    assert client.post("/api/library/messages/nope/recall").status_code == 404


def test_save_list_delete_glyph(client):
    r = client.post(
        "/api/library/glyphs", json={"name": "heart", "rows": [0, 10, 31, 31, 14, 4, 0]}
    )
    assert r.status_code == 200
    gid = r.json()["id"]
    assert r.json()["rows"] == [0, 10, 31, 31, 14, 4, 0]
    assert len(client.get("/api/library").json()["glyphs"]) == 1
    assert client.delete(f"/api/library/glyphs/{gid}").status_code == 200
    assert client.delete(f"/api/library/glyphs/{gid}").status_code == 404


def test_reorder_glyphs_persists(client, paths):
    ids = []
    for name in ("a", "b", "c"):
        ids.append(
            client.post(
                "/api/library/glyphs", json={"name": name, "rows": [0] * 7}
            ).json()["id"]
        )
    # Move the last glyph to the front.
    new_order = [ids[2], ids[0], ids[1]]
    r = client.post("/api/library/glyphs/order", json={"ids": new_order})
    assert r.status_code == 200
    assert [g["id"] for g in r.json()["glyphs"]] == new_order
    # Persisted to disk in the new order.
    on_disk = json.loads((paths / "library.json").read_text())
    assert [g["id"] for g in on_disk["glyphs"]] == new_order
    # GET reflects it.
    assert [g["id"] for g in client.get("/api/library").json()["glyphs"]] == new_order


def test_reorder_tolerates_partial_and_unknown_ids(client):
    a = client.post("/api/library/glyphs", json={"name": "a", "rows": [0] * 7}).json()["id"]
    b = client.post("/api/library/glyphs", json={"name": "b", "rows": [0] * 7}).json()["id"]
    # Only mention b (+ an unknown id); a must survive (appended), unknown ignored.
    r = client.post("/api/library/glyphs/order", json={"ids": [b, "ghost"]})
    assert [g["id"] for g in r.json()["glyphs"]] == [b, a]


def test_reorder_bad_input_rejected(client):
    assert client.post("/api/library/glyphs/order", json={"ids": "nope"}).status_code == 400


def test_bad_input_rejected(client):
    assert client.post("/api/library/messages", json={"name": ""}).status_code == 400
    assert client.post("/api/library/glyphs", json={"name": "x", "rows": [1, 2]}).status_code == 400
    assert client.post(
        "/api/library/glyphs", json={"name": "x", "rows": "nope"}
    ).status_code == 400


def test_glyph_rows_masked_to_low_5_bits(client):
    item = client.post(
        "/api/library/glyphs", json={"name": "full", "rows": [255, 255, 0, 0, 0, 0, 0]}
    ).json()
    assert item["rows"][0] == 31  # 0xFF & 0x1F
