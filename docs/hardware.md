<!-- Moved out of CLAUDE.md on 2026-08-16 under the four-tier standard
     (~/mathom/conventions/the-four-tiers.md). Tier 2: needed by someone
     cloning this repo, not needed on every turn. -->

# Hardware reference

Two displays: the **IBM SurePOS** (Futaba M202MD10C, below) and the **HP
LD220-HP** (EPSON mode). `CHECKOUT_DISPLAY` picks one per machine. Last, the
**TG3 M4220 bump bar**, an input keypad on dad.

## IBM SurePOS (Futaba M202MD10C)

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


### Extended characters 0x80-0xFF (bench, v1.4.0)
Photographed on page 0 (default) and page 2 (CP850). ASCII (0x20-0x7E) looks the
same on both pages. **Reference only: the driver sends none of these** (only
printable ASCII and the 9 user-glyph codes). A built-in degree sign — `0xF8` on
page 2, a 4-dot ring identical to the custom one — was wired in and then reverted
by choice: the custom degree glyph and pacman's font colon were preferred.

Also seen: page 2 follows the standard CP850 table — `ø` 0x9B and `Ø`
0x9D (but `Ø` is only 5 rows tall, so it cannot stand in for a slashed zero),
`± ÷ ¼ ½ ¾ ¹ ² ³ § ¶ « »` in 0xA0-0xFF. Page 0 is CP437-like: accented Latin
0x80-0x9F, Greek 0xB0-0xBF, maths/arrows 0xF0-0xFF (`≠ ≡ ← →`), superscripts and
`× ± ∫` at 0xC5-0xCA, and a Cyrillic block at 0xD0-0xEF. Before using any of these,
bench-confirm the exact byte and page, and let it through `driver._sanitize`
(it replaces everything above 0x7E with `?`).


## HP LD220-HP (EPSON command mode)

Driver: `checkout/driver_epson.py` (`EpsonDriver`). Source: the OEM "VFD LD220
User Manual V2.3" §4.1.2. There is no HP-branded command reference.

### Bench facts (power-on self-test, 2026-09-28)

| | |
|---|---|
| USB ID | `03f0:3524` — kernel `pl2303` driver, node `/dev/ttyUSB*` |
| by-id path | `/dev/serial/by-id/usb-Prolific_Technology_Inc._USB-Serial_Controller_22222222-if00-port0` |
| Firmware | 6.6 · EEPROM OK · pass-through: none |
| Serial | 9600, N, 8, 1 |
| **Command mode** | **EPSON** (factory default) |
| Character set | USA/Europe |
| Power | **5 V USB bus power alone** (the manual: 5–12 V input). No 12 V supply |
| Power-on screen | scrolling "have a nice day" welcome, until the host writes |

`22222222` is a placeholder serial that many Prolific chips share. It is unique
only while this is the one Prolific adapter on the machine.

**check-out requires EPSON mode.** The mode lives in the display's memory, and
only HP's Windows setup utility changes it. The self-test screen shows the
current mode. In any other mode our bytes print as garbage.

### Command bytes

| Operation | Bytes | Notes |
|---|---|---|
| init | `1B 40` · `1F 01` · `1F 43 00` · `1B 25 00` | `ESC @` (**erases user glyphs**) · overwrite mode · cursor off · user set off |
| move cursor | `1F 24 x y` | **1-based**: x = col 1–20, y = row 1–2 |
| full frame | `1F 24 01 01` + row + `1F 24 01 02` + row | 48 bytes of text; + 3 bytes per user-set switch |
| changed cells | `1F 24 x y` + run | merge gap 4; a full frame when that is no longer |
| brightness | `1F 58 n` | n = 1–4 (state index 0–3 + 1) |
| define glyphs | `1B 26 01 30 38` + 9 × 5 column bytes | **all 9 in one command**; per column bit 0 = top row; **no width byte** |
| user set on / off | `1B 25 01` / `1B 25 00` | switched per written character (see below) |
| blank | `0C` | clears the glass; glyph definitions survive |
| self-test | `1F 40` | then re-init |
| scroll mode | `1F 02` on / `1F 01` off | hidden in the UI |
| code page | `1B 74 00` | page 0 only; other numbers unconfirmed |

No hardware ticker: `start_ticker` writes the first 20 chars to the top row
(marquee is hidden in the UI anyway).

### User glyphs — how the bench unit really behaves (2026-09-28)

Three things differ from the manual and the Epson convention. Each was found
with a probe on the glass:

