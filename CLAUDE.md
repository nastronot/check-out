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
  "glyphs": { "0": [r0..r6], ... "8": [...] },  // optional 5x7 user glyphs, 7 ints (low 5 bits)
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

## Versioning
Semver `major.minor.patch` read as **"big.small.bug"**.

## How to run
```bash
pip install -r requirements.txt
python -m checkout.daemon --dry-run   # no display; prints outgoing bytes as hex
python -m checkout.daemon             # live, opens the serial port
```
Env overrides: `CHECKOUT_PORT`, `CHECKOUT_BAUD`, `CHECKOUT_TICK_MS`,
`CHECKOUT_STATE_PATH`, `CHECKOUT_STATUS_PATH`.

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
- **Phase 2b:** Svelte/FastAPI web UI that writes `state.json` + reads `status.json`.
- **Phase 3:** more frames + rotation + Docker for arda.
- Brightness byte confirmed in v0.1.1 (two levels: dim/bright).
- **v0.2.0:** adopted the authoritative Futaba M202MD10C command set + extended-mode
  init sequence — all 40 cells now writable, the old 39-cell/scroll workarounds removed.
  Vertical scroll exposed as a controllable feature. TODO: retest 4-level brightness.

## Hardware-confirm TODOs (bench)
- Which character code(s) render the 9 user glyphs after `define_character` (probe:
  define glyph 0, then write bytes `0x00`..`0x08` and see which shows it). Document the
  code→glyph mapping.
- Whether code pages (`0x02` + page) visibly change the glyph set on our unit.
- Whether extended mode exposes the library's claimed 4 brightness levels.
