# check-out

## Overview
`check-out` is a status board that drives a salvaged **IBM SurePOS 2x20 VFD**
customer display (blue-green vacuum-fluorescent, 2 lines × 20 chars) over a
write-only serial link. A long-running daemon owns the serial port, reads desired
state from a JSON file each tick, renders the active frame to fit the 40-character
budget, and writes it to the display. Phase 1 ships a working clock plus the
architecture seams (state file, frame interface) that a web UI plugs into later.
The governing constraint: the port is **write-only at 9600 baud** and only the
command bytes below are confirmed safe — never emit anything else.

## Hardware reference
- **Port / baud:** `/dev/ttyUSB0`, 9600 8N1, **WRITE-ONLY** — never read from it.
- **Geometry:** 2 lines × 20 chars (40 char total budget).

### Command bytes — authoritative Futaba M202MD10C set
Single-byte control codes (NOT ESC/POS). Recovered from the SNMetamorph
`FutabaVfdM202MD10C` library source (our exact board) and bench-confirmed on this
unit. The `abomin` "extended mode" enable was the missing piece (see init below).

| Command                 | Bytes                          |
|-------------------------|--------------------------------|
| Extended mode           | `0x00` then `0x01` enable / `0x00` disable |
| Select code page        | `0x02` + page byte (12 pages)  |
| Define character        | `0x03` + index + 7 bytes + `0x00` (9 user glyphs) |
| Dimming / brightness    | `0x04` + level byte            |
| Print ticker text       | `0x05` (hardware ticker, 45-char buffer) |
| Backspace               | `0x08`                         |
| Self test               | `0x0F`                         |
| Set cursor position     | `0x10` + position byte (= col + row*20) |
| Disable vertical scroll | `0x11`                         |
| Enable vertical scroll  | `0x12`                         |
| Cursor on               | `0x13`                         |
| Cursor off              | `0x14` (must be sent LAST — see rule 1) |
| Reset                   | `0x1F`                         |
| Brightness DIM          | `0x04 0x20`                    |
| Brightness BRIGHT       | `0x04 0xFF`                    |
| Write text              | printable ASCII at cursor (auto-advances + wraps) |

### Required INIT sequence (mandatory on every open/reconnect)
```
0x1F            reset
0x00 0x01       enable extended mode   <-- the missing piece
0x11            disable vertical scroll
```
Without `0x00 0x01` + `0x11` the display scrolls when the bottom-right cell is
written. `VFDDriver.initialize()` sends exactly these bytes and is called from
`open()` (and on every reconnect).

### Addressing (linear: `position = col + row*20`, row 0 = top)
| Line        | Range        |
|-------------|--------------|
| Top line    | `0x00`–`0x13` (0–19)  |
| Bottom line | `0x14`–`0x27` (20–39) |

**ALL 40 CELLS ARE WRITABLE** once initialized correctly. (The earlier
"39-cell / `0x27` phantom scroll / no-leading-clear" findings were artifacts of
the MISSING INITIALIZATION — no extended mode, scroll left on. Resolved.)

### Behavioral rules (bench-verified — do not regress)
1. **Cursor-off last.** `0x14` hides the cursor, but ANY subsequent write
   re-enables it (no persistent off, no separate on byte). So `0x14` must be the
   FINAL byte of every frame update.
2. **Initialize before drawing.** Extended mode + scroll-off (the init sequence)
   must be set before any full frame, or the display scrolls. `open()` handles
   this; `blank()` re-asserts it so the display is never left in scroll mode.
3. **Vertical scroll is a controllable mode.** `0x12` enables it, `0x11` disables
   it — exposed via `set_vertical_scroll(bool)` for later ticker effects.
4. **Brightness = two confirmed levels.** DIM (`0x04 0x20`) / BRIGHT (`0x04 0xFF`).
   Live, no redraw needed. The library claims 4 levels; extended mode may expose
   more — TODO to retest the intermediate bytes (left at the two confirmed for now).

### `show()` byte sequence (keep intact)
```
0x10 0x00  <top: EXACTLY 20 ASCII bytes>     # cells 0x00..0x13
0x10 0x14  <bottom: EXACTLY 20 ASCII bytes>   # cells 0x14..0x27 — full 20 now
0x14       # cursor off — MUST be last
```
One buffered serial write (no flicker). Overwrite-in-place, NO leading clear, NO
`0x27` special-case, NO anchor/reposition — all gone now that init is correct.

### Pin map (RJ-style connector)
| Pin | Use                                            |
|-----|------------------------------------------------|
| 1   | **back-feed hazard — leave open**              |
| 3   | DATA                                           |
| 5   | GND                                            |
| 8   | +12V                                           |

