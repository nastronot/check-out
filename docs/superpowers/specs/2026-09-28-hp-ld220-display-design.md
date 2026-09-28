# HP LD220-HP display support — design

**Date:** 2026-09-28 · **Target version:** v1.8.0 · **Status:** draft for review

## Intent

Matt has an **HP LD220-HP** pole display (2×20 VFD) to use with check-out at
work. Long term, **each display has its own machine**: the IBM SurePOS stays on
dad, the HP goes to work. The two share one machine only during setup, when both
are plugged into dad for testing.

**Success:**
1. Every check-out feature (clock, message, dynamic/weather + pacman + news
   alerts, spectrum, glyph editor, brightness, animations) works on the HP as it
   does on the IBM.
2. During setup, both displays run on dad at once, each with its own UI, without
   disturbing the installed IBM services.
3. work runs the HP from the same `deploy/install.sh`, set to `hp`. What was
   tested on dad is exactly what runs at work.

**Decided (with Matt, 2026-09-28):** no in-UI display dropdown. A dropdown only
pays off when one machine drives both displays for good, which is not the plan.
Which display a machine has is a **per-machine setting**.

## Bench facts (read off the HP's power-on self-test, 2026-09-28)

| | |
|---|---|
| USB ID | `03f0:3524` — kernel `pl2303` driver, node `/dev/ttyUSB*` |
| by-id path on dad | `/dev/serial/by-id/usb-Prolific_Technology_Inc._USB-Serial_Controller_22222222-if00-port0` |
| Firmware | 6.6 · EEPROM OK · pass-through: none |
| Serial | 9600, N, 8, 1 |
| **Command mode** | **EPSON** |
| Character set | USA/Europe |
| Power-on screen | scrolling "have a nice day" welcome, until the host writes |
| Power | **5 V USB bus power alone** — no 12 V supply needed (the manual: "5V to 12V" input). Looks brighter than the IBM by eye |

`22222222` is a placeholder serial number that many Prolific chips share. It is
still unique on dad, because the IBM's adapter is an FTDI chip. On a machine with
two Prolific adapters this path would clash. That setup is not planned.

Protocol source: the OEM "VFD LD220 User Manual V2.3" §4.1.2 (EPSON command
mode), bundled in the `ld220` Ruby gem. There is no HP-branded command reference.

## Architecture

The daemon, frames, renderer, state files and UI stay **display-agnostic**. The
only new seam is **which driver class the daemon opens**.

```
CHECKOUT_DISPLAY=ibm|hp ──> displays.make_driver() ──> VFDDriver   (Futaba, existing)
                                                  └──> EpsonDriver (HP LD220, new)
```

### Logical glyph codes stay 0x15–0x1E

Frames already embed user glyphs as the characters `chr(0x15..0x1E)`: spectrum,
weather, news alert and `{gN}` placeholders all do this. The UI preview reads the
same codes from `status.json`. **These stay as the app-wide logical encoding.**
Each driver translates them to wire bytes in its own sanitize step. The IBM
translation is the identity (these are its real codes). Nothing above the driver
changes.

### The driver interface

Both drivers expose today's `VFDDriver` public surface: `open`, `close`,
`initialize`, `reset`, `blank`, `show`, `show_changes`, `show_bottom`,
`start_ticker`, `set_brightness`, `set_vertical_scroll`, `define_character`,
`select_code_page`, `self_test`, plus `port`, `baud` and `dry_run`.

**One new method: `glyphs_loaded()`.** Today the daemon calls `initialize()`
after defining glyphs, because on the IBM a define can knock the display out of
extended mode. On the HP, `initialize()` sends `ESC @`, which **erases the glyphs
just defined**. The three call sites in `daemon.py` (`_sync_glyphs` ×2,
`redefine_glyphs`) switch to `driver.glyphs_loaded()`:
- IBM: calls `initialize()`, exactly today's behaviour.
- HP: sends `ESC % 1`, which switches the user character set on.

A class attribute `DISPLAY` (`"ibm"` / `"hp"`) and `LABEL`
(`"IBM SUREPOS 2×20 VFD"` / `"HP LD220 2×20 VFD"`) identify the driver.

### New modules

- **`checkout/driver_epson.py` — `EpsonDriver`.** Owns every HP byte. Shares
  `normalize_brightness`, `VFDError`, `_pad` and `apply_glyph_placeholders` with
  `driver.py` by import. It does not copy them.
