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
| **Select code page** | `0x02` + page byte | 12 code pages (wire later) |
| **Define character** | `0x03` + index + 7 bytes + `0x00` | 9 user-definable glyphs (wire later) |
| **Dimming / brightness** | `0x04` + level byte | DIM `0x04 0x20`, BRIGHT `0x04 0xFF` |
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

4. **Brightness is two confirmed levels** — DIM (`0x04 0x20`) and BRIGHT (`0x04 0xFF`),
   applied live (no redraw needed). The library claims 4 levels and extended mode may expose
   more; left at the two confirmed values for now (TODO: retest the intermediate level bytes
   under extended mode).

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
- `set_brightness("dim"|"bright")` → `0x04 0x20` / `0x04 0xFF`
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

### 4.3 Constraint-as-feature
- Hard cap: 2×20. No graphics (character cell display).
- Lean into it: rotating single-purpose frames, ticker for anything longer, blink/dim
  for emphasis. The limitation is the charm.

### 4.4 Initial frames (v0.1.x)
- Clock (HH:MM:SS + date) — proves the full path end to end.
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
  "mode": "clock" | "message" | "ticker",
  "message": "text for message/ticker mode",
  "brightness": "dim" | "bright",
  "blank": false,
  "scroll": false,                 // hardware vertical-scroll MODE (0x11/0x12); normally false
  "code_page": 0,                  // 0..11
  "scroll_speed_ms": 300,          // ticker software-scroll step
  "animation": "none" | "flash" | "blink",
  "animation_params": { "on_ms": 500, "off_ms": 500 },
  "glyphs": { "0": [r0..r6], ... "8": [...] },  // optional 5x7 user glyphs, 7 ints (low 5 bits)
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

**Modes.** `clock` (date + HH:MM:SS); `message` (static — a newline splits the two
lines, else greedy word-wrap/center, ≤40 chars); `ticker` (software horizontal scroll of
a long message on the top line at `scroll_speed_ms`/step, via `renderer.ticker_window`).

**Animations** (timed by `animation_params.on_ms`/`off_ms`): `none` (show on change),
`flash` (alternate the frame with a real `blank()` — display goes dark), `blink`
(alternate the frame with blank lines — display stays on).

**Re-init rule.** After `self_test()`, `reset()`, or `define_character()` the display may
drop extended-mode/scroll-off; `initialize()` is re-run before the next `show()`. The
`self_test`/`reset` driver methods do this themselves; the daemon re-inits after a glyph batch.

**Hardware-confirm TODOs (bench):** which character code(s) render the 9 user glyphs
after `define_character` (probe: define glyph 0, write bytes `0x00`..`0x08`, see which
shows it — document the mapping); whether code pages (`0x02` + page) visibly change the
glyph set. These don't block the code — the commands are wired; confirm exact codes on glass.

---

## 5. Open items
- [x] ~~Confirm DB9 pin mapping~~ — DATA=3, GND=5, +12 V=8, back-feed=1 (open). Done.
- [x] ~~Confirm power~~ — 12 V alone. Done.
- [x] ~~Confirm bring-up matrix~~ — RS-232 / inversion OFF / 9600 8N1. Done.
- [x] ~~Confirm command bytes~~ — adopted the authoritative Futaba M202MD10C set (§3) with
  the extended-mode init sequence; all 40 cells writable. Done (v0.2.0).
- [x] ~~Confirm brightness command~~ — two levels: DIM `0x04 0x20`, BRIGHT `0x04 0xFF`. Done.
- [ ] Decide frame rotation timing and data-source set for v0.1.
- [ ] Seal the enclosure once interface dev is far enough along to stop probing.

## 6. References
- PerfectoWeb/IBM-VFD-Display-ESP32-S3 — exact display class, known-good RS-232 config.
- playfultechnology/arduino-VFD-RS232 — true-RS-232 build + ESC/POS PDF.
- SNMetamorph "Toshiba 00DN901" writeup — M202MD10C bare-board (inverted-TTL fallback).
- Instructables "Cash Register Clock (VFD Display)" — bare-board teardown + command codes.
- IBM SurePOS 500 Technical Reference — connector pinout, RJ45→DB9 cable.
- Petint/IBM_41k6814 — the RS-485 41K6814 variant (NOT this unit; the avoided trap).
