# spec.md — check-out (IBM VFD Status Board)

Repo: `github.com/nastronot/check-out`

A self-hosted status/news board driven by a salvaged IBM SurePOS 2x20 vacuum-fluorescent
customer display. The constraint (two lines, twenty characters) is the aesthetic — design
within it.

Version scheme: `major.minor.patch` = "big.small.bug".

---

## 1. Hardware

### 1.1 The display
- **Unit:** IBM SurePOS 500 customer display, **P/N 15K2012** (iron-gray housing).
- **VFD board:** Futaba **M202MD10C** family, 2 lines × 20 characters, blue-green VFD.
- **Cable:** IBM genuine OEM **54Y2454** (RJ-to-DB9, 1 m) — the matched SurePOS 500
  customer-display harness. Display side is the RJ jack ("port 4"); host side is DB9.

### 1.2 Electrical interface (CONFIRMED on this unit, bench-verified)
- **Data:** true **RS-232** levels, **normal polarity (inversion OFF)**. Verified — plain
  USB-RS232 FTDI adapter drives it directly, no level shifter or invert needed.
- **UART:** **9600 8N1**. Verified.
- **Power:** **12 V DC** to the display. Verified (showed a cursor/underscore on power-up).
- **Minimal connection — three wires:**
  - `VFD DATA  ← host TX` (RS-232) → **DB9 pin 3**
  - `VFD GND   ← common ground`   → **DB9 pin 5**
  - `VFD +12V  ← 12 V supply`     → **DB9 pin 8**
- The display is **write-only** in this build; host RX is unused.

### 1.3 DB9 pinout (BENCH-CONFIRMED on this exact cable)
Measured directly on the 54Y2454 via the breakout. The generic RS-232 chart is WRONG for
pins 7/8 on this powered cable — do not trust it; the measured map is:

| Pin | Measured | Use |
|-----|----------|-----|
| 1 | **+11.75 V back-feed** | **HAZARD — leave unconnected.** This is the "present"/detect line that sources voltage back out. |
| 2 | floating (noise) | unused |
| 3 | steady ~163 mV idle | **DATA** (host TX → here) |
| 4 | floating (noise) | unused |
| 5 | 0 V (ground) | **GND** |
| 6 | ground | unused (same as 5) |
| 7 | — | unused |
| 8 | +11.75 V | **+12 V power** |

Final wiring used: **pin 3 = DATA, pin 5 = GND, pin 8 = +12 V, pin 1 left open.**

### 1.4 Hazard — the "VFD present" / back-feed line
On this cable, **pin 1 sources ~12 V back through the harness** (measured). This can
destroy an adapter's TX pin. **Pin 1 is left permanently unconnected.** Only pin 3 (DATA),
pin 5 (GND), and pin 8 (+12 V) are wired.

### 1.5 Bill of materials (AS BUILT)
| Part | Role |
|------|------|
| OIKWAN USB-to-RS-232 (DB9 male, FTDI) adapter | data path → `/dev/ttyUSB0` |
| 12 V 1 A regulated supply, 5.5×2.1 mm center-positive + panel barrel jack | display power |
| 2× panel-mount DB9-female screw-terminal breakouts | one mates the cable, one mates the adapter; injector wiring between them |
| Hammond 1591C (120×80×38 mm) ABS box | enclosure |
| Inline fuse holder + 1 A fuse | on the +12 V line |
| 22 AWG stranded hookup wire | wiring |
| ~~MAX3232 module~~ | **not needed** — display takes RS-232 directly |

Build is the "injector box": cable-side breakout and adapter-side breakout, with DATA
(pin 3↔3) and GND (pin 5↔5) joined across, and +12 V (fused) injected onto cable pin 8.
All grounds (barrel −, cable pin 5, adapter pin 5) common. Cable pin 1 left open.

### 1.6 Enclosure ("tidy dongle")
One sealed box. Outside: a USB cable to the host (`arda`) and a 12 V barrel-jack input.
Inside: the USB-RS232 adapter (or FTDI+MAX3232 if the fallback is needed) wired to a
panel DB9, with 12 V routed to the display power pin and all grounds common. No exposed
boards or loose wires.

---

## 2. Bring-up procedure — COMPLETED

Result: **Case A confirmed** — RS-232, inversion OFF, 9600 8N1, 12 V power. The display
powered up on 12 V (pin 8 / GND pin 5), the back-feed line was identified as pin 1 and
left open, and `HELLO WORLD` rendered correctly over a plain USB-RS232 adapter on pin 3.
No MAX3232, no inversion, no baud sweep needed. Hardware phase done.

