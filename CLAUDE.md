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

### Confirmed command bytes (single-byte control codes; NOT ESC/POS)
| Action                | Bytes                          |
|-----------------------|--------------------------------|
| Clear whole display   | `0x1F`                         |
| Set cursor position   | `0x10` then ONE position byte  |
| Write text            | printable ASCII at cursor (auto-advances + wraps) |
| Hide cursor           | `0x14` (must be sent LAST — see rule 1) |
| Brightness DIM        | `0x04 0x20`                    |
| Brightness BRIGHT     | `0x04 0xFF`                    |

### Addressing (linear: `position = line*20 + col`)
| Line        | Range        |
|-------------|--------------|
| Top line    | `0x00`–`0x13` (0–19)  |
| Bottom line | `0x14`–`0x27` (20–39) |

The 40th cell (`0x27`) is only written for a visible glyph (rule 2); with a
space there it's left untouched, so effective width is 39 in that case.

### Behavioral rules (bench-verified — do not regress)
1. **Cursor-hide last.** `0x14` hides the cursor, but ANY subsequent write
   re-enables it (no persistent off, no separate on byte). So `0x14` must be the
   FINAL byte of every frame update.
2. **40th-cell scroll — only a VISIBLE glyph anchors.** Writing cell `0x27`
   (bottom-right) advances the cursor past the end and scrolls the display up. A
   reposition (`0x10 0x00`) right after suppresses that scroll — but ONLY when a
   visible glyph was written. Writing a SPACE (`0x20`) into `0x27` does NOT
   anchor the cursor, so it scrolls anyway. Rule: write `0x27` only for a visible
   char; if the 40th char is a space, DON'T write `0x27` at all (the cursor sits
   at `0x27` after the 19-char write without advancing). Effective usable width
   is 39 cells whenever the 40th char is a space.
3. **No leading clear.** A `0x1F` immediately before a full-frame write scrolls
   the display. Frames overwrite in place; `0x1F` is for explicit `clear()`/
   `blank()` only.
4. **Brightness = two levels only.** DIM (`0x04 0x20`) / BRIGHT (`0x04 0xFF`).
   Other level bytes are ignored — not a 0–255 scale, not four levels. Live, no
   redraw needed.

### `show()` byte sequence (encodes rules 1–3 — keep intact)
```
0x10 0x00  <top: 20 ASCII bytes>
0x10 0x14  <bottom: first 19 ASCII bytes>   # cells 0x14..0x26
# IF the 40th char is a visible glyph:
0x10 0x27  <bottom: 20th ASCII byte>         # the 40th cell
0x10 0x00  # reposition — anchors cursor, suppresses the 40th-cell scroll
# ELSE (40th char is a space): emit nothing for 0x27.
0x14       # hide cursor — MUST be last
```
One buffered serial write (no flicker). Overwrite-in-place, NO `0x1F` clear.

### Pin map (RJ-style connector)
| Pin | Use                                            |
|-----|------------------------------------------------|
| 1   | **back-feed hazard — leave open**              |
| 3   | DATA                                           |
| 5   | GND                                            |
| 8   | +12V                                           |

## Architecture
The daemon is the **sole owner** of the serial port (only one process may hold
it). The web UI (Phase 2) communicates *only* by writing `state.json`.

```
state.json (atomic) <-- web UI (Phase 2, not built yet)
     |  read each tick
     v
daemon loop --> active frame --> renderer (fit to 2x20) --> driver --> serial
```

- `driver.py` — `VFDDriver`, owns **all** raw command bytes; nothing else emits bytes.
- `renderer.py` — pure fit/pad/center/ticker logic (no serial).
- `frames/base.py` — `Frame` interface; `frames/clock.py` — `ClockFrame`.
- `state.py` — atomic load/save of `state.json`.
- `daemon.py` — main loop + entrypoint; diffs frames, reconnects, shuts down clean.

## Versioning
Semver `major.minor.patch` read as **"big.small.bug"**.

## How to run
```bash
pip install -r requirements.txt
python -m checkout.daemon --dry-run   # no display; prints outgoing bytes as hex
python -m checkout.daemon             # live, opens the serial port
```
Env overrides: `CHECKOUT_PORT`, `CHECKOUT_BAUD`, `CHECKOUT_TICK_MS`,
`CHECKOUT_STATE_PATH`.

## Serial permissions
The dev user must belong to the device's group (on Arch this is `uucp`) or run
with `sudo`:
```bash
sudo usermod -aG uucp "$USER"   # then re-login
```

## Roadmap
- **Phase 1 (this):** driver, renderer, clock frame, daemon, state seam.
- **Phase 2:** FastAPI web UI that writes `state.json` (custom message, mode,
  flash patterns, blank, brightness).
- **Phase 3:** more frames + rotation + Docker for arda.
- Brightness byte confirmed in v0.1.1 (two levels: dim/bright).
