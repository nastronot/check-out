<!-- Moved out of CLAUDE.md on 2026-08-16 under the four-tier standard
     (~/mathom/conventions/the-four-tiers.md). Tier 2: needed by someone
     cloning this repo, not needed on every turn. -->

# Hardware reference

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

