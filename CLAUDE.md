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
| Print ticker text       | `0x05` + text + `0x0D` (hardware ticker, top row, FIXED speed, 45-char buffer) |
| Backspace               | `0x08`                         |
| Self test               | `0x0F`                         |
| Set cursor position     | `0x10` + position byte (= col + row*20) |
| Disable vertical scroll | `0x11`                         |
| Enable vertical scroll  | `0x12`                         |
| Cursor on               | `0x13`                         |
| Cursor off              | `0x14` (must be sent LAST — see rule 1) |
| Reset                   | `0x1F`                         |
| Brightness (4 levels)   | `0x04` + `0x20`/`0x40`/`0x60`/`0xFF` (Min/Med/Med+/Max) |
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
4. **Brightness = FOUR confirmed levels** (bench-confirmed under extended mode):
   `0x04` + `0x20` Min / `0x40` Med / `0x60` Med+ / `0xFF` Max — the SNMetamorph
   Dimming enum. Live, no redraw needed. The canonical `state.brightness` is an
   int 0..3 (index into those bytes); `set_brightness(0..3)` emits the level. The
   old "two levels (dim/bright)" was an artifact of testing before extended-mode
   init; legacy `"dim"`/`"bright"` still map to 0/3.

### `show()` byte sequence (keep intact)
```
0x10 0x00  <top: EXACTLY 20 ASCII bytes>     # cells 0x00..0x13
0x10 0x14  <bottom: EXACTLY 20 ASCII bytes>   # cells 0x14..0x27 — full 20 now
0x14       # cursor off — MUST be last
```
One buffered serial write (no flicker). Overwrite-in-place, NO leading clear, NO
`0x27` special-case, NO anchor/reposition — all gone now that init is correct.

**Every write DRAINS to the wire (v1.0.0).** After each `self._serial.write(data)`,
`_write()` calls `self._serial.flush()` — on POSIX pyserial this is
`termios.tcdrain(fd)`, which BLOCKS until all bytes are transmitted. The port is
opened non-blocking (`timeout=0`), so a bare `write()` just dumps the frame into
the OS TX buffer and returns; at 9600 baud the buffer drains only ~21fps, so the
daemon's ~30fps spectrum renders piled frames into it until full (~1-1.5s) and the
glass always showed frames that old — the spectrum **latency drift** (bars trail
~1-2s behind the music and after a pause). Draining after each write paces the
daemon to the real serial speed, so the TX buffer can never accumulate a backlog:
spectrum renders at the true wire ceiling with zero growing latency. Normal modes
emit-diff (write rarely), so the drain there is negligible — one consistent,
backlog-free path for all modes.

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
- `daemon.py` — the SINGLE FAST LOOP + entrypoint; diffs frames, reconnects, shuts down clean.
- `spectrum.py` — spectrum protocol + bar rendering + DSP + `SpectrumReceiver`/`Sender` (shared).
- `audioviz.py` — the audio capture + FFT process (separate; streams bars over a socket).

### Single fast loop (v0.9.0)
The daemon runs ONE fast loop (~30Hz, `config.LOOP_HZ`), NOT a 250ms tick. Each
iteration: mtime-gates `state.json` (re-parse only when it changed — a single
`os.stat`), computes the active frame, and **emit-diffs** to the serial port
(writes only when the frame changed). Looping fast is free for normal modes
(clock/message/scroll/marquee touch the port only on content change) because
emit-diffing decouples loop rate from write rate; it's what gives `spectrum` its
frame rate — one code path, no mode-transition seam. Per-mode timing is driven
off elapsed wall-clock (`now_ms`): clock ticks 1/s, scroll steps at
`scroll_speed_ms`, marquee re-kicks on text change, animations by their ms params
— all unchanged behaviorally. `status.json` is THROTTLED to ~`config.STATUS_HZ`
(~6Hz) so the mirror file isn't churned 30×/s (still far inside the 5s liveness
window). The loop self-paces with `time.monotonic`; a slow serial write (spectrum)
naturally paces it below `LOOP_HZ`.

## Phase 2 — control surface (v0.3.0)
Everything the display can do is driven by `state.json` (the daemon stays sole
port owner). The web UI is just a writer of this file.

### `state.json` (web writes, daemon reads each tick)
```jsonc
{
  "mode": "clock" | "message" | "scroll" | "marquee" | "spectrum",  // active frame (legacy "ticker" -> "scroll")
  "message": "text for message/scroll mode",
  "align_top": "left" | "center" | "right",     // line 1 justification (default center)
  "align_bottom": "left" | "center" | "right",  // line 2 justification (default center)
  // marquee (hardware ticker): top autonomous + FIXED speed; bottom STATIC-only
  "marquee_text": "scrolls on the top row (hardware, 45-char buffer)",
  "marquee_bottom": "static",                   // static-only; legacy "clock" normalized to "static"
  "marquee_bottom_text": "the static bottom row text",
  // software scroll (mode "scroll"): per-row source + scroll + direction
  "scroll_top_source": "message" | "clock",     // per-row content source (news-ready)
  "scroll_bottom_source": "message" | "clock",
  "scroll_top": true, "scroll_bottom": false,
  "scroll_dir_top": "left" | "right", "scroll_dir_bottom": "left" | "right",
  "brightness": 0 | 1 | 2 | 3,            // level index (0 Min .. 3 Max); legacy "dim"/"bright" migrate to 0/3
  "blank": false,
  "scroll": false,                 // hardware vertical-scroll MODE (0x11/0x12); normally false
  "code_page": 0,                  // 0..11
  "scroll_speed_ms": 300,          // ticker software-scroll step
  "animation": "none" | "flash" | "blink" | "pulse",
  "animation_params": { "on_ms": 500, "off_ms": 500, "step_ms": 200 },  // step_ms times pulse
  "glyphs": { "0": [r0..r6], ... "8": [...] },  // optional 5x7 glyphs; 7 ints, low 5 bits = cols 1..5
  // place a glyph in `message` with {g0}..{g8}
  // spectrum (mode "spectrum") — SETTINGS only; the live bar data goes over a socket
  "audio_source": "system" | "mic",   // "system" = PipeWire/Pulse monitor; "mic" = default input
  "audio_device": null,               // device name/index, or null = source default
  "audio_gain": 1.0,                  // sensitivity (clamped 0.05..20)
  "audio_decay": 0.85,                // Smoothing: bar release factor (clamped 0..0.999; UI slider 0..0.98, 0 = instant snappy fall)
  "spectrum_style": "bars",           // "bars" (filled) | "line" (single-row peak per band)
  "spectrum_layout": "full",          // "full" (mono) | "stereo_v" (L/R spectra) | "stereo_h" (L/R level meters)
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
  "bars": [0..14]×20 | null,        // full-layout heights (preview), else null
  "spectrum_style": "bars"|"line",  // mirrored render style (preview matches bars vs line)
  "spectrum_layout": "full"|"stereo_v"|"stereo_h",  // mirrored layout (preview matches it)
  "spectrum_left": [0..7]×19 | null, "spectrum_right": [...] | null,  // stereo_v per-channel
  "spectrum_level_l": 0..95 | null, "spectrum_level_r": 0..95 | null,  // stereo_h per-channel
  "last_command_id": "...", "heartbeat": N, "updated_at": "iso" }
```
Written atomically (throttled to ~`STATUS_HZ`). This is how the UI mirrors the
real display + daemon health.