The original step-by-step (kept for reference): power-test first with only 12 V + GND and
the adapter disconnected; do a powered voltage survey to find the back-feed pin (the one
reading ~12 V that isn't pin 8) and the data pin (the one holding a small steady idle
voltage); only then wire the adapter to the data pin; then send text.

---

## 3. Command set — authoritative Futaba M202MD10C protocol

Single-byte control codes (NOT ESC/POS — `0x1B 0x40` printed a literal "@", so ESC-prefixed
commands do not apply). This is the authoritative command table, recovered from the
SNMetamorph `FutabaVfdM202MD10C` library source (our exact board) and bench-confirmed on this
unit. Credit the SNMetamorph library + the `abomin` "extended mode" discovery — enabling
extended mode (`0x00 0x01`) was the missing initialization that the v0.1.x findings lacked.

| Command | Bytes | Behavior |
|---------|-------|----------|
| **Extended mode** | `0x00` + `0x01` enable / `0x00` disable | required for full 40-cell, no-scroll operation |
| **Select code page** | `0x02` + page byte | 12 code pages (see §4.5 glyph contract) |
| **Define character** | `0x03` + code + 7 row bytes + `0x00` | 9 user glyphs at non-contiguous codes (see §4.5) |
| **Dimming / brightness** | `0x04` + level byte | 4 levels: `0x20`/`0x40`/`0x60`/`0xFF` (Min/Med/Med+/Max) |
| **Print ticker text** | `0x05` | hardware ticker, 45-char buffer (wire later) |
| **Backspace** | `0x08` | |
| **Self test** | `0x0F` | built-in self test |
| **Set cursor position** | `0x10` + position byte | moves cursor to absolute position |
| **Disable vertical scroll** | `0x11` | normal frame mode |
| **Enable vertical scroll** | `0x12` | writing past the end scrolls (ticker effects) |
| **Cursor on** | `0x13` | |
| **Cursor off** | `0x14` | hides cursor block (rule 1 — must be sent last) |
| **Reset** | `0x1F` | resets the display |
| **Write text** | printable ASCII | prints at cursor, cursor auto-advances |

### 3.1 Required INIT sequence (mandatory on every open/reconnect)
```
0x1F            reset
0x00 0x01       enable extended mode   <-- THIS was the missing piece
0x11            disable vertical scroll
```
Without `0x00 0x01` + `0x11` the display scrolls when the bottom-right cell is written —
that was the root cause of the v0.1.x "40th-cell scroll" workarounds. `VFDDriver.initialize()`
sends exactly these bytes from `open()` (and on every reconnect).

### 3.2 Addressing (linear)
- Top line:    positions `0x00`–`0x13` (0–19)
- Bottom line: positions `0x14`–`0x27` (20–39)
- `position = column + row * 20` (row 0 = top, row 1 = bottom)
- **ALL 40 CELLS ARE WRITABLE** once the display is initialized correctly.