- **`checkout/displays.py`** — the registry `{"ibm": VFDDriver, "hp":
  EpsonDriver}` and `make_driver(dry_run)`. That function reads
  `config.DISPLAY`; an unknown value raises at startup with the valid names.

### Config

`config.DISPLAY = os.environ.get("CHECKOUT_DISPLAY", "ibm")`. The default keeps
dad's current install working unchanged. `CHECKOUT_PORT` already exists.

## EpsonDriver byte plan (EPSON mode, manual §4.1.2)

| Operation | Bytes | Notes |
|---|---|---|
| `initialize()` | `1B 40` · `1F 01` · `1F 43 00` · `1B 25 01` | init (erases glyphs) · overwrite mode · cursor off · user set on |
| move cursor | `1F 24 x y` | x = col 1–20, y = row 1–2 (**1-based**) |
| `show(top, bottom)` | `1F 24 01 01` + 20 bytes + `1F 24 01 02` + 20 bytes | 48 bytes; no trailing cursor-off (see bench check 3) |
| `show_changes` | `1F 24 x y` + changed run, per run | merge gap **4** (the header is 4 bytes, not 2); falls back to `show()` at ≥ 48 bytes |
| `show_bottom` | `1F 24 01 02` + 20 bytes | |
| `set_brightness(i)` | `1F 58 (i+1)` | index 0..3 → n 1..4; same four-level state value |
| `define_character(slot, rows)` | `1B 26 01 c c 05 p1..p5` | `c` = the slot's parked code (below). Rows (7, low 5 bits = columns) are turned into 5 column bytes |
| `glyphs_loaded()` | `1B 25 01` | |
| `blank()` | `0C` | clear screen; glyph definitions survive |
| `reset()` | `initialize()` | the daemon then redefines glyphs (caches are invalidated) |
| `self_test()` | `1F 40`, then `initialize()` | |
| `set_vertical_scroll(on)` | `1F 02` on / `1F 01` off | hidden in the UI (`SHOW_HW_SETTINGS = false`) |
| `select_code_page(p)` | page 0 only → `1B 74 00`; anything else raises `ValueError` | hidden in the UI; the daemon already logs and continues |
| `start_ticker(text)` | writes the first 20 chars to the top row | the HP has no 45-char hardware ticker; marquee mode is hidden in the UI |

### Parked glyph codes

In EPSON mode a user glyph is defined **at a printable character code**. While
the user set is on, that code draws the bitmap instead of the character. The 9
slots park on characters check-out rarely shows:

