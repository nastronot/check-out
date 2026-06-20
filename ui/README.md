# ui/ — Svelte phosphor control surface

A single-page Svelte + Vite + TypeScript app: a pixel-accurate live preview of
the 2×20 VFD plus the core controls. It talks only to the FastAPI backend
(`/api/*`) — it never touches the serial port.

## Design

Blue-green VFD phosphor (`#3df0c8`) on near-black, styled like the faceplate of
POS / rack gear: thin rules, monospaced labels, subtle bevels, tactile
switches, and a faint scanline + bloom **on the preview only**. Plain CSS (no
framework) so the aesthetic is hand-tuned.

## Components

- **VfdPreview** — the centerpiece. A canvas-rendered 2×20 grid of 5×7 phosphor
  dots that mirrors `/api/status` (so it shows real clock ticks, ticker motion,
  brightness, and blank). Built-in 5×7 font for ASCII `0x20–0x7E`; the 9 user
  glyph codes render from `state.glyphs` using the shared low-5-bit convention.
- **ControlPanel** — mode, message (+40-char budget, `{g0}`…`{g8}` hint),
  brightness, blank, hardware scroll, code page, animation (+on/off ms), ticker
  speed. Each change `PUT`s `/api/state`.
- **CommandBar** — fire-once `self_test` / `reset` via `POST /api/command`.
- **StatusReadout** — daemon alive LED (from `/api/health`), mode, last update.
- **GlyphEditorPanel** — placeholder for the next phase (reserves layout space).

The preview always reflects **what the daemon actually rendered** (`/api/status`),
not the raw control values, so it's an honest mirror.

## Run

```bash
npm install

# Dev (hot reload). Run the backend too: `uvicorn web.app:app --port 8000`.
# Vite proxies /api -> :8000 (see vite.config.ts).
npm run dev          # http://localhost:5173

# Production build -> dist/, which uvicorn serves at /.
npm run build

# Unit test (pure font/render helpers — no DOM).
npm run test

# Type-check.
npm run check
```

> Requires Node 18+. Docker packaging is Phase 3; the build output (`dist/`) is
> static and served by the FastAPI process in production.