## Architecture
The daemon is the **sole owner** of the serial port (only one process may hold
it). The web UI (Phase 2b) communicates *only* by writing `state.json`; the
daemon communicates back *only* by writing `status.json`. One-directional file
ownership = no races.

```
state.json  (web WRITES, daemon reads)  ──┐
                                          v
daemon loop --> active frame --> renderer (fit to 2x20) --> driver --> serial
                                          │
status.json (daemon WRITES, web reads) <──┘   (mirror of the glass + health)
```

- `driver.py` — `VFDDriver`, owns **all** raw command bytes; nothing else emits bytes.
- `renderer.py` — pure fit/pad/center/ticker logic (no serial).
- `frames/base.py` — `Frame` interface; `frames/{clock,message,ticker}.py`.
- `state.py` — atomic load/save of `state.json` + `status.json`.
- `daemon.py` — main loop + entrypoint; diffs frames, reconnects, shuts down clean.

## Phase 2 — control surface (v0.3.0)
Everything the display can do is driven by `state.json` (the daemon stays sole
port owner). The web UI is just a writer of this file.

### `state.json` (web writes, daemon reads each tick)
```jsonc
{
  "mode": "clock" | "message" | "ticker",   // active frame
  "message": "text for message/ticker mode",
  "brightness": "dim" | "bright",
  "blank": false,
  "scroll": false,                 // hardware vertical-scroll MODE (0x11/0x12); normally false
  "code_page": 0,                  // 0..11
  "scroll_speed_ms": 300,          // ticker software-scroll step
  "animation": "none" | "flash" | "blink",
  "animation_params": { "on_ms": 500, "off_ms": 500 },
  "glyphs": { "0": [r0..r6], ... "8": [...] },  // optional 5x7 glyphs; 7 ints, low 5 bits = cols 1..5
  // place a glyph in `message` with {g0}..{g8}
  "command": { "id": "uuid-or-null", "action": "self_test"|"reset"|"redefine_glyphs", "args": {} },
  "updated_at": "iso"
}
```
`load_state()` backfills every missing key from defaults (nested `command` /
`animation_params` are merged, not replaced), so a partial write never breaks the
daemon.

### `status.json` (daemon writes, web reads)
```jsonc
{ "alive": true, "mode": "...", "top": "....20....", "bottom": "....20....",
  "brightness": "...", "blank": false, "scroll": false,
  "last_command_id": "...", "updated_at": "iso" }
```
Written atomically on change. This is how the UI mirrors the real display + daemon health.

### Command nonce
`command.id` is a nonce. The daemon runs `command.action` once per *new* id
(tracked in-memory) and records it as `last_command_id`. A null id is a no-op;
re-using an id is ignored. All actions are idempotent (so re-running once on
restart is safe): `self_test`, `reset` (both re-initialize the display after),
`redefine_glyphs` (defines `state.glyphs`, then re-initializes).

### Modes & animations
- **Modes:** `clock` (date/time), `message` (static; newline splits the two
  lines, else word-wrapped/centered, ≤40 chars), `ticker` (software horizontal
  scroll of a long message on the top line, `scroll_speed_ms` per step).
- **Animations:** `none` (show when changed), `flash` (alternate frame / real
  `blank()`), `blink` (alternate frame / blank lines — display stays on), timed
  by `animation_params.on_ms`/`off_ms`.

> **Re-init rule:** after `self_test()`, `reset()`, or `define_character()` the
> display may drop extended-mode/scroll-off, so `initialize()` is re-run before
> the next `show()`. The driver methods `self_test`/`reset` do this themselves;
> the daemon re-inits after a glyph batch.

### User glyphs (bench-confirmed, v0.3.1)
There are **9 user-glyph slots** at **non-contiguous** character codes
(`0x1B` is skipped):

| slot | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|------|---|---|---|---|---|---|---|---|---|
| code |`0x15`|`0x16`|`0x17`|`0x18`|`0x19`|`0x1A`|`0x1C`|`0x1D`|`0x1E`|

- **Define:** `0x03 <code> <7 row bytes> 0x00` (top row first).
- **Display:** write the slot's code byte (e.g. `0x15` for slot 0). `glyph_code(n)`
  returns it; `_sanitize` allow-lists these codes so they survive into `show()`.
- **Bitmap (the v0.3.0 bug):** the display reads the 5 columns from **bits 3-7**
  of each row byte, NOT the low 5 bits:

  | column | 1 (left) | 2 | 3 | 4 | 5 (right) |
  |--------|----------|---|---|---|-----------|
  | bit    | 3 (`0x08`)|4 (`0x10`)|5 (`0x20`)|6 (`0x40`)|7 (`0x80`)|

  A lit pixel in column C sets bit (C+2); a full row = `0xF8`; bits 0-2 ignored.