1. **No width byte.** The manual's `[a(p1..p5)] … a=5` reads like a `05` before
   each character's pattern. The unit took that `05` as column 1 (a
   top-left + bottom-right test drew a raised colon instead).
2. **Bit 0 is the top row** of each column byte (Epson DM-D uses bit 7). An
   asymmetric `F` test glyph drew exactly as designed.
3. **Each `ESC &` replaces the whole user set.** Nine one-glyph defines left
   only the last one; four glyphs in one ranged command all survived. So the
   driver keeps the 9 bitmaps itself and `glyphs_loaded()` re-sends all of them
   in one command at the contiguous codes `'0'..'8'` (slot n = digit n).

**`ESC %` applies to characters as they are written**, not to what is already
shown: a row written with the set off kept plain `{|}~` after the set was
switched back on. So the driver switches the set on only around glyph cells and
off before any real `0`–`8`, and every write ends with it off. Text prints
unchanged, digits included; no character is given up to the glyphs.

### Bench checks

| # | Check | Result |
|---|---|---|
| 1 | init stops the welcome; `show()` lands both rows (1-based `1F 24`) | **pass** |
| 2 | glyph format | **pass after fixes** — no width byte, bit 0 = top, one define for all 9 |
| 3 | cursor stays hidden after `1F 43 00` across writes | **pass** — no trailing cursor-off needed |
| 4 | `1F 58 1..4` gives four distinct levels | **pass** (pulse animation) |
| 5 | `0C` keeps glyph definitions | **pass** (flash animation) |
| 6 | spectrum keeps up | **pass** — "just like the IBM" |
| 7 | every mode by eye | **pass** — spectrum ×3 layouts, weather ×4 colons, pacman duo/solo, news alert (throb), scrolling message with `[1] \| ~ 2026` |

All seven checks passed on 2026-09-28 (firmware 6.6). The HP also looks brighter
than the IBM at the same level, likely phosphor wear on the salvaged IBM.

## TG3 M4220 bump bar (input, v1.9.0)

A 10-key kitchen "bump" keypad, **KBA-M4220A-BC15A** (NCR part 7182-1058-9900),
plugged into dad. It is an input device, not a display: `checkout-bumpbar`
reads it and drives check-out and desktop controls (see `CLAUDE.md`).

### Bench facts (dad, 2026-09-28)

| | |
|---|---|
| USB ID | `0f39:0101` — lsusb "TG3 Electronics M4220"; the HID chip reports "Heng Yu Technology" |
| Link | the bar's RJ45 jack → an RJ45-to-USB cable. **The RJ45 is not Ethernet**: never plug a network or PoE cable into it |
| Input nodes | three on one USB device: the keyboard (`…M4220-event-kbd`), "System Control" (`…-event-if01`, advertises Power/Sleep/Wake) and "Consumer Control" (no by-id link — udev links one node per interface). The service grabs all three, found through sysfs |
| Keys | column 1 top→bottom `a b c d e`, column 2 `f g h i j` (evdev 30 48 46 32 18 / 33 34 35 23 36). The grey blank key is `h` |
| **Key timing** | **every key is an instant tap**: key-down then key-up 30–40 ms later, however long it is held, and **no auto-repeat**. A held key cannot be seen, so the grey key is a one-shot shift (tap it, then a key) |
| LED | green idle, red while a key is down |
| Ports + switch | **RJ45 · switch · RJ11** along the bottom edge. With the switch toward the RJ45 the bar works over USB. Flipping it toward the RJ11 did **not** drop the USB link (no disconnect in the kernel log). TG3 and NCR bars carry powered RS-232 on an RJ11/RJ12 jack, so the switch most likely picks the serial jack — **inferred, not confirmed**. Leave it toward the RJ45 |

**Manager mode:** holding the keys with *internal* numbers 2 and 9 for ~4 s turns
the LED amber; the next key then changes firmware options (key table, buzzer,
baud). If the LED goes amber, press nothing. Source: "TG3 Bump Bar Programming
Instructions" (posmarket PDF).

### Access

`deploy/udev/70-checkout-bumpbar.rules` tags the bar's nodes `uaccess`, so the
logged-in user gets an ACL on this device only (`getfacl /dev/input/event25`
shows `user:matt:rw-`). One sudo install per machine; the file must sort before
`73-seat-late.rules`, which applies the ACL. Not the `input` group, which would
open every keyboard to every program.

`python -m checkout.bumpbar --capture` prints raw key codes (stop the service
first: only one process can grab the bar).
