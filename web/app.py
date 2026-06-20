"""FastAPI control surface for check-out.

Two-process design (the daemon is NOT touched):

    web (this app)            daemon
    -------------             ------
    writes state.json   -->   reads state.json  --> drives the VFD
    reads  status.json  <--   writes status.json (what's on the glass + health)

Single-writer-per-file is preserved: the web app only ever WRITES state.json and
only ever READS status.json. It never opens the serial port. All state handling
reuses ``checkout.state`` (schema, defaults, atomic writes, deep-merge) so the
two processes agree on the format byte-for-byte.

Run (prod): build the UI (``ui/dist``) then ``uvicorn web.app:app``.
Run (dev):  ``uvicorn web.app:app --reload`` + ``npm run dev`` in ui/ (proxy).
Paths come from the same env the daemon uses: CHECKOUT_STATE_PATH /
CHECKOUT_STATUS_PATH (via ``checkout.config``).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from checkout.state import (
    load_state,
    load_status,
    merge_patch,
    save_state,
    status_defaults,
)

# A status.json older than this (or missing) means the daemon isn't running.
STALE_SECONDS = 5.0

# Where the built Svelte app lands (ui/dist). Overridable for deployment layouts.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_DIST = os.environ.get("CHECKOUT_UI_DIST", os.path.join(_REPO_ROOT, "ui", "dist"))

app = FastAPI(title="check-out control surface")

# Open CORS for local dev (vite dev server on a different port).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _daemon_alive(status: dict) -> bool:
    """True if status.json is present, marked alive, and fresh (< STALE_SECONDS)."""
    if not status or not status.get("alive"):
        return False
    stamp = status.get("updated_at")
    if not stamp:
        return False
    try:
        updated = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return False
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - updated).total_seconds()
    return age < STALE_SECONDS


# --- API -------------------------------------------------------------------
@app.get("/api/status")
def get_status() -> dict:
    """The daemon's mirror of the glass. Empty/absent -> a not-alive placeholder."""
    status = load_status()
    if not status:
        return {**status_defaults(), "alive": False, "updated_at": None}
    return status


@app.get("/api/state")
def get_state() -> dict:
    """The desired state the daemon reads each tick (backfilled to full schema)."""
    return load_state()


class StatePatch(BaseModel):
    # A free-form partial; validated/normalized by the state schema on merge.
    model_config = {"extra": "allow"}


@app.put("/api/state")
async def put_state(patch: dict) -> dict:
    """Merge-patch a partial into state.json (deep-merge + atomic write)."""
    current = load_state()
    merged = merge_patch(current, patch or {})
    save_state(merged)
    return load_state()


class CommandBody(BaseModel):
    action: str
    args: dict = {}


@app.post("/api/command")
def post_command(body: CommandBody) -> dict:
    """Queue a one-shot daemon command by stamping a fresh nonce into state.command."""
    command = {"id": uuid.uuid4().hex, "action": body.action, "args": body.args or {}}
    current = load_state()
    merged = merge_patch(current, {"command": command})
    save_state(merged)
    return {"command": command}


@app.get("/api/health")
def get_health() -> dict:
    """Liveness derived from status.json freshness."""
    return {"ok": True, "daemon_alive": _daemon_alive(load_status())}


# --- static UI (mounted last so /api/* wins) -------------------------------
if os.path.isdir(UI_DIST):
    app.mount("/", StaticFiles(directory=UI_DIST, html=True), name="ui")
else:
    @app.get("/")
    def _no_ui() -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={
                "detail": "UI not built. Run `npm run build` in ui/ "
                f"(expected at {UI_DIST}). The /api endpoints are live.",
            },
        )