- **Input convention:** `define_character(slot, rows)` takes **editor-natural**
  rows — 7 ints whose **low 5 bits are columns 1..5** (`bit0`=col1 … `bit4`=col5).
  The driver translates each to the wire byte by `(row & 0x1F) << 3`
  (e.g. `0x1F`→`0xF8`, `0x01`→`0x08`, `0x10`→`0x80`). The public API is intuitive;
  the `<<3` lives in the driver only. `state.glyphs` uses this same low-5-bit
  convention, so the future editor/preview and the daemon share one format.
- **Placing glyphs in text:** `{g0}`..`{g8}` in a `message` are replaced (in the
  message/ticker frames) by the slot's code byte, so you can mix text + glyphs,
  e.g. `"TEMP {g0}C"`.

### Code pages (confirmed available)
`select_code_page(page)` → `0x02 <page>`; `page` is a name or int `0..11`
(12 total). Confirmed names: `0` default, `1` japanese (CP897), `2` cp850
(Fr/De/Es/Pt), `3` cp852, `4` cp855, `5` cp857 (Turkish). Pages 6–11 exist per
the library but are not yet identified on our unit. `state.code_page` drives this.

## Phase 2b — web control surface (v0.4.0)
A single-page **Svelte** app (`ui/`) served by a **FastAPI** backend (`web/`).
The daemon is UNTOUCHED and remains the sole serial-port owner. Two processes,
filesystem-coupled, single-writer-per-file:

```
ui/ (Svelte)  --HTTP-->  web/ (FastAPI)  --writes state.json-->  daemon --> VFD
   ^  polls /api/status         ^  reads status.json  <----------  (writes it)
```

- **FastAPI never opens the serial port.** It only reads `status.json` and
  writes `state.json`, reusing `checkout.state` (schema, defaults, atomic write,
  `merge_patch`, `load_status`) so the format matches the daemon byte-for-byte.
- **Endpoints:** `GET /api/status` (the glass mirror), `GET /api/state`,
  `PUT /api/state` (deep merge-patch), `POST /api/command` (stamps a fresh
  `command.id` nonce → daemon runs once), `GET /api/health`
  (`daemon_alive` = status.json fresh < 5s), `/` serves the built UI (`ui/dist`).
- **Preview mirrors status, not controls.** `VfdPreview` renders a pixel-accurate
  2×20 of 5×7 phosphor dots from `/api/status`, so it shows real clock ticks /
  ticker motion / brightness / blank. Built-in 5×7 font for ASCII; the 9 user
  glyph codes render from `state.glyphs` via the shared low-5-bit convention.
- **Controls** (`PUT /api/state` on change): mode, message (+`{gN}` hint),
  brightness, blank, hardware scroll, code page, animation (+on/off ms), ticker
  speed. `CommandBar` fires self_test/reset; `StatusReadout` shows daemon health.
  `GlyphEditorPanel` is a placeholder (full editor next phase).
- **Config:** `CHECKOUT_STATE_PATH` / `CHECKOUT_STATUS_PATH` (shared with daemon)
  via `checkout.config`; `CHECKOUT_UI_DIST` for the built UI. Docker is Phase 3.

See `web/README.md` and `ui/README.md` for run instructions.

### UI toolchain + verify loop (MANDATORY)
The UI is Svelte 4 + Vite 5 + TypeScript, built/tested with Node (Node 22 via nvm
in this repo). Scripts in `ui/package.json`:
- `npm run build` — `vite build` → `ui/dist`
- `npm run check` — `svelte-check` (type + a11y)
- `npm run test`  — `vitest run` (pure font/render helpers, DOM-free)
- `npm run verify` — `svelte-check && vitest run && vite build` (the gate)

**RULE: every UI change must pass `npm run verify` (zero errors, no A11y
warnings) before commit.** v0.4.0 shipped UI that never compiled; v0.4.1 fixed it
and added this gate. Do not commit `.svelte`/`ui` changes you haven't built.

Gotcha that caused v0.4.0: Svelte parses markup expressions with acorn, **not**
TypeScript — no `as`/type annotations inside `{...}`. Keep all TS (casts, typed
params) in `<script lang="ts">` handler functions and call them from markup. Use
real `<button type="button">`/`<label>` controls (not `aria-disabled` on a
`<section>`) to keep svelte-check's a11y pass clean.

## Versioning
Semver `major.minor.patch` read as **"big.small.bug"**.

