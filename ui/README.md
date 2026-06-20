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
  brightness, and blank). Real M202MD10C 5×7 font for ASCII `0x20–0x7E`; the 9 user
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

## Verify before committing (required)

**Run `npm run verify` before committing any UI change.** It runs the full gate
and must pass with zero errors (and no A11y warnings):

```bash
npm run verify   # svelte-check  &&  vitest run  &&  vite build
```

This is mandatory — UI code was once committed without compiling. Treat a red
`verify` like a failing test: fix it before you commit. (Common gotcha: Svelte
parses markup expressions with acorn, not TypeScript — no `as`/type annotations
inside `{...}`; move them into typed handler functions in `<script lang="ts">`.)

> Requires Node 18+ (this repo is on Node 22 via nvm). Docker packaging is
> Phase 3; the build output (`dist/`) is static and served by FastAPI in prod.

## Credits

- The 5×7 preview charset (`src/lib/font5x7.ts`) is the real Futaba M202MD10C
  font, decoded from the per-character display photos in
  [Eigenbaukombinat/vfd_kassendisplay](https://github.com/Eigenbaukombinat/vfd_kassendisplay)
  (public domain, Unlicense).
- The display command protocol (used by the daemon this UI drives) comes from
  [SNMetamorph/FutabaVfdM202MD10C](https://github.com/SNMetamorph/FutabaVfdM202MD10C)
  (MIT) — command set, extended-mode init, glyph codes, brightness/code-page
  commands; extended-mode discovery credited to `abomin`.

These are published facts (command bytes, glyph bitmaps), independently
bench-confirmed on our unit; the code here is original.