> **Historical note (resolved):** earlier versions documented a "39-cell" limit, a `0x27`
> "phantom scroll", a glyph-only-anchors rule, and a "no leading clear" rule. Those were
> ALL artifacts of MISSING INITIALIZATION (extended mode never enabled, vertical scroll left
> on). With the init sequence above they no longer occur — all 40 cells hold, and a leading
> reset only matters because it drops the init state (re-init, don't avoid it).

**Behavioral rules (bench-verified — ground truth):**

1. **Cursor off must be last.** `0x14` hides the cursor, but ANY subsequent write RE-ENABLES
   it. There is no persistent "cursor off" and no separate "cursor on" byte — writing
   implicitly turns it back on. Therefore `0x14` must be the LAST byte of every frame update.

2. **Initialize before drawing.** Extended mode + scroll-off (§3.1) must be set before any
   full frame, or the display scrolls when the 40th cell is written. `open()` runs the init
   sequence; `blank()` re-asserts it so the display is never left in scroll mode.

3. **Vertical scroll is a controllable mode.** `0x12` enables it, `0x11` disables it. Normal
   frames run with it disabled; enabling it is reserved for later ticker/marquee effects.
   Exposed as `set_vertical_scroll(bool)`.

4. **Brightness is FOUR confirmed levels** (bench-confirmed under extended mode) —
   `0x04` + `0x20` Min / `0x40` Med / `0x60` Med+ / `0xFF` Max, the SNMetamorph Dimming
   enum. Applied live (no redraw). The canonical `state.brightness` is an int 0..3 (index
   into those bytes); `set_brightness(0..3)` emits the level. The earlier "two levels
   (dim/bright)" reading was an artifact of testing before extended-mode init; legacy
   `"dim"`/`"bright"` still map to 0/3.

**`show()` byte sequence (do not regress):**
```
0x10 0x00  <top: EXACTLY 20 ASCII bytes>     # cells 0x00..0x13
0x10 0x14  <bottom: EXACTLY 20 ASCII bytes>   # cells 0x14..0x27 — full 20
0x14       # cursor off — MUST be the final byte
```
Built as one buffered serial write (no flicker, cursor-off reliably last). Both lines are a
full 20 chars; overwrite-in-place. No leading clear, no `0x27` special-case, no
anchor/reposition trick — all removed now that the init sequence is correct.

**Driver primitives** wrap exactly these bytes, so the app never emits raw bytes:
- `initialize()` → `0x1F 0x00 0x01 0x11` (reset + extended mode + scroll off)
- `clear()` → `0x1F` (note: drops the init state; prefer `blank()`)
- `write_at(pos, text)` → `0x10`, `chr(pos)`, then ASCII text
- `show(top, bottom)` → the buffered sequence above (overwrite-in-place, cursor-off last)
- `set_brightness(0..3)` → `0x04` + `0x20`/`0x40`/`0x60`/`0xFF` (legacy `"dim"`/`"bright"` -> 0/3)
- `set_vertical_scroll(bool)` → `0x12` (enable) / `0x11` (disable)
- `self_test()` → `0x0F`
- `blank()` → `0x1F 0x00 0x01 0x11 0x14` (dark screen, re-initialized, no lingering cursor)

---

## 4. Software

### 4.1 Stack & placement
- Interface developed/tested on **local dev machine** first (display on `/dev/ttyUSB0`),
  then deployed to **`arda`** (Synology NAS).
- Talks to `/dev/ttyUSB*` (serial), 9600 8N1, write-only.
- Containerized (Docker) for the `arda` deployment.
- Serial port access: dev user must be in the device's group (Arch: `uucp`) or use sudo.

### 4.2 Architecture
```
data sources ──► frame builder ──► 2x20 renderer ──► serial driver ──► /dev/ttyUSB*
                                       (40-char budget, fit/scroll)
```
- **Driver layer:** opens the port (9600 8N1), runs the init sequence, and exposes
  `initialize`, `clear`, `write_at`, `show`, `set_brightness`, `set_vertical_scroll`,
  `self_test`, `blank`. Owns all command bytes. Write-only.
- **Renderer:** enforces the **2 lines × 20 chars** budget. Truncate, pad, or scroll.
  A line longer than 20 chars uses a ticker; format with spaces/newlines so each frame
  is ≤40 chars total.
- **Frame builder:** rotates through "frames" on a timer (e.g. clock → weather →
  Docker health → job/queue counts → a custom message).
- **Data sources:** pluggable. Start with clock; add others incrementally.

**Single fast loop (v0.9.0).** The daemon runs ONE fast loop (~30Hz,
`CHECKOUT_LOOP_HZ`), not a 250ms tick. Each iteration mtime-gates `state.json`
(re-parse only on change), computes the frame, and **emit-diffs** to the port
(write only when the frame changed). Emit-diffing decouples loop rate from
serial-write rate, so looping fast is free for normal modes and gives `spectrum`
its frame rate — one code path, no mode-transition seam. Per-mode timing runs off
elapsed wall-clock; `status.json` is throttled to ~`CHECKOUT_STATUS_HZ` (~6Hz).

### 4.3 Constraint-as-feature
- Hard cap: 2×20. No graphics (character cell display).
- Lean into it: rotating single-purpose frames, ticker for anything longer, blink/dim
  for emphasis. The limitation is the charm.

### 4.4 Initial frames (v0.1.x)
- Clock (date + time) — proves the full path end to end. Format (v0.6.1):
  `DD MON YYYY` top, `HH:MM:SS AM/PM` bottom.
Then iterate: weather line, Docker/container health, print-queue or job counts,
rotating short messages.

### 4.5 Phase 2 — control surface (v0.3.0)
Everything the display can do is driven by **two JSON files** with one-directional
ownership, so the daemon (sole serial-port owner) and the future web UI never race:
the **web writes `state.json`**, the **daemon writes `status.json`**. Phase 2a wires
this control surface in the daemon; Phase 2b adds the Svelte/FastAPI UI on top.

**`state.json`** (web writes, daemon reads each tick):
```jsonc
{
  "mode": "clock" | "message" | "scroll" | "marquee" | "spectrum",  // legacy "ticker" -> "scroll"
  "message": "text for message/scroll mode",
  // spectrum (mode "spectrum") SETTINGS only; live bars go over a socket, not here:
  "audio_source": "system" | "mic", "audio_device": null, "audio_gain": 1.0, "audio_decay": 0.85,
  "align_top": "left" | "center" | "right",     // line 1 justify (default center)
  "align_bottom": "left" | "center" | "right",  // line 2 justify (default center)
  "marquee_text": "...", "marquee_bottom": "static", "marquee_bottom_text": "...",  // bottom is static-only
  "scroll_top_source": "message" | "clock",      // per-row content source (news-ready)
  "scroll_bottom_source": "message" | "clock",
  "scroll_top": true, "scroll_bottom": false,
  "scroll_dir_top": "left" | "right", "scroll_dir_bottom": "left" | "right",
  "brightness": 0 | 1 | 2 | 3,  // level index (0 Min .. 3 Max); legacy "dim"/"bright" -> 0/3
  "blank": false,
  "scroll": false,                 // hardware vertical-scroll MODE (0x11/0x12); normally false
  "code_page": 0,                  // 0..11
  "scroll_speed_ms": 300,          // ticker software-scroll step
  "animation": "none" | "flash" | "blink" | "pulse",
  "animation_params": { "on_ms": 500, "off_ms": 500, "step_ms": 200 },
  "glyphs": { "0": [r0..r6], ... "8": [...] },  // optional 5x7 glyphs; 7 ints, low 5 bits = cols 1..5
  // place a glyph in `message` with {g0}..{g8}
  "command": { "id": "uuid-or-null", "action": "self_test"|"reset"|"redefine_glyphs", "args": {} },
  "updated_at": "iso"
}
```
`load_state()` backfills every missing key from defaults (nested `command` and
`animation_params` are merged, not wholesale-replaced), so a partial web write never
breaks the daemon. Atomic save (temp file + `os.replace`).

**`status.json`** (daemon writes — sole writer, web reads):
```jsonc
{ "alive": true, "mode": "...", "top": "....20....", "bottom": "....20....",
  "brightness": "...", "blank": false, "scroll": false,
  "last_command_id": "...", "updated_at": "iso" }
```
Written atomically on change. The UI uses it to mirror the real display and daemon health.

**Command nonce.** `command.id` is a nonce; the daemon runs `command.action` once per
*new* id (tracked in-memory as `last_command_id`), null id is a no-op, a repeated id is
ignored. All actions are idempotent — safe to re-run once on restart: `self_test` and
`reset` (both re-initialize the display afterward), `redefine_glyphs` (defines
`state.glyphs`, then re-initializes).

**Modes.** `clock` (top `DD MON YYYY` e.g. `05 JUN 2026`; bottom 12-hour
`HH:MM:SS AM/PM` e.g. `08:47:03 PM` — hand-formatted, locale-independent);
`message` (static — a newline splits the two lines, else greedy word-wrap, ≤40
chars); `scroll` and `marquee` (the two scrolling systems, below).

**Two scrolling systems (v0.7.3, bench-validated; refined v0.8.0).**
- **`scroll` — software, flexible (the news-ready home).** The `message`'s two lines
  (newline-split). Each row INDEPENDENTLY picks a **content source**
  (`scroll_top_source` / `scroll_bottom_source` = `message` | `clock`, default `message`;
  **news-ready** — a third `news` source slots into the enum + per-row selector without
  reshaping the schema). A `clock` row shows the live TIME line (`HH:MM:SS AM/PM`, refreshed
  each second, statically aligned; date-vs-time is a future sub-choice, defaults to time).
  A `message` row scrolls (`scroll_top`/`scroll_bottom`) in either direction
  (`scroll_dir_top`/`scroll_dir_bottom` = `left`/`right`) via `renderer.ticker_window`,
  advancing per `scroll_speed_ms` **clamped to a ~60ms floor** (a step redraws ~40 bytes
  at 9600 baud ≈ 40ms on the wire, so faster can't keep up), or sits fit/aligned; glyph
  cells count as one. Legacy mode `"ticker"` migrates to `"scroll"`.
- **`marquee` — hardware ticker (`0x05`).** Bench ground truth: the hardware ticker scrolls
  the TOP row autonomously at a FIXED medium speed (**no speed control** — the SNMetamorph
  ticker API takes no speed arg and bench probes found none). The BOTTOM row is **static
  text only** (`marquee_bottom_text`), written via `show_bottom` (`0x10 0x14` + 20 + `0x14`)
  once on change without re-kicking the ticker. **A live clock/news bottom is impossible by
  hardware limit** (v0.8.0): a bottom write that arrives after the scroll resumes STOPS the
  top scroll — one static write keeps position, but two quick writes (a per-second clock)
  halt it. So `marquee_bottom="clock"` was removed; the field is tolerated for back-compat
  but **normalized to `static`**. For a live clock/news ticker, use `scroll` (a `clock`
  source on a row). The daemon `start_ticker(marquee_text)` (`0x05` + text≤45 + `0x0D`) only
  when the text changes / after a reset. status.json's `top` is a SOFTWARE `ticker_window`
  approximation that ADVANCES every tick (a per-tick offset counter) so the preview scrolls
  (it won't match the fixed/unreadable hardware speed — it just MOVES).
  **`{gN}` glyphs (v0.8.2):** the hardware ticker renders user glyphs (codes `0x15`–`0x1E`)
  in its buffer (bench-confirmed), so the daemon substitutes `{gN}`→glyph-code on both
  `marquee_text` (before `start_ticker`) and `marquee_bottom_text` (before `show_bottom`),
  exactly like message/scroll. The 45-char buffer is counted POST-substitution (one cell per
  `{gN}`); glyphs are defined first so the codes resolve, and `status.top` substitutes so the
  preview shows the glyph.

**Per-line justify.** `align_top` / `align_bottom` (`left`/`center`/`right`, default
`center`) independently justify line 1 / line 2 at the `render_lines` fit step, on RENDERED
cells (a `{gN}` glyph is one cell). The daemon coerces an invalid value to `center`. A
ticker's scrolling top line is already 20 cells wide, so alignment is a no-op there;
a static bottom line honors `align_bottom`.

**Animations (4):** `none` (show on change); `flash` (alternate the frame with a real
`blank()` — display goes fully DARK, timed by `on_ms`/`off_ms`); `blink` (2-state
brightness snap — the frame stays up but dims to MIN on the off-phase, `on_ms`/`off_ms`,
v0.7.0); `pulse` (a 4-level stepped **triangle-wave brightness sweep** `0→1→2→3→2→1→…`,
one level per `animation_params.step_ms` ≈ 1.2 s full sweep — a breathing effect that
OVERRIDES the static brightness, v0.7.2). blink/pulse fold into the brightness step (no
frame redraw). The daemon writes the on-glass result to status.json each tick — blank
top/bottom for flash-off, the applied `brightness` for blink/pulse — so the preview
animates all of them. **invert** was intentionally skipped: a character VFD (9 glyph
slots) can't do a true per-pixel invert for arbitrary text. **N/A in marquee (v0.8.1):**
the hardware ticker owns the top row, so the daemon forces `animation = "none"` on the
marquee path and the UI hides the Animation control there.

**Re-init rule.** After `self_test()`, `reset()`, or `define_character()` the display may
drop extended-mode/scroll-off; `initialize()` is re-run before the next `show()`. The
`self_test`/`reset` driver methods do this themselves; the daemon re-inits after a glyph batch.

**User glyphs (bench-confirmed, v0.3.1).** 9 glyph slots live at **non-contiguous**
character codes (`0x1B` is skipped):

| slot | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|------|`0x15`|`0x16`|`0x17`|`0x18`|`0x19`|`0x1A`|`0x1C`|`0x1D`|`0x1E`|

- **Define:** `0x03 <code> <7 row bytes> 0x00` (top row first). **Display:** write the
  slot's code byte. `_sanitize` allow-lists these codes so they survive into `show()`.
- **Bitmap encoding:** the display reads the 5 columns from **bits 3-7** of each row byte
  (column 1 = bit 3 `0x08` … column 5 = bit 7 `0x80`; a lit pixel in column C sets bit
  (C+2); full row = `0xF8`; bits 0-2 ignored). v0.3.0 masked to the *low* 5 bits, which
  was wrong and dropped the pixels.
- **Input convention:** `define_character(slot, rows)` and `state.glyphs` take
  **editor-natural** rows — 7 ints whose **low 5 bits are columns 1..5** (`bit0`=col1 …
  `bit4`=col5). The driver translates each to the wire byte by `(row & 0x1F) << 3`
  (`0x1F`→`0xF8`, `0x01`→`0x08`, `0x10`→`0x80`). One convention shared by the future
  editor/preview and the daemon; the `<<3` lives only in the driver.
- **Placeholders:** `{g0}`..`{g8}` in a `message` are replaced (message/ticker frames) by
  the slot's code byte, so text + glyphs mix freely, e.g. `"TEMP {g0}C"`.

**Code pages (confirmed available).** `select_code_page(page)` → `0x02 <page>`; `page` is a
name or int `0..11` (12 total). Confirmed: `0` default, `1` japanese (CP897), `2` cp850
(Fr/De/Es/Pt), `3` cp852, `4` cp855, `5` cp857 (Turkish). Pages 6–11 exist per the library
but are not yet identified on our unit. `state.code_page` drives this.

### 4.6 Phase 2b — web control surface (v0.4.0)
A single-page **Svelte + Vite + TypeScript** app (`ui/`) served by a **FastAPI** backend
(`web/`). **The daemon is untouched and stays the sole serial-port owner.** The web layer
only touches the JSON files the daemon already uses, preserving single-writer-per-file:

```
ui/ (Svelte)  ──HTTP /api──▶  web/ (FastAPI)  ──writes state.json──▶  daemon ──▶ VFD
   ▲ polls /api/status              ▲ reads status.json ◀───────────────  (daemon writes)
```

- **FastAPI never opens the serial port.** It reuses `checkout.state` (schema, defaults,
  atomic write, plus new `load_status` + `merge_patch`) so the on-disk format matches the
  daemon exactly. Paths come from the same env (`CHECKOUT_STATE_PATH` /
  `CHECKOUT_STATUS_PATH`), so a deployment just shares those two files on a volume.
- **Endpoints:**
  - `GET /api/status` — the daemon's mirror of the glass (top/bottom/mode/brightness/
    blank/scroll/last_command_id/alive/updated_at).
  - `GET /api/state` / `PUT /api/state` — read / deep merge-patch the desired state.
  - `POST /api/command` `{action,args}` — stamps `state.command = {id:<uuid>,...}` so the
    daemon runs it once (self_test | reset | redefine_glyphs).
  - `GET /api/health` — `{ok, daemon_alive}`; `daemon_alive` is derived from status.json
    freshness (< 5 s old + `alive`). Kept for external checks; the UI no longer hot-polls
    it (v0.8.3) — it derives `daemon_alive` client-side from the `/api/status` it already
    polls (`aliveFromStatus`, same freshness rule), so only `/api/status` is on the hot
    loop. Run uvicorn with `--no-access-log` to silence the ~2×/s poll's request log.
  - `/` — serves the built UI (`ui/dist`).
- **Preview mirrors status, not the controls.** `VfdPreview` renders a pixel-accurate
  2×20 of 5×7 phosphor dots from `/api/status` (so it shows real clock ticks, ticker
  motion, brightness, blank). A built-in 5×7 font covers ASCII `0x20–0x7E`; the 9 user
  glyph codes render from `state.glyphs` using the shared low-5-bit convention (§4.5). The
  preview box has a **fixed 2×20 aspect** so it never resizes on status/mode changes; the
  two layout columns are independent flex stacks, so no dead space appears under it (v0.8.2).
- **Aesthetic:** blue-green VFD phosphor (`#3df0c8`) on black, POS/rack-gear faceplate —
  thin rules, monospaced labels, subtle bevels, tactile switches, a faint scanline/bloom
  on the preview only. Plain hand-tuned CSS.
- **Controls** (`PUT /api/state` on change). Two panels split per-mode from device
  settings (v0.8.1): **Control** (per-mode) = mode, message (+40-char budget, `{gN}` hint),
  marquee text+tip, scroll per-row source/scroll/dir/speed, Justify, animation (+on/off ms;
  hidden in marquee); **Display** (`DisplayPanel.svelte`, mode-agnostic device settings) =
  brightness, blank, hardware scroll, code page. Right-column panel order: Control, Display,
  Saved Messages, Commands, Daemon. `CommandBar` fires once; `StatusReadout` shows daemon
  health; `GlyphEditorPanel` is the glyph editor (§4.7).
- **Dev/build:** vite dev server proxies `/api` → uvicorn:8000; `npm run build` → `ui/dist`
  which uvicorn serves in prod. Docker is deferred to Phase 3 but the layout is
  container-ready. See `web/README.md` and `ui/README.md`.

### 4.7 Phase 2c — glyph editor (v0.5.0)
A 9-slot 5×7 glyph editor (`GlyphEditorPanel`), built on the existing `state.glyphs`
contract and `{gN}` references — **no new endpoints or schema changes**.

- **Slot strip** — 9 thumbnails (g0–g8) rendered with the SAME dot routine as the main
  preview (`dotrender.paintCell` + `font5x7` decode), so a glyph looks identical in the
  strip, the editor, and on the simulated glass. Selected slot highlighted; per-slot sync dot.
- **Draw grid** — a 5×7 canvas (`GlyphCanvas.svelte`) with click and **click-drag paint**
  via pointer events (mouse + touch). The first cell sets the paint value (lit → erase,
  empty → paint); dragging applies it. Lit = phosphor square, empty = faint.
- **Tools** — Clear; **copy-from-character** (type any printable char to seed the grid from
  the real `font5x7` bitmap, then tweak); the `{gN}` token for the slot with one-click copy.
- **Debounced auto-push** — an edit updates local state instantly (optimistic
  `setGlyphLocal`, so the strip + main preview reflect it), then ~400 ms after the last edit
  a single `PUT /api/state` sends `{glyphs:{"<slot>":[7 ints]}}` (`pushGlyphs`). The backend
  `merge_patch` deep-merges that one slot without disturbing the others, and the daemon
  (re)defines the glyph on the display next tick (§4.5 glyph path). Never per-toggle — the
  debounce is the contract. A subtle per-slot indicator shows syncing… / synced ✓.
- **Encoding** uses the shared low-5-bit convention (`glyphedit.ts`: `withBit` /
  `copyFromChar` / `normGlyph`), so the editor encode round-trips through the preview decode
  (`lineToCells`) — what you draw is what the daemon defines (test-verified).
- **Dev/build:** vite dev server proxies `/api` → uvicorn:8000; `npm run build` → `ui/dist`
  which uvicorn serves in prod. Docker is deferred to Phase 3 but the layout is
  container-ready. See `web/README.md` and `ui/README.md`.

### 4.8 Phase 2d — saved library (v0.7.0)
A persistent library of saved **messages** and **glyphs**, **web-owned** in `library.json`
(env `CHECKOUT_LIBRARY_PATH`, default `./library.json`). **The daemon never reads it** —
recalling an item writes `state.json` through the normal path, preserving single-writer
ownership. `web/library.py` validates input and writes atomically (reusing
`checkout.state.atomic_write_json`); each list is capped at 200.

- **Schema:** `{ "messages": [{id, name, message, mode, align_top, align_bottom, brightness,
  glyphs: {<slot>:[7 ints]}}], "glyphs": [{id, name, rows:[7 ints]}] }`. A saved message
  carries the glyph defs it references, so recalling it makes its `{gN}` refs light up.
- **Endpoints:** `GET /api/library`; `POST /api/library/messages` (saves the current
  composable state) / `DELETE …/{id}` / `POST …/{id}/recall` (the one bridge from library
  to live: merge-patches the message's fields + glyphs into `state.json`);
  `POST /api/library/glyphs` `{name, rows}` / `DELETE …/{id}`;
  `POST /api/library/glyphs/order` `{ids}` (drag-to-reorder, v0.7.1).
- **9 slots vs the library:** the 9 glyph **slots** are the live hardware registers the
  daemon defines; the **library** is unlimited saved bitmaps you load *into* a slot.
  Loading routes through the same optimistic + debounced push as drawing.
- **UI:** `SavedMessages` (save current / recall / delete) and `GlyphLibrary` (save the
  selected slot / load / reorder / delete; mini phosphor thumbnails via the shared
  dot-render). The selected editor slot is a shared store so the library targets it.
- **Drag-and-drop (v0.7.1; cross-component fix v0.8.3):** drag a library glyph onto a slot
  (g0–g8) to load it there (drop target highlights; the slot becomes selected); drag within
  the library to reorder (persisted to `library.json`, optimistic + revert). The library→slot
  drop crosses two components, so it relies on a shared `draggedGlyph` store: the slot's
  `dragover` `preventDefault()`s whenever that store is set (so the browser actually fires
  `drop` — gating only on `dataTransfer.types` is unreliable, its custom-MIME visibility
  during dragover is browser-dependent). HTML5 DnD doesn't fire on touch, so a **click/tap
  fallback** loads into the selected slot (cards are keyboard-activatable).

### 4.9 Phase 3a — spectrum analyzer (v0.9.0)
A crude real-time audio spectrum analyzer (mode `spectrum`): 20 bands, double-
height (14 levels over 2 rows), ~21fps. THREE processes; the daemon stays the
sole serial owner.

```
audioviz (capture+FFT) ── unix DGRAM socket (20-byte frame) ──► daemon ──► VFD
   ▲ reads audio_* from state.json                              ▲ writes status.bars
```

- **`checkout.audioviz`** (separate process; never opens the port). Hann window →
  numpy rFFT → 20 LOG-spaced bands → dB-scaled heights 0..14 with
  **attack-fast/release-slow** decay (`out = max(new, prev*decay)`). Source via
  `state.json`: `system` / `mic`; `audio_device`/`audio_gain`/`audio_decay`
  re-read live (capture runs only while mode = spectrum).
  - **system audio (v0.9.1):** PortAudio can't see PipeWire `.monitor` sources, so
    it's captured NATIVELY via `pw-record`/`parec` reading the monitor (enumerated
    with `pactl`; default = `pactl get-default-sink` + `.monitor`). `select_capture`
    never silently uses the mic for `system`. **mic** uses `sounddevice`.
  - **hardened restart (v0.9.1):** full PortAudio teardown (null → stop → close,
    guarded) + debounced switches + try/except open, so cycling devices can't
    segfault. Device list is LABELED (monitors vs inputs) in `devices.json`
    (`--list`, served at `/api/devices`); the UI filters by source. Needs
    `pipewire-pulse` + `portaudio`.
- **Socket protocol.** Unix `SOCK_DGRAM` (`CHECKOUT_SPECTRUM_SOCK`, default
  `$XDG_RUNTIME_DIR/checkout-spectrum.sock`). Each datagram = a fixed **20-byte**
  frame (one height 0..14 per bar). Newest-frame-wins: the daemon **drains to the
  latest** datagram each loop (stale discarded), so a slow reader can't back up a
  stream. Heavy per-frame data goes here; only settings via `state.json`.
- **Daemon spectrum path.** On enter: define the **7 bar height-glyphs** (slots
  0..6; this OVERWRITES those user glyphs) + bind the socket. Each iteration:
  drain → latest heights (or **decay toward 0** if no datagram within
  `SPECTRUM_STALE_MS`) → double-height bars → emit-diff a `show()` (~21fps, paced
  by the serial write). On leave: re-apply `state.glyphs` (RESTORE user glyphs);
  animation forced `none`. `status.bars` carries the 20 heights for the preview.
- **Bench-locked (do not retune):** 9600 baud cap, ~21fps full-frame ceiling,
  double-height over 7 partial glyphs, height 0..14 → bottom cell 1..7 then top
  8..14, `bar_glyph(h)` lights rows `r ≥ 7-h` full width (`0x1F`).

---

## 5. Open items
- [x] ~~Confirm DB9 pin mapping~~ — DATA=3, GND=5, +12 V=8, back-feed=1 (open). Done.
- [x] ~~Confirm power~~ — 12 V alone. Done.
- [x] ~~Confirm bring-up matrix~~ — RS-232 / inversion OFF / 9600 8N1. Done.
- [x] ~~Confirm command bytes~~ — adopted the authoritative Futaba M202MD10C set (§3) with
  the extended-mode init sequence; all 40 cells writable. Done (v0.2.0).
- [x] ~~Confirm brightness command~~ — FOUR levels `0x04` + `0x20`/`0x40`/`0x60`/`0xFF`,
  bench-confirmed under extended mode (v0.6.2). Done.
- [x] ~~Confirm user-glyph codes + bitmap encoding~~ — 9 non-contiguous codes,
  columns in bits 3-7 (§4.5). Done (v0.3.1).
- [x] ~~Confirm code pages~~ — 12 pages, names 0–5 confirmed (§4.5). Done (v0.3.1).
- [ ] Decide frame rotation timing and data-source set for v0.1.
- [ ] Seal the enclosure once interface dev is far enough along to stop probing.

## 6. References
- PerfectoWeb/IBM-VFD-Display-ESP32-S3 — exact display class, known-good RS-232 config.
- playfultechnology/arduino-VFD-RS232 — true-RS-232 build + ESC/POS PDF.
- SNMetamorph "Toshiba 00DN901" writeup — M202MD10C bare-board (inverted-TTL fallback).
- Instructables "Cash Register Clock (VFD Display)" — bare-board teardown + command codes.
- IBM SurePOS 500 Technical Reference — connector pinout, RJ45→DB9 cable.
- Petint/IBM_41k6814 — the RS-485 41K6814 variant (NOT this unit; the avoided trap).
