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

## 3. Command set (BENCH-CONFIRMED on this unit)

Single-byte control codes (this is NOT ESC/POS — `0x1B 0x40` printed a literal "@", so
ESC-prefixed commands do not apply). Verified by sending bytes and observing the display:

| Command | Bytes | Behavior |
|---------|-------|----------|
| **Clear** | `0x1F` | clears the whole display |
| **Set cursor position** | `0x10` then one position byte | moves cursor to absolute position |
| **Write text** | printable ASCII | prints at cursor, cursor auto-advances |
| **Hide cursor** | `0x14` | hides the cursor block (see rule 1 — must be sent last) |
| **Brightness DIM** | `0x04 0x20` | dim level |
| **Brightness BRIGHT** | `0x04 0xFF` | bright level |

**Addressing (linear):**
- Top line:    positions `0x00`–`0x13` (0–19)
- Bottom line: positions `0x14`–`0x27` (20–39)
- `position = line * 20 + column` (line 0 = top, line 1 = bottom)
- The 40th cell (`0x27`) is written only for a visible glyph (rule 2); a space there is
  left untouched, so the effective width is 39 whenever the 40th char is a space.

**Behavioral rules (bench-verified — ground truth):**

1. **Cursor hide must be last.** `0x14` hides the cursor, but ANY subsequent write
   RE-ENABLES it. There is no persistent "cursor off" and no separate "cursor on" byte —
   writing implicitly turns it back on. Therefore `0x14` must be the LAST byte of every
   frame update, after all positioning and text. (The v0.1.0 clock omitted this, so a
   cursor block appeared on screen — fixed in v0.1.1.)

2. **40th cell scrolls — and only a VISIBLE glyph anchors it.** Writing the last cell
   (`0x27`, bottom-right) auto-advances the cursor PAST the end, which scrolls the whole
   display up and loses the top line. A reposition (`0x10 0x00`) right after writing `0x27`
   suppresses that scroll — BUT only when a visible glyph was written. Writing a SPACE
   (`0x20`) into `0x27` does NOT anchor the cursor, so the reposition fires too late and it
   scrolls anyway (bench-verified: same frame with `X` at `0x27` holds; with a space it
   wraps). Rule: write `0x27` only for a visible char; if the 40th char is a space, don't
   write `0x27` at all — the cursor sits at `0x27` after the 19-char write without
   advancing. So the effective usable width is 39 cells whenever the 40th char is a space.

3. **No leading clear.** Sending `0x1F` immediately before a full-frame write scrolls the
   display (bench-verified: an all-`#` fill that holds wraps when prefixed with `0x1F`).
   Frames must overwrite in place; `0x1F` is for explicit `clear()`/`blank()` only.

4. **Brightness is two discrete levels only** — DIM (`0x04 0x20`) and BRIGHT (`0x04 0xFF`).
   Other level bytes (`0x00`–`0x03`, `0x40`, `0x60`, `0x80`, `0xC0`) are IGNORED. It is NOT
   a 0–255 scale and NOT four levels. Brightness applies live (no redraw needed).

**`show()` byte sequence (do not regress — encodes rules 1–3):**
```
0x10 0x00  <top: 20 ASCII bytes>
0x10 0x14  <bottom: first 19 ASCII bytes>   # cells 0x14..0x26
# IF the 40th char is a visible glyph:
0x10 0x27  <bottom: 20th ASCII byte>         # the 40th cell
0x10 0x00  # reposition — anchors the cursor, suppresses the 40th-cell scroll
# ELSE (40th char is a space): emit nothing for 0x27 (a space there would scroll).
0x14       # hide cursor — MUST be the final byte
```
Built as one buffered serial write (no flicker, cursor-hide reliably last). The bottom
line is split 19+1; the top line needs no split (its auto-advance lands on `0x14`, which
the next position command overwrites anyway). `show()` does NOT clear first — it overwrites
in place (a leading `0x1F` clear would scroll, per rule 3).

**Driver primitives** wrap exactly the confirmed bytes, so the app never emits raw bytes:
- `clear()` → `0x1F`
- `write_at(pos, text)` → `0x10`, `chr(pos)`, then ASCII text
- `show(top, bottom)` → the buffered sequence above (overwrite-in-place, cursor-hide last)
- `set_brightness("dim"|"bright")` → `0x04 0x20` / `0x04 0xFF`
- `blank()` → `0x1F` then `0x14` (dark screen, no lingering cursor block)

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
- **Driver layer:** opens the port (9600 8N1), exposes `clear`, `write_at`,
  `set_brightness`, `show`. Owns all command bytes. Write-only.
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

---

## 5. Open items
- [x] ~~Confirm DB9 pin mapping~~ — DATA=3, GND=5, +12 V=8, back-feed=1 (open). Done.
- [x] ~~Confirm power~~ — 12 V alone. Done.
- [x] ~~Confirm bring-up matrix~~ — RS-232 / inversion OFF / 9600 8N1. Done.
- [x] ~~Confirm command bytes~~ — clear `0x1F`, position `0x10`+byte, ASCII text. Done.
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