## How to run
```bash
# Daemon (owns the serial port)
pip install -r requirements.txt
python -m checkout.daemon --dry-run   # no display; prints outgoing bytes as hex
python -m checkout.daemon             # live, opens the serial port

# Web control surface (Phase 2b) — separate process, never opens the port
pip install -r web/requirements.txt
( cd ui && npm install && npm run build )   # build the Svelte app -> ui/dist
uvicorn web.app:app --port 8000             # serves UI + /api; shares state/status json
# dev: `uvicorn web.app:app --reload` + `cd ui && npm run dev` (vite proxies /api)
```
Env overrides: `CHECKOUT_PORT`, `CHECKOUT_BAUD`, `CHECKOUT_TICK_MS`,
`CHECKOUT_STATE_PATH`, `CHECKOUT_STATUS_PATH`, `CHECKOUT_UI_DIST`.

## Serial permissions
The dev user must belong to the device's group (on Arch this is `uucp`) or run
with `sudo`:
```bash
sudo usermod -aG uucp "$USER"   # then re-login
```

## Roadmap
- **Phase 1:** driver, renderer, clock frame, daemon, state seam. (done)
- **Phase 2a (v0.3.0):** rich `state.json` schema + `status.json`; message/ticker
  frames; flash/blink animation; command nonce (self_test/reset/redefine_glyphs);
  glyphs + code pages wired. All driven by `state.json` (no web yet). (done)
- **Phase 2b (v0.4.0):** Svelte/FastAPI web control surface — FastAPI reads
  status.json / writes state.json (never the port) + serves the UI; Svelte app
  with the live phosphor preview + core controls. Glyph editor scaffolded. (done)
- **Phase 3:** more frames + rotation + Docker for arda.
- Brightness byte confirmed in v0.1.1 (two levels: dim/bright).
- **v0.2.0:** adopted the authoritative Futaba M202MD10C command set + extended-mode
  init sequence — all 40 cells now writable, the old 39-cell/scroll workarounds removed.
  Vertical scroll exposed as a controllable feature. TODO: retest 4-level brightness.
- **v0.3.1:** bench-confirmed the user-glyph pipeline — 9 non-contiguous codes,
  bitmap columns in bits 3-7 (fixed the v0.3.0 low-5-bit encoding), `{gN}` message
  placeholders, code-page name map. Glyph + code-page bench TODOs resolved.
- **v0.4.0:** web control surface — FastAPI (`web/`) over the JSON files +
  Svelte phosphor UI (`ui/`) with the live preview and core controls. Daemon
  untouched. `checkout.state` gained `load_status` + `merge_patch` for reuse.
- **v0.4.1:** fixed the UI build (it shipped uncompiled) — `lang="ts"` + typed
  handlers (no inline TS casts in markup), a11y clean; added `npm run verify`
  (svelte-check + vitest + vite build) as the mandatory pre-commit gate.
- **v0.4.2:** VfdPreview now renders live status — canvas buffer sized via
  ResizeObserver (ctx → size → draw, dpr-scaled, never 0×0) with reactive redraw
  each poll. Daemon coerces an invalid brightness to "bright" once (no per-tick
  log spam). Added a favicon.
- **v0.4.3:** VfdPreview redraw now uses explicit reactive data deps (derived
  top/bottom/bright passed to drawFrame, not a strippable `void` no-op) and an
  un-gated first-frame diagnostic log; added a test tying the canvas decode path
  to litCount. Daemon: after self_test/reset/reconnect it invalidates the
  display-state cache AND skips the rest of that tick, so the NEXT tick re-asserts
  scroll/brightness/code-page/glyphs — fixes the clock scrolling after a self-test.
- **v0.4.4:** replaced the placeholder preview font with the REAL M202MD10C
  charset, decoded from photos of our exact panel (one per char code) in
  Eigenbaukombinat/vfd_kassendisplay. The preview now matches the glass
  dot-for-dot (e.g. 'A' lights 16 dots, not the placeholder's 18).

## Credits / third-party
- **Command set:** SNMetamorph `FutabaVfdM202MD10C` library + the abomin
  "extended mode" discovery (see §3 in spec.md).
- **Preview charset:** the 5×7 glyph bitmaps in `ui/src/lib/font5x7.ts` were
  extracted from the character photos in
  [Eigenbaukombinat/vfd_kassendisplay](https://github.com/Eigenbaukombinat/vfd_kassendisplay)
  (`charsetweb/cropped_<ascii>.jpg`), released into the public domain
  (**Unlicense**). Decoded by sampling each photo's 5×7 dot grid.

## Hardware-confirm TODOs (bench)
- [x] ~~Which character code(s) render the 9 user glyphs~~ — RESOLVED (v0.3.1):
  9 non-contiguous codes `0x15`–`0x1A`, `0x1C`–`0x1E` (`0x1B` skipped); bitmap
  columns are bits 3-7. See "User glyphs" above.
- [x] ~~Whether code pages (`0x02` + page) change the glyph set~~ — RESOLVED
  (v0.3.1): yes; 12 pages, confirmed names 0–5. See "Code pages" above.
- Whether extended mode exposes the library's claimed 4 brightness levels.