| slot | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| code | `` ` `` 60 | `{` 7B | `|` 7C | `}` 7D | `~` 7E | `^` 5E | `\` 5C | `[` 5B | `]` 5D |

In the HP's sanitize step, the logical codes `0x15–0x1E` become the parked codes.
Real occurrences of a parked character in text (a `[` in a headline) become a
**lookalike**, so they never draw a glyph by accident:
`` ` ``→`'`, `{ [`→`(`, `} ]`→`)`, `|`→`!`, `~`→`-`, `^`→space, `\`→`/`.
Everything else outside printable ASCII becomes `?`, as on the IBM.

### Glyph bitmap encoding (assumed — bench check 2)

Epson convention: **one byte per column, left to right, bit 7 = top row**, so
column `c`'s byte = Σ over rows r=0..6 of `((rows[r] >> c) & 1) << (7 - r)`. The
public API stays 7 editor rows (low 5 bits = columns 1..5). If the glass shows
the glyph flipped or shifted, the fix is this one function.

## Status and UI

- `status.json` gains `"display": "ibm" | "hp"` and `"display_label"`, from the
  driver's `DISPLAY` and `LABEL`. Both stay in `status_defaults()` for the web
  server's fallback.
- `VfdPreview.svelte`: the hardcoded tag `IBM SUREPOS 2×20 VFD` reads
  `status.display_label`. It falls back to the IBM label when the field is absent
  (an older daemon).
- **Known limitation:** the preview draws every character with the IBM's font,
  decoded from photos. The HP's built-in font differs slightly. Custom glyphs
  (weather labels, pacman, spectrum bars, news bars) are drawn from their own
  bitmaps, so they preview exactly. Photographing the HP's font is out of scope.

## Setup on dad: a second instance, `deploy/bench-hp.sh`

A foreground script. It is **not installed** and touches none of the user units.
It sets:

```
CHECKOUT_DISPLAY=hp
CHECKOUT_PORT=<HP by-id path; the first by-id entry whose USB vendor is 03f0, or an argument>
CHECKOUT_STATE_PATH / STATUS_PATH / LIBRARY_PATH / DEVICES_PATH = bench-hp/*.json
CHECKOUT_SPECTRUM_SOCK=$XDG_RUNTIME_DIR/checkout-spectrum-hp.sock
```

It then runs the daemon, `audioviz` and `uvicorn` on **port 8001** together, and
Ctrl-C stops all three. `bench-hp/` is gitignored. The IBM instance keeps port
8000 and its own files. Two `audioviz` processes both tapping the PipeWire
monitor is fine.

## work: install

1. `deploy/install.sh` takes `--display ibm|hp` and `--port PATH`. It writes
   `~/.config/checkout/env` with `CHECKOUT_DISPLAY` and `CHECKOUT_PORT`.
   `checkout-daemon.service` gains `EnvironmentFile=-%h/.config/checkout/env`.
   The leading `-` means a missing file is fine, so dad's existing install keeps
   its defaults.
   - With no `--display`, it writes no env file, so the defaults (`ibm`,
     `/dev/ttyUSB0`) apply and dad's reinstall behaves exactly as today.
   - With `--display` but no `--port`, the installer picks the one `/dev/serial/by-id` entry if
     there is exactly one. Otherwise it stops and lists the entries.
   - The units still carry **no** ordering between each other (v1.3.1).
2. work prerequisites, in order: clone the repo, create `.venv` and pip-install the
   three requirements files, **`sudo usermod -aG uucp matt` then log in again**
   (Matt runs this; sudo on work needs his password), plug in the HP, then run
   `deploy/install.sh --display hp`.
3. **Audio at work:** PipeWire on work currently has only `auto_null`, a dummy
   output. Spectrum shows flat bars until audio plays through a real output
   device. That is a property of the desk, not the code.

## Bench checks (run on dad, in order, before work)

1. **Mode + init:** the welcome message stops and `show()` draws both rows in the
   right place (1-based `1F 24`).
2. **Glyph bit order:** define a glyph with a lone pixel at the top-left and one
   at the bottom-right. Confirm it is not flipped or shifted.
3. **Cursor stays hidden** after `1F 43 00` across later writes. If it does not,
   `show`/`show_changes` end with `1F 43 00`, as the IBM ends with `0x14`.
4. **Brightness** `1F 58 1..4` gives four visibly distinct levels.
5. **`0C` keeps glyph definitions** (flash animation blanks, then redraws).
6. **Spectrum frame rate:** 48-byte full frames at 9600 baud cap near 20 fps,
   the same class as the IBM. Check that the bars keep up.
7. **Every mode by eye** on the HP through the 8001 UI: clock, message, dynamic
   (each colon style, pacman duo and solo, news alert with flash and throb),
   spectrum (every layout), glyph editor.

## Testing

- `tests/test_driver_epson.py`, byte-exact in dry-run: init, `show`, the 1-based
  cursor, `show_changes` runs and merge gap and full-frame fallback, brightness
  mapping, glyph column encoding, the logical→parked code map, lookalike
  substitution, and that a control byte can never escape.
- `tests/test_displays.py`: the registry, an unknown `CHECKOUT_DISPLAY` rejected,
  and both drivers exposing the same public methods (so a new method on one
  cannot be forgotten on the other).
- The daemon tests gain a case: after a glyph define the daemon calls
  `glyphs_loaded()`, not `initialize()`. Existing IBM byte tests must pass
  unchanged, which proves nothing moved for dad.
- `tests/test_deploy.py`: `EnvironmentFile=-%h/.config/checkout/env` present; the
  installer writes the env file and never enables lingering; `bench-hp.sh` is
  executable and passes `bash -n`.
- UI vitest: the preview tag shows `display_label`, with the IBM fallback.

## Docs

- `docs/hardware.md` gains an **HP LD220-HP** section: the bench facts, the byte
  plan, the parked codes, and each bench-check result once confirmed.
- `CLAUDE.md`: the overview names both displays; the architecture list adds
  `driver_epson.py` and `displays.py`; `CHECKOUT_DISPLAY` joins the env list;
  "How to run" adds `bench-hp.sh` and `install.sh --display`. Credit the OEM
  manual.
- `README`: a line on choosing the display.

## Out of scope

- The in-UI display dropdown, and one daemon driving two displays.
- The HP's other command modes (LOGIC, UTC, native LD220). check-out requires EPSON
  mode, which is the factory default, and says so in `docs/hardware.md`.
- Photographing the HP's font for the preview.
- A hardware ticker on the HP (marquee stays hidden).