### Command nonce
`command.id` is a nonce. The daemon runs `command.action` once per *new* id
(tracked in-memory) and records it as `last_command_id`. A null id is a no-op;
re-using an id is ignored. All actions are idempotent (so re-running once on
restart is safe): `self_test`, `reset` (both re-initialize the display after),
`redefine_glyphs` (defines `state.glyphs`, then re-initializes).

### Modes & animations
- **Modes:** `clock` (`DD MON YYYY` top / `HH:MM:SS AM/PM` 12-hour bottom, e.g.
  `05 JUN 2026` / `08:47:03 PM`; locale-independent), `message` (static; newline
  splits the two lines, else word-wrapped, ≤40 chars), `scroll` (software
  horizontal scroll — see below), `marquee` (hardware ticker — see below),
  `spectrum` (audio analyzer — see "Spectrum analyzer" below).
- **`scroll` (software, flexible — the news-ready home).** The `message`'s two
  lines (newline-split). Each row INDEPENDENTLY picks a CONTENT SOURCE
  (`scroll_top_source` / `scroll_bottom_source` = `message` | `clock`, default
  `message`) and, for a `message` row, whether/how it scrolls:
  - `clock` source → the live TIME line (`HH:MM:SS AM/PM`), refreshed each second,
    statically aligned (date-vs-time is a future sub-choice; defaults to time).
  - `message` source → that row's text, which scrolls (`scroll_top`/`scroll_bottom`)
    in a direction (`scroll_dir_top`/`scroll_dir_bottom` = `left`/`right`) or sits
    fit/aligned. Advances per `scroll_speed_ms`, **clamped to a ~60ms floor** (each
    step redraws ~40 bytes at 9600 baud ≈ 40ms on the wire, so faster can't keep
    up). Glyph cells count as one (v0.5.3).
  - **News-ready (v0.8.0):** the `*_source` enum + per-row UI selector have room
    for a third `"news"` source — `_SCROLL_SOURCES` in `state.py` and
    `_scroll_row` in the daemon are the extension points (no schema reshape).
  - Legacy mode `"ticker"` migrates to `"scroll"`.
- **`marquee` (hardware ticker, `0x05`).** Bench: the hardware ticker scrolls the
  TOP row autonomously at a FIXED medium speed (NO speed control — the SNMetamorph
  ticker API takes no speed arg, and bench probes found none). The BOTTOM row is
  **static text only**:
  - Top = `start_ticker(marquee_text)` (`0x05` + text≤45 + `0x0D`), (re)kicked
    only when the text changes / after a reset/reconnect (re-init, then re-start).
  - **`{gN}` glyphs (v0.8.2):** the hardware ticker renders user glyphs (codes
    `0x15`–`0x1E`) in its buffer (bench-confirmed), so the daemon substitutes
    `{gN}` → glyph-code byte (`apply_glyph_placeholders`) on BOTH `marquee_text`
    (before `start_ticker`) and `marquee_bottom_text` (before `show_bottom`),
    same as message/scroll. The 45-char buffer limit is counted POST-substitution
    (each `{gN}` is one cell — consistent with v0.5.3). Glyphs are defined first
    (tick section 3, and a glyph change re-kicks the ticker) so the codes resolve;
    `status.top` substitutes too so the preview shows the glyph.
  - Bottom = `marquee_bottom_text`, written via `show_bottom` (`0x10 0x14` + 20 +
    `0x14`) once on change, WITHOUT re-sending the ticker.
  - **Clock/news bottom is IMPOSSIBLE by hardware limit (v0.8.0):** a bottom write
    that lands after the scroll resumes STOPS the top scroll — a single static
    write keeps position, but two quick writes (a per-second clock) halt it. So
    `marquee_bottom="clock"` was removed; the field is tolerated for back-compat
    but **normalized to `static`** (`state.py`). For a live clock/news ticker, use
    `scroll` with a `clock` source on a row.
  - status.json's `top` is a SOFTWARE `ticker_window` of the marquee text that
    ADVANCES every tick (a per-tick offset counter in `ctx`), so the preview
    scrolls (a coarse approximation of the unreadable hardware speed — it just
    MOVES); `bottom` is the rendered static bottom.
- **Per-line justify:** `align_top` / `align_bottom` (`left`/`center`/`right`,
  default `center`) independently justify line 1 / line 2. Applied at the
  `render_lines` fit step on RENDERED cells (a `{gN}` glyph counts as one cell);
  the daemon coerces an invalid value to `center`. A scrolling row ignores its
  align (the window is already 20 cells wide). In **marquee** mode the top row is
  the hardware ticker (it controls its own layout), so the UI HIDES the Line 1
  justify control; Line 2 justify still applies to the static bottom.
