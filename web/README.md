# web/ — FastAPI control surface

A thin HTTP layer over the JSON files the daemon already uses. It **never opens
the serial port** — the daemon stays the sole owner of `/dev/ttyUSB0`. This
process only:

- **reads** `status.json` (what the daemon actually rendered + health)
- **writes** `state.json` (the desired state the daemon reads each tick)
- serves the built Svelte UI (`ui/dist`)

Single-writer-per-file is preserved (web writes state, daemon writes status), so
the two processes never race over the filesystem.

## Endpoints

| Method | Path           | Purpose |
|--------|----------------|---------|
| GET    | `/api/status`  | Current `status.json` (top/bottom/mode/brightness/blank/scroll/last_command_id/alive/updated_at) |
| GET    | `/api/state`   | Current `state.json` (desired state, full schema) |
| PUT    | `/api/state`   | Merge-patch a partial into `state.json` (deep-merge + atomic write); returns the new state |
| POST   | `/api/command` | Body `{action, args}` → stamps `state.command = {id: <uuid>, action, args}` so the daemon runs it once |
| GET    | `/api/health`  | `{ok, daemon_alive}` — `daemon_alive` is true iff `status.json` is fresh (< 5s) and marked alive |
| GET    | `/api/library` | The saved library `{messages, glyphs}` (web-owned `library.json`) |
| POST   | `/api/library/messages` | Save the current composable state (name + message/mode/align/brightness/glyphs) |
| DELETE | `/api/library/messages/{id}` | Delete a saved message |
| POST   | `/api/library/messages/{id}/recall` | Apply a saved message to `state.json` (fields + its glyphs) — the library→live bridge |
| POST   | `/api/library/glyphs` | Save a glyph `{name, rows}` (7 low-5-bit ints) |
| DELETE | `/api/library/glyphs/{id}` | Delete a saved glyph |
| GET    | `/`            | The built UI (`ui/dist`), or a 503 hint if it isn't built yet |

The library is **web-owned**: the daemon never reads `library.json`. Recall is the only
action that crosses over, and it does so by writing `state.json` (the daemon's normal input).

## Config (shared with the daemon)

Paths come from the same env the daemon uses, via `checkout.config`:

- `CHECKOUT_STATE_PATH`  (default `./state.json`)
- `CHECKOUT_STATUS_PATH` (default `./status.json`)
- `CHECKOUT_LIBRARY_PATH` (default `./library.json`) — web-only; the daemon ignores it
- `CHECKOUT_UI_DIST`     (default `ui/dist`) — where the built UI lives

In deployment both processes share these files via a mounted volume.

## Run

```bash
pip install -r web/requirements.txt

# Dev: API with reload (run the UI separately with `npm run dev`, which proxies /api here)
uvicorn web.app:app --reload --port 8000

# Prod: build the UI first, then serve everything from uvicorn
( cd ui && npm install && npm run build )
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

Tests: `pytest tests/test_web.py` (uses FastAPI's `TestClient`).

> Docker is intentionally deferred to Phase 3, but the layout is container-ready:
> one image can run uvicorn serving `ui/dist`, with the state/status volume shared
> with the daemon container.