- **Animations** (4): `none` (show when changed); `flash` (alternate frame /
  real `blank()` — display goes fully DARK); `blink` (2-state brightness snap —
  the frame stays up but dims to MIN on the off-phase); `pulse` (a stepped
  **triangle-wave brightness sweep** `0→1→2→3→2→1→…` — a breathing effect that
  OVERRIDES the static brightness while active). `flash`/`blink` are timed by
  `animation_params.on_ms`/`off_ms`; `pulse` by `animation_params.step_ms`
  (default 200 → ~1.2 s full sweep). blink/pulse fold into the brightness step
  (no frame redraw). The daemon writes the on-glass result to status.json each
  tick (blank top/bottom for flash-off, the applied `brightness` for blink/pulse),
  so the preview animates all of them with no preview-side change. **N/A in
  marquee (v0.8.1):** the hardware ticker owns the top row, so the daemon forces
  `animation = "none"` on the marquee path (a leftover setting from another mode
  can't blank/pulse it) and the UI hides the Animation control in marquee.
  > **invert** was intentionally NOT added: a character VFD with 9 glyph slots
  > can't do a true per-pixel invert for arbitrary text, and a flooded
  > approximation would just look like a worse flash.

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
  (`daemon_alive` = status.json fresh < 5s), the library endpoints (below),
  `/` serves the built UI (`ui/dist`).
- **Polling (v0.8.3):** the UI hot-polls ONLY `GET /api/status` (~500ms, for
  clock/marquee motion). `daemon_alive` is DERIVED client-side from that status's
  freshness (`aliveFromStatus` in `stores.ts`: `alive` && `updated_at` < 5s old —
  the same rule as `/api/health`), so there's no redundant health hot-poll. The
  `/api/health` endpoint stays for external checks. Run uvicorn with
  `--no-access-log` so the 2×/s status poll doesn't flood the console.
- **Preview mirrors status, not controls.** `VfdPreview` renders a pixel-accurate
  2×20 of 5×7 phosphor dots from `/api/status`, so it shows real clock ticks /
  ticker motion / brightness / blank. Built-in 5×7 font for ASCII; the 9 user
  glyph codes render from `state.glyphs` via the shared low-5-bit convention. The
  preview box is a **fixed 2×20 aspect** (locked on the canvas), so it never
  resizes as status updates or modes switch — no layout jump (v0.8.2).
- **Controls** (`PUT /api/state` on change): mode, message (+`{gN}` hint),
  brightness, blank, hardware scroll, code page, animation (+on/off ms), ticker
  speed. `CommandBar` fires self_test/reset; `StatusReadout` shows daemon health.
- **Layout (v0.8.0, panels v0.8.1):** two columns, each its OWN flex stack so they
  size INDEPENDENTLY (v0.8.2 fix: a prior 2-row grid let the tall right column span
  both left rows and inject dead space under the fixed-size preview). LEFT
  (`layout__left`) = header/preview, Glyph Editor, Glyph Library. RIGHT = Control,
  Display, Saved Messages, Commands, Daemon. The masthead's meta text is
  baseline-aligned to the logo.
  - **Control** = PER-MODE only: mode selector, the per-mode inputs (message /
    marquee text+tip / scroll per-row source+scroll+dir+speed), Justify (where
    applicable), and Animation (hidden in marquee).
  - **Display** (`DisplayPanel.svelte`, v0.8.1) = MODE-AGNOSTIC device settings
    that apply regardless of mode: brightness (4-stop slider), Blank, HW scroll,
    Code page. Split out of Control to declutter; same state fields + same
    optimistic/debounced `PUT /api/state` (a pure relocation, no schema change).
  - **Commands** = fire-once actions (self_test/reset); **Daemon** = status.
  - **Mobile (≤860px, v0.8.3):** single column; `layout__left` flattens via
    `display: contents` and `order` puts CONTROLS right after the preview
    (preview → controls → glyph editor+library), since controls are primary.
- **Config:** `CHECKOUT_STATE_PATH` / `CHECKOUT_STATUS_PATH` (shared with daemon)
  via `checkout.config`; `CHECKOUT_UI_DIST` for the built UI. Docker is Phase 3.

See `web/README.md` and `ui/README.md` for run instructions.

## Phase 2c — glyph editor (v0.5.0)
The `GlyphEditorPanel` is now a real 9-slot 5×7 glyph editor, using the existing
`state.glyphs` contract (no schema/endpoint changes):

- **Slot strip:** 9 thumbnails (g0–g8) rendered through the SAME dot-draw as the
  main preview (`dotrender.paintCell` + `font5x7` decode), so a glyph looks
  identical everywhere. Selected slot highlighted; a per-slot sync dot.
- **Draw grid:** a 5×7 canvas (`GlyphCanvas.svelte`) with click + **click-drag
  paint** (pointer events, mouse + touch). The first cell sets the paint value
  (lit → erase, empty → paint); dragging applies it. Lit cells are phosphor
  squares, empty cells faint — matching the preview.
- **Tools:** **Clear**, and **copy-from-character** — type any printable char to
  seed the grid from the REAL `font5x7` bitmap, then tweak. Plus the `{gN}`
  reference token for the selected slot with a one-click copy.
- **Debounced auto-push:** an edit updates local state instantly (slot strip +
  main preview reflect it — optimistic via `setGlyphLocal`), then ~400 ms after
  the last edit a single `PUT /api/state` sends `{glyphs:{"<slot>":[7 ints]}}`
  (`pushGlyphs`). The backend deep-merges one slot (`merge_patch`) without
  touching the others; the daemon defines it on the display next tick (the v0.3.1
  glyph path). Never push per-toggle — the debounce is the contract. A per-slot
  indicator shows syncing… / synced ✓.
- **Encoding** is the shared low-5-bit convention (`glyphedit.ts`: `withBit` /
  `copyFromChar` / `normGlyph`), so what you draw is exactly what the daemon
  defines and what the preview decodes — one round-trip, verified by test.

## Phase 2d — saved library (v0.7.0)
A persistent library of saved **messages** and **glyphs**, **web-owned** in
`library.json` (env `CHECKOUT_LIBRARY_PATH`, default `./library.json`). The
**daemon NEVER reads it** — recalling an item writes `state.json` via the normal
path, which the daemon already consumes. `web/library.py` does atomic writes
(reusing `checkout.state.atomic_write_json`); validation caps each list at 200.

- **Schema:** `{ "messages": [{id,name,message,mode,align_top,align_bottom,
  brightness,glyphs}], "glyphs": [{id,name,rows}] }`. A saved message carries the
  `glyphs` it references, so recalling it lights up its `{gN}` refs.
- **Endpoints:** `GET /api/library`; `POST /api/library/messages`
  (saves the current composable state) / `DELETE …/{id}` /
  `POST …/{id}/recall` (the one bridge library→live: PUTs the message's fields +
  glyphs into `state.json`); `POST /api/library/glyphs` {name,rows} /
  `DELETE …/{id}`.
- **9 slots vs the library:** the **9 glyph slots** are the live hardware
  registers the daemon defines; the **library** is unlimited saved bitmaps you
  *load into* a slot. Loading a saved glyph routes through the same optimistic +
  debounced push as drawing (`commitGlyph`).
- **UI:** `SavedMessages` (save current / recall / delete) and `GlyphLibrary`
  (save selected slot / load / reorder / delete, mini phosphor thumbnails via the
  shared dot-render). The selected editor slot is a shared store
  (`selectedGlyphSlot`) so the library targets it.
- **Drag-and-drop (v0.7.1; cross-component fix v0.8.3):** drag a library glyph
  **onto a slot** (g0–g8) to load it there (the slot highlights on drag-over and
  becomes selected on drop); drag a glyph **within the library** to reorder
  (persisted via `POST /api/library/glyphs/order`, optimistic with revert). The
  library→slot drop spans two components, so it uses a shared `draggedGlyph` store
  (set on dragstart, cleared on dragend) as the reliable "what's being dragged"
  signal — the slot's `dragover` calls `preventDefault()` whenever that store is
  set (NOT gated only on `dataTransfer.types`, whose custom-MIME visibility during
  dragover is browser-dependent; without `preventDefault` the browser silently
  drops the `drop` event), and the drop reads `dataTransfer` first then the store
  as fallback. HTML5 DnD doesn't fire on touch, so the **click/tap fallback** loads
  a glyph into the selected slot (cards are keyboard-activatable `role="button"`).
  Pure DnD logic lives in `dnd.ts` (`reorderIds` / `rowsForGlyphId` /
  `resolveGlyphDrop`), test-covered.

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

## Phase 3a — spectrum analyzer (v0.9.0)
A crude real-time audio spectrum analyzer (mode `spectrum`): 20 frequency bars,
double-height (up to 14 levels over 2 rows), ~21fps. THREE processes cooperate,
each single-purpose; the daemon stays the sole serial owner:

```
audioviz (capture+FFT) --unix DGRAM socket (20 heights)--> daemon --> VFD
   ^ reads audio_* from state.json                          ^ writes status.bars
```

- **`checkout.audioviz`** (separate process, never opens the port). Hann-windows
  → numpy rFFT → 20 LOG-spaced bands → **auto-gained** heights 0..14, with
  **attack-fast/release-slow** smoothing (`out = max(new, prev*decay)`). SETTINGS
  via `state.json`: `audio_source` (`mic` | `system`), `audio_device`,
  `audio_gain` (now **sensitivity**), `audio_decay` (re-read live; a source/device
  change restarts the capture). Capture only runs while mode is `spectrum`.
  - **Auto-gain (v0.9.2, reworked v0.9.3/.4) — volume-independent.** The monitor
    is captured POST-volume, so the display must not track absolute level. The
    reference is an ENVELOPE FOLLOWER (`update_ref`) of **broadband loudness**:
    its target is `band_mean` (the MEAN band magnitude — "how loud overall now"),
    NOT a per-band percentile/max (which equals the loudest bands, so "at ref →
    top" then dumped the median-and-below to the floor — bars "filled then sank",
    v0.9.4). It RISES toward the level by `(peak-ref)*AUTOGAIN_ATTACK` (smooth,
    ~0.4 — not an instant snap, which pumped) and RELEASES by `*AUTOGAIN_RELEASE`
    (0.95 — fast enough to recover). `normalize_levels` is **centered with
    headroom**: `db_rel = 20*log10(band/ref)` maps over `[-AUTOGAIN_RANGE_DB(24),
    +AUTOGAIN_HEADROOM_DB(9)]` → `[0, MAX_BAR]`, so a band AT ref lands mid-high
    (~range/(range+headroom)·MAX ≈ 10/14), louder bands have headroom to the top,
    quieter bands spread DOWN — typical music fills ACROSS the display instead of
    collapsing. `sensitivity` biases it; bar heights are then smoothed by
    `decay_levels` (attack-fast/release-slow, prev persists across frames — the
    anti-flash). **Smoothing (`audio_decay`) is a purely VISUAL feel control**
    (UI slider `0..0.98`: 0 = snappy/instant fall, no smoothing; higher = bars
    fall more slowly / less twitch) — it is SEPARATE from pipeline latency (the
    small constant offset is structural FFT-window + monitor-tap delay, left
    alone). Lowering system volume does NOT shrink the bars: `ref` tracks the
    signal, so level cancels — which REQUIRES `REF_FLOOR` (1e-4) BELOW quiet-music
    levels. The SILENCE GATE (`signal_rms` < `SILENCE_FLOOR_RMS`), NOT the floor,
    is what stops noise amplification (below it → 0 + `ref` releases). Constants in
    `spectrum.py` with a tuning guide — bars SINK → ref must be `band_mean` +
    release fast enough; too short → lower `RANGE_DB` / raise `HEADROOM_DB`; clip
    at top → raise `RANGE_DB` / lower `HEADROOM_DB`; flashing → lower
    `AUTOGAIN_ATTACK` / raise decay; volume leaks → lower `REF_FLOOR`.
  - **Two capture backends (v0.9.1; tool priority fixed v0.9.5).** PortAudio's
    ALSA backend does NOT expose PipeWire/Pulse `.monitor` sources, so audio is
    captured NATIVELY via a **`parec`** (preferred) / `pw-record` (fallback)
    subprocess reading raw s16le PCM (`ParecCapture` + reader thread; `_read_exact`
    accumulates partial pipe reads). **parec is preferred because `pw-record`/
    `pw-cat`, piped, deliver ONE good buffer from a `.monitor` then STARVE to
    near-silence** (RMS ~0.00003; bench-proven v0.9.5) — the real cause of the
    spectrum "fills then dies", NOT the DSP. `parec --device=<src> --format=s16le
    …` sustains (RMS ~0.2). **parec MUST also pass `--latency-msec`
    (`PAREC_LATENCY_MS`=20)** or it BLOCK-BUFFERS ~750ms and dumps audio in bursts
    (bench v0.9.6: gaps ~21ms with the flag vs up to ~2000ms without) — that
    burst-buffering was the pop-to-top / fall-to-zero PUMP + 1-2s delay behind the
    whole spectrum-tuning saga. **Tuned defaults (v1.0.0):** `PAREC_LATENCY_MS`=10
    (was 20 — tighter) and `BLOCK`=256 samples (was 1024 — smaller FFT frame =
    tighter timing, acceptable bass resolution); both tunable. Both `system` (a
    monitor) and `mic` (an input
    source) go through this; `sounddevice`/PortAudio (`SoundDeviceCapture`) is the FALLBACK
    when Pulse is absent. `select_capture`: system → the monitor (device override →
    default-sink monitor → first), else None = emit zeros (NEVER the mic); mic →
    the Pulse input (default-source) or the PortAudio fallback.
  - **Hardened restart (v0.9.1).** Switching devices used to segfault PortAudio.
    Now `SoundDeviceCapture.stop()` nulls the handle then `stop()` THEN `close()`
    (guarded); a `ChangeDebouncer` coalesces rapid switches (~400ms → one
    restart); `_restart_capture` tears down the old capture and wraps `start()` in
    try/except (a failed open → zeros, never a crash).
  - **Minimal device list (v0.9.2).** `build_device_list` uses PULSE sources —
    the REAL devices: the handful of `.monitor` outputs + real input sources, each
    labeled by its Pulse Description ("Monitor of <sink>" / the input name). The
    raw ALSA/PortAudio plugin junk (hw:*, rate converters, per-app streams) never
    appears (~5 entries vs ~25). PortAudio inputs are the fallback only when
    `pactl` is absent. `devices.json` carries `default_monitor` + `default_source`
    (web `/api/devices`, `--list`); the UI filters by source and defaults to Auto.
  - **System packages (Arch):** `pipewire-pulse` (`pactl`/`pw-record`),
    `portaudio` (mic fallback / `sounddevice`).
- **Socket protocol.** A unix **DATAGRAM** socket (`config.SPECTRUM_SOCKET`,
  default `$XDG_RUNTIME_DIR/checkout-spectrum.sock`). Each datagram is a fixed
  **20-byte** frame, one byte per bar (height 0..14). `SOCK_DGRAM` = newest-frame-
  wins: the daemon **drains to the LATEST** datagram each loop (discards stale),
  so a slow reader can't back up a stream and there's no filesystem churn / tear.
  The HEAVY per-frame data goes here; only settings go via `state.json`.
- **Daemon spectrum path** (in the fast loop). On ENTER: define the **7 height-
  glyphs for the active style** (slots 0..6 via `spectrum.style_glyphs(style)`;
  this OVERWRITES those user-glyph slots), re-init, lazily bind the socket. Each
  iteration: drain → latest 20 heights (or **decay toward 0** if no datagram
  within `SPECTRUM_STALE_MS` — don't freeze) → render via the style's cell mapping
  → emit-diff a full `show()` (~21fps, paced by the serial write). On LEAVE:
  re-apply `state.glyphs` (RESTORE the user's glyphs the bars overwrote); glyph
  re-apply is skipped while in spectrum. Animation is forced `none`. `status.bars`
  carries the 20 heights and `status.spectrum_style` the style (throttled) so the
  preview renders the right analyzer style.
- **Render style (`spectrum_style`, v1.1.0): bars | line.** Two swappable 7-glyph
  sets in the SAME slots 0..6, picked by `spectrum_style` (UI toggle, default
  `bars`). **bars** = filled double-height columns (`bar_glyph(h)` lights the
  bottom `h` rows; `bar_to_cells` keeps the bottom cell full while the top fills
  8..14). **line** = ONLY the peak row lit per band: `line_glyph(h)` lights
  exactly one row (`r == GLYPH_ROWS-h`, same anchoring as bars so heights line
  up), and `line_to_cells` puts the line in the bottom cell for 1..7 then **empties
  the bottom** once the peak rides into the top cell (8..14) — nothing lit below
  the line (the contrast with bars). On a live style change mid-spectrum the daemon
  redefines the 7 slots (`_define_spectrum_glyphs`: `style_glyphs` →
  `define_character`×7 → re-init → invalidate caches), tracked in
  `ctx["spectrum_style"]` so it only redefines on an actual change. This **style +
  swappable-glyph-set seam** (`SPECTRUM_STYLES` / `style_glyphs`) is the pattern
  the stereo modes reuse.
- **Stereo layouts (`spectrum_layout`, v1.2.0): full | stereo_v | stereo_h.** A UI
  toggle (default `full`). The Bars/Line style applies ACROSS all layouts; columns
  (the 5-per-cell h-resolution) apply only to stereo_h (stereo_v is inherently 7
  vertical row-levels per cell).
  - **`full`** — the original: mono `(L+R)/2` → 20 bands, double-height, both rows
    one spectrum. Unchanged.
  - **`stereo_v`** — top row = LEFT, bottom = RIGHT; each a **19-band** spectrum
    ONE cell tall (7 row-levels). Cell 0 of each row is an **inverted L/R label**
    glyph. `render_stereo_v` → `[Llabel] + 19 _v_cell` (a `bar_glyph`/`line_glyph`
    per height in slots 0..6) / `[Rlabel] + 19`.
  - **`stereo_h`** — top = LEFT, bottom = RIGHT; cell 0 = label, cells 1..19 = ONE
    horizontal LEVEL meter per channel at **FINE resolution**: 19 cells × 5 dot-
    columns = **95 steps** (level 0..95), growing column-by-column. **Bars**: full
    cells (`col_glyph(5)`) below the level + one partial leading cell
    (`col_glyph(1..4)`), empty beyond. **Line**: only the single leading-edge COLUMN
    lit (`vline_glyph(c)`) — a dot gliding the 95 columns. `render_stereo_h`.
  - **Stereo CAPTURE (audioviz):** parec is now ALWAYS `--channels=2`; the reader
    DEINTERLEAVES s16le (L,R,L,R…) and keeps L/R separate. `full` derives mono =
    `(L+R)/2` (one capture path); `stereo_v` FFTs each channel → 19 bands;
    `stereo_h` takes one broadband RMS level per channel scaled to 0..95. The mic
    (mono) feeds L==R.
  - **SHARED auto-gain (deliberate):** L and R normalize against ONE reference
    (the broadband loudness of BOTH channels), NOT independent per-channel gain —
    so a louder channel reads visibly louder and you can SEE the stereo balance.
    (Independent gain would hide balance; flip the shared-ref target to change it.)
  - **Tagged socket protocol:** every datagram is now `byte 0 = layout tag` + a
    payload whose shape depends on the tag — `full`→20 heights, `stereo_v`→19+19,
    `stereo_h`→2 levels. `encode_full`/`encode_stereo_v`/`encode_stereo_h` (+ an
    `encode_frame(layout, **data)` dispatcher); `decode_frame` returns a dict
    `{"layout", …}` or **None** on a wrong-length / unknown-tag / mid-switch frame
    (the daemon ignores it — never crashes). audioviz sends the frame for the
    layout it reads from `state.json`; the daemon only consumes a frame whose
    layout matches the active one.
  - **Glyph budget per (layout, style)** — `layout_glyphs(layout, style)`, defined
    on entry and redefined on a layout OR style change (same invalidate-on-change
    pattern, keyed `ctx["spectrum_glyphs_key"]`): `full` = 7 height glyphs (0..6);
    `stereo_v` = 7 height + L + R labels = **9 (exact fit)**; `stereo_h` = 5 column
    glyphs (col-fill for bars / single-column for line) + L + R = 7. The L/R label
    glyphs (`label_glyph` → `LABEL_L`/`LABEL_R`, the user's custom hand-designed
    INVERTED bitmaps — lit frame, dark letter cut out, v1.2.1) keep cell 0 reading
    as a label. The preview (`spectrumbars.ts`) keeps a matching copy.
- **Bench-locked params (do NOT retune):** 9600 baud is the hard cap; ~21fps
  full-frame is the ceiling and looks good; double-height over 7 partial-height
  glyphs reads clean; bar height 0..14 → bottom cell 1..7 then top cell 8..14;
  `bar_glyph(h)` lights rows `r >= 7-h` full width (`0x1F`), driver `(row&0x1F)<<3`.
- **Run:** `pip install -r requirements-audio.txt` then `python -m checkout.audioviz`
  (and set mode `spectrum`). The 5×7 preview draws every layout directly from
  status (it can't read the hardware glyphs) via `spectrumbars.ts`
  (`spectrumStatusCells` → bars/line for full, per-channel cells + inverted L/R
  labels + 95-column h-res for the stereo layouts).

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
uvicorn web.app:app --port 8000 --no-access-log   # serves UI + /api; shares state/status json
# dev: `uvicorn web.app:app --reload --no-access-log` + `cd ui && npm run dev` (vite proxies /api)
# --no-access-log: the UI polls /api/status ~2x/s; skip per-request 200 spam (errors/warnings still show)

# Spectrum analyzer (Phase 3a) — separate process, never opens the port
pip install -r requirements-audio.txt   # numpy + sounddevice (PortAudio)
python -m checkout.audioviz --list      # enumerate input devices -> devices.json
python -m checkout.audioviz             # capture + stream bars to the daemon (set mode "spectrum")
```
Env overrides: `CHECKOUT_PORT`, `CHECKOUT_BAUD`, `CHECKOUT_LOOP_HZ`,
`CHECKOUT_STATUS_HZ`, `CHECKOUT_STATE_PATH`, `CHECKOUT_STATUS_PATH`,
`CHECKOUT_LIBRARY_PATH` (web-only), `CHECKOUT_UI_DIST`, `CHECKOUT_SPECTRUM_SOCK`,
`CHECKOUT_DEVICES_PATH` (audioviz). `CHECKOUT_TICK_MS` is legacy (the loop now
uses `LOOP_HZ`; kept for `--once`).

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
- **Phase 2c (v0.5.0):** the glyph editor — 9-slot 5×7 draw grid with click-drag
  paint, slot strip (shared dot-render), debounced auto-push to `state.glyphs`,
  clear + copy-from-character (seed from the real font). (done)
- **Phase 2d (v0.7.0):** saved library (`library.json`, web-owned) of messages +
  glyphs with CRUD/recall endpoints + UI panels; `blink` reworked to a brightness
  pulse (distinct from `flash`'s blank). (done)
- **Phase 3a (v0.9.0):** single fast daemon loop (emit-diffed, mtime-gated state,
  throttled status); `spectrum` audio analyzer — `audioviz` process (capture+FFT+
  20 log-bands+decay) streaming 20 bar heights to the daemon over a unix datagram
  socket; double-height bars via 7 height-glyphs (user glyphs restore on exit);
  preview renders the bars. (done)
- **v1.0.0:** serial writes drain to the wire (`tcdrain`) — paces the daemon to
  9600 baud so the OS TX buffer can't backlog (the spectrum latency-drift fix);
  tuned spectrum defaults (`PAREC_LATENCY_MS`=10, `BLOCK`=256). (done)
- **v1.0.1:** Smoothing slider reaches 0 (full snappy↔smooth range). (done)
- **v1.1.0:** spectrum `bars`|`line` style toggle (swappable 7-glyph sets) — sets
  up the style/glyph-swap pattern for the upcoming stereo modes. (done)
- **v1.2.0:** stereo spectrum layouts (`full`|`stereo_v`|`stereo_h`) — stereo
  capture + per-channel DSP (shared auto-gain), tagged socket protocol, L/R label
  + column glyphs, two stereo renderers, UI toggle + preview. (done)
- **v1.2.1:** custom inverted L/R label bitmaps; audio sliders share the
  Brightness slider styling (global `.phosphor-slider`). (done)
- **Phase 3:** more frames + rotation.
- Brightness byte first confirmed in v0.1.1 (then thought to be two levels:
  dim/bright; superseded by the four-level finding in v0.6.2).
- **v0.2.0:** adopted the authoritative Futaba M202MD10C command set + extended-mode
  init sequence — all 40 cells now writable, the old 39-cell/scroll workarounds removed.
  Vertical scroll exposed as a controllable feature.
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
- **v0.4.5–v0.4.8:** preview polish — square dots (rounded), tighter intra-cell
  dot pitch (denser glyphs, character spacing unchanged), final `DOT_PITCH_X` 5.8.
- **v0.5.0:** the glyph editor (Phase 2c) — `GlyphCanvas` draw grid + slot strip
  on a shared `dotrender.paintCell`, `glyphedit.ts` low-5-bit encode, debounced
  auto-push (`setGlyphLocal` + `pushGlyphs`). VfdPreview refactored onto the same
  `paintCell` so editor and preview render identically.
- **v0.5.1–v0.5.3:** message textarea (Enter = line break) + per-line 20-char
  budget; status heartbeat every tick (alive in static modes); `{gN}` counted/fit
  as one cell (fixed glyph-codes-as-whitespace dropping slots 6–8).
- **v0.6.0:** independent per-line justification — `align_top` / `align_bottom`
  (`left`/`center`/`right`) wired through `render_lines`, with per-line LEFT/
  CENTER/RIGHT controls in the UI.
- **v0.6.1:** clock format `DD MON YYYY` / `HH:MM:SS AM/PM` (12-hour,
  locale-independent month abbreviations).
- **v0.6.2:** FOUR brightness levels (`0x04` + `0x20`/`0x40`/`0x60`/`0xFF`),
  bench-confirmed under extended mode. `state.brightness` is now an int 0..3
  (legacy `"dim"`/`"bright"` migrate to 0/3 and self-heal on load); UI 4-stop
  slider; preview renders 4 phosphor intensities.
- **v0.6.3:** header is the phosphor-tinted logo (CSS mask) + dynamic version
  from package.json.
- **v0.7.0:** saved message/glyph library (`web/library.py` + `library.json`,
  web-owned; daemon untouched) with CRUD + recall endpoints and `SavedMessages` /
  `GlyphLibrary` UI panels; `blink` is now a brightness pulse (dims to MIN on the
  off-phase) — clearly distinct from `flash`'s hard blank, and the preview
  animates both via status.
- **v0.7.1:** drag-and-drop glyph library — drag a glyph onto a slot to load it,
  drag within the library to reorder (`/api/library/glyphs/order`); removed the
  `→gN` buttons; click/tap fallback keeps it touch/keyboard-reachable.
- **v0.7.2:** `pulse` animation — a stepped triangle-wave brightness sweep
  (`0→3→0`, `animation_params.step_ms`) that breathes through the 4 levels;
  PULSE added to the animation control. invert intentionally omitted (hardware
  can't per-pixel invert arbitrary text).
- **v0.7.3:** two scrolling systems — `marquee` (hardware ticker `0x05`, top-only
  autonomous + FIXED speed, free static/clock bottom via `show_bottom`) and
  `scroll` (software, 2-line per-row direction + speed with a ~60ms floor;
  renamed from `ticker`, legacy migrates). Driver `start_ticker`/`show_bottom`;
  bench-confirmed fixed ticker speed + independent bottom row.
- **v0.8.0:** marquee/scroll UX honesty pass. **marquee** bottom is now STATIC
  TEXT ONLY — a live clock/news bottom is impossible (a per-second bottom write
  stops the hardware scroll), so `marquee_bottom="clock"` was removed (tolerated +
  normalized to `static`); added a constraints tip, hid the top-line justify, and
  the preview top now ADVANCES every tick (per-tick offset) so it scrolls.
  **scroll** is the flexible, news-ready home: per-row content source
  (`scroll_{top,bottom}_source` = `message`|`clock`, with a clear `news` extension
  point), per-row scroll/dir/speed kept, and the over-budget char warning removed
  in SCROLL (MESSAGE still warns). Layout: daemon status moved to the right column
  under Commands; masthead meta baseline-aligned to the logo.
- **v0.8.1:** declutter — split the mode-agnostic device settings (brightness,
  Blank, HW scroll, code page) out of Control into a new `DisplayPanel.svelte`
  (right-column order Control, Display, Saved Messages, Commands, Daemon). Control
  is now per-mode only. Animation is hidden in marquee mode and the daemon forces
  `"none"` there so a leftover animation can't affect the ticker. UI-only relocation
  (no state/daemon schema change beyond the marquee animation guard).
- **v0.8.2:** two fixes. (a) **marquee `{gN}` glyphs** — the hardware ticker renders
  user glyphs, but marquee sent the raw text so `{gN}` scrolled literally; the daemon
  now substitutes `{gN}`→glyph-code on `marquee_text` (before `start_ticker`) and
  `marquee_bottom_text`, with the 45-char limit counted post-substitution, and
  `status.top` substitutes so the preview shows the glyph. (b) **preview layout
  stability** — the two columns are now independent flex stacks (`layout__left`),
  removing the dead gap the old row-spanning grid injected under the fixed-size
  preview; the preview keeps a constant 2×20 aspect across mode/status changes.
- **v0.8.3:** three fixes. (a) **library→slot drag-drop** — dragging a library
  glyph onto an editor slot did nothing on desktop; the slot's `dragover` now
  `preventDefault()`s based on a shared `draggedGlyph` store (set on dragstart) so
  the `drop` fires reliably across components (custom-MIME visibility during
  dragover is browser-dependent), and the drop reads `dataTransfer` then the store.
  (b) **polling consolidated** — dropped the redundant `/api/health` hot-poll;
  `daemon_alive` is derived from `/api/status` freshness (`aliveFromStatus`),
  halving request volume; documented `uvicorn --no-access-log`. (c) **mobile
  order** — controls now sit directly under the preview on narrow screens.
- **v0.9.0:** audio **spectrum** analyzer + daemon loop refactor. The daemon is
  now ONE fast loop (~30Hz): mtime-gated state re-parse, emit-diffed serial
  writes, elapsed-time per-mode timing, throttled status — normal modes behave
  identically, spectrum gets its frame rate, no mode-transition seam. New
  `audioviz` process captures audio (mic / PipeWire-Pulse system monitor), FFTs,
  buckets into 20 log bands, decays (attack-fast/release-slow), and streams 20
  bar heights to the daemon over a unix datagram socket (newest-frame-wins,
  20-byte frames; settings via `state.json`, heavy data via the socket). Mode
  `spectrum` defines 7 height-glyphs and renders double-height bars at ~21fps,
  decays on stale, and restores the user's glyph slots on exit; the preview draws
  the bars from `status.bars`. UI gains a SPECTRUM mode with source/device/gain/
  decay controls (`/api/devices` ← `devices.json`).
- **v0.9.1:** two real-machine (Arch/PipeWire) audioviz fixes. (a) **segfault on
  device switch** — the PortAudio (mic) restart now fully tears down (null handle
  → `stop()` THEN `close()`, guarded), debounces rapid switches (~400ms → one
  restart), and catches a failed open (→ zeros, no crash). (b) **system monitor
  not found** — PortAudio can't see PipeWire `.monitor` sources, so system audio
  is now captured natively via `pw-record`/`parec` on the monitor (enumerated via
  `pactl`; default = default-sink `.monitor`); `select_capture` never silently
  uses the mic for `system`. The device list is labeled (monitors vs inputs) and
  the UI filters it by source. Bench-validated: system + monitor + playback →
  non-zero bars; cycling devices no longer crashes.
- **v0.9.2:** spectrum "just works" regardless of volume. (a) **Auto-gain** —
  bars normalize against a decaying-max reference of recent loudness
  (`update_ref`/`normalize_levels`), so they're CONTENT-driven, not volume-driven
  (turn the system volume down, bars stay full). A **silence floor**
  (`signal_rms` < `SILENCE_FLOOR_RMS`) lets them fall flat without amplifying
  hiss, and the reference doesn't ratchet up on silence. The gain slider is now
  **Sensitivity** (biases auto-gain). (b) **Minimal device picker** — the dropdown
  lists only the real Pulse monitors/inputs (labeled), auto-picking the
  default-sink monitor / default source; the raw ALSA/hw/plugin junk is gone
  (~5 vs ~25 entries). Mic now also captures via `pw-record` (PortAudio fallback).
- **v0.9.3:** auto-gain envelope fixes (confirmed on glass). (1) `REF_FLOOR`
  1e-2 → **1e-4** so it sits below quiet-music levels — it was pinning the
  reference at low volume, so volume still shrank the bars (it's now a pure
  divide-by-zero epsilon; the RMS silence gate handles noise). (2) the reference
  tracks `percentile_peak` (~85th) instead of the single loudest band, and
  `AUTOGAIN_RANGE_DB` 42 → **28**, so the spectrum fills instead of one bass band
  pinning the top. (3) `update_ref` is now an **envelope follower** (smooth
  `AUTOGAIN_ATTACK` rise, not an instant snap) so transients don't pump the whole
  display; the bar-height `decay_levels` smoothing is confirmed wired (prev
  persists). Constants carry a tuning guide.
- **v0.9.4:** auto-gain "fills then sinks" fix. v0.9.3's reference tracked an
  85th-percentile of the frame's bands (= the loudest ~15%), and `normalize_levels`
  mapped "at ref → top", so only the loudest bands could reach the top and the
  median-and-below collapsed (and on init `ref` starts tiny, so all clamp to top
  then sink as it rises). Now the reference is `band_mean` (broadband MEAN
  loudness, not a per-band percentile), and `normalize_levels` is **centered with
  headroom** (a band at ref → mid-high, louder → top, quieter → down), so typical
  music SPREADS across the display and is stable. `AUTOGAIN_RELEASE` 0.99 → **0.95**
  (recovers in ~0.5-1s). Sim: pink-ish broadband → max 14 / median ~9 / all 20
  bands lit, stable (no sink), volume-independent.
- **v0.9.5:** the ACTUAL "fills then dies" root cause — capture, not DSP.
  `pw-record`/`pw-cat` piped from a `.monitor` deliver one good buffer then STARVE
  to near-silence (RMS 0.00769 → 0.00003…, bench-proven with a bare pipe);
  `parec --device=<src> --format=s16le …` sustains (RMS ~0.23). `_capture_tool()`
  now PREFERS parec (was pw-record), pw-record kept as fallback. Reverses the
  v0.9.1 guess that "parec emits nothing" (that was a bad invocation). The
  v0.9.2–v0.9.4 DSP was correct, just starved.
- **v0.9.6:** the FINAL spectrum root cause (ends the saga) — parec was
  BLOCK-BUFFERING. Bench (a bare pipe): without a latency hint parec dumps ~30
  chunks at ~0ms apart then a ~760ms (up to ~2000ms) gap, repeating — a ~750ms
  buffer in bursts, which the daemon saw as the pop-to-top / fall-to-zero PUMP
  plus a 1-2s delay. `parec_command` now passes `--latency-msec=20`
  (`PAREC_LATENCY_MS`) → steady ~21ms gaps (max 31ms, zero >100ms). Confirmed on
  glass: bars bounce smoothly with music, no pump, no delay. The DSP was right
  all along — it was being fed bursts.
- **v1.0.0:** the LAST spectrum-latency root cause — the SERIAL TX BUFFER backing
  up. The daemon renders spectrum at `LOOP_HZ` (~30fps) and `show()` → `_write()`
  did `self._serial.write(data)` fire-and-forget into the OS TX buffer (port
  opened `timeout=0`, non-blocking). But 9600 baud only drains ~21fps, so ~9
  frames/s accumulated in the kernel buffer until full (~1-1.5s) and the glass
  always rendered frames that old — the spectrum delay that drifted in then held,
  trailing ~1-2s after the music paused. Proven: a standalone 30fps socket
  receiver tracked the music perfectly; only the serial-writing daemon lagged.
  Fix: `_write()` now calls `self._serial.flush()` (POSIX pyserial =
  `termios.tcdrain` — blocks until transmitted) AFTER each write, so the daemon
  paces to the real wire speed and NEVER queues more than the current frame —
  zero backlog by construction. Applies to ALL writes (normal modes emit-diff +
  write rarely, so the drain there is negligible — one uniform path). Also
  formalized the bench-tuned spectrum defaults: `PAREC_LATENCY_MS` 20 → **10**
  and `BLOCK` 1024 → **256** (`LOOP_HZ` stays 30 — 60 felt worse). Confirmed on
  glass: bars track the music with only the minimal fixed pipeline latency, no
  drift; pausing stops the bars within ~one frame.
- **v1.0.1:** the Smoothing slider (`audio_decay`) now reaches **0** (was floored
  at 0.5 in the UI), so the bars can do a crisp/snappy instant fall — `decay_levels`
  and the state clamp already accepted `[0, 0.999]`, only the slider blocked it.
  Purely a visual feel control, separate from pipeline latency.
- **v1.1.0:** spectrum **render style** — a `spectrum_style` toggle (`bars` |
  `line`) with two swappable 7-glyph sets in the same slots 0..6. **bars** = the
  existing filled double-height columns; **line** = only the PEAK row lit per band
  (`line_glyph` lights one row, `line_to_cells` empties the bottom cell once the
  peak rides into the top cell). The daemon redefines the 7 slots on a live style
  change (`_define_spectrum_glyphs`, tracked in `ctx["spectrum_style"]`), renders
  via the style's cell mapping, and mirrors `spectrum_style` into status so the
  preview (`spectrumbars.ts` `spectrumCells`) draws bars vs line. UI: a BARS|LINE
  segmented toggle in the spectrum controls. This establishes the style +
  swappable-glyph-set seam that the stereo modes (next release) reuse.
- **v1.2.0:** **stereo spectrum layouts** — a `spectrum_layout` toggle (`full` |
  `stereo_v` | `stereo_h`) on top of the v1.1.0 Bars/Line style. `stereo_v` = a
  19-band spectrum per channel (top=L, bottom=R, one cell tall); `stereo_h` = one
  horizontal level meter per channel at 95-column (19×5) resolution; `full` =
  the original mono double-height. Needed real changes through the stack: parec
  capture is now `--channels=2`, deinterleaved (mono = `(L+R)/2`); per-channel DSP
  (19-band / broadband-level) with a **SHARED** auto-gain reference across L/R so
  the balance is visible; a **tagged variable socket protocol** (layout byte +
  per-layout payload, `decode_frame`→dict, malformed-safe); inverted L/R label
  glyphs + column-fill / single-column glyphs; `layout_glyphs(layout,style)`
  redefined on a layout OR style change; `render_stereo_v` / `render_stereo_h`;
  a daemon layout branch + status carrying per-channel data; a UI LAYOUT toggle;
  and the preview rendering all three layouts (labels + 95-column h-res). This
  reuses (and generalizes) the v1.1.0 glyph-swap seam.
- **v1.2.1:** two polish changes. (a) the stereo L/R label glyphs are now the
  user's hand-designed inverted bitmaps (`LABEL_L`/`LABEL_R` in `spectrum.py`,
  with a matching copy in `spectrumbars.ts`) instead of the auto-generated ones —
  same slots/budgets, bitmap contents only. (b) the audio **Sensitivity** and
  **Smoothing** sliders now share the Brightness slider's track/handle styling: it
  was extracted to a global `.phosphor-slider` class (`app.css`) used by all three
  (no tick labels on the audio sliders; ranges/handlers unchanged).

## Credits / third-party
- **Command set:** [SNMetamorph/FutabaVfdM202MD10C](https://github.com/SNMetamorph/FutabaVfdM202MD10C)
  (**MIT**) — the authoritative Futaba M202MD10C command protocol. The
  extended-mode initialization (`0x00 0x01`) that resolved the vertical-scroll
  behavior, the 9 user-glyph codes (`0x15`–`0x1E`), and the brightness /
  code-page / cursor / reset commands were all derived from this library's
  published source. The extended-mode discovery is credited to `abomin` in that
  library. (See §3 in spec.md.)
- **Preview charset:** the 5×7 glyph bitmaps in `ui/src/lib/font5x7.ts` were
  extracted from the character photos in
  [Eigenbaukombinat/vfd_kassendisplay](https://github.com/Eigenbaukombinat/vfd_kassendisplay)
  (`charsetweb/cropped_<ascii>.jpg`), released into the public domain
  (**Unlicense**). Decoded by sampling each photo's 5×7 dot grid.

This project uses these projects' **published facts** — command bytes and glyph
bitmaps — each **independently bench-confirmed on our unit**. The driver and all
other code here is original Python.

## Hardware-confirm TODOs (bench)
- [x] ~~Which character code(s) render the 9 user glyphs~~ — RESOLVED (v0.3.1):
  9 non-contiguous codes `0x15`–`0x1A`, `0x1C`–`0x1E` (`0x1B` skipped); bitmap
  columns are bits 3-7. See "User glyphs" above.
- [x] ~~Whether code pages (`0x02` + page) change the glyph set~~ — RESOLVED
  (v0.3.1): yes; 12 pages, confirmed names 0–5. See "Code pages" above.
- [x] ~~Whether extended mode exposes the library's claimed 4 brightness levels~~
  — RESOLVED (v0.6.2): yes, four levels `0x20`/`0x40`/`0x60`/`0xFF` confirmed on glass.
