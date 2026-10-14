# check-out

A salvaged **IBM SurePOS 500** customer display, turned into a self-hosted status
board and a real-time **stereo spectrum analyzer**. The display is the till-side
screen that shows shoppers their total: a Futaba **M202MD10C** vacuum-fluorescent
display (VFD), blue-green, 2 lines × 20 characters. No public datasheet exists for
it. Everything here was recovered from one published command set and
**bench-confirmed on the actual unit**.

A long-running daemon drives the display over a **write-only 9600-baud serial
link**. A web control panel, an audio process and a keypad service are optional
extras. The constraint — two lines, twenty characters — is the aesthetic.

Since v1.8.0 it also drives an **HP LD220-HP** pole display (USB, Epson command
set), with every feature intact. Each machine runs one display, chosen with
`CHECKOUT_DISPLAY`. See [HP LD220-HP](#hp-ld220-hp-second-display).

![The check-out web control panel. Top left, the preview of the IBM display reads
"10/14/26 WED 11:52" over Chicago's high, low, current temperature and rain. Below
it, the glyph editor and the glyph library. On the right, the Control panel in
dynamic mode with the pacman time feature and news alerts on, then Saved
messages.](docs/screenshot.png)

*The web control panel, driving the IBM in dynamic mode (weather for Chicago).*

> This README is the full reference: the physical build, the protocol, the
> architecture, and — most valuable — the **bench findings**, the "why" that no
> datasheet holds. If you have the same salvaged display, start here. The internal
> spec is [`spec.md`](spec.md); conventions for working on the code are in
> [`CLAUDE.md`](CLAUDE.md); hardware detail is in [`docs/hardware.md`](docs/hardware.md).

---

## What it does

Four display modes, picked in the web panel or with the bump bar:

- **Clock** — `DD MON YYYY` over `HH:MM:SS AM/PM`. Locale-independent, ticks once a
  second without flicker.
- **Message** — your text. Each row shows the message or the clock, and each row
  can scroll left or right at its own speed. A single line with nothing scrolling
  word-wraps across both rows.
- **Spectrum** — a real-time audio analyzer of what's playing (or a microphone), in
  three layouts × two styles. See [Spectrum analyzer](#spectrum-analyzer-optional).
- **Dynamic** — a weather clock: date and time over the next 24 hours' high, low
  and rain, plus the current temperature. The time's colon is animated, and news
  headlines can break in as alerts. See [Dynamic mode](#dynamic-mode-weather--news).

Across all modes:

- **Custom glyphs** — the display holds 9 user-drawn 5×7 characters. A glyph
  editor draws them, a library saves any number, and `{g0}`..`{g8}` places them
  in text.
- **Brightness and animation** — four brightness levels; `flash`, `blink` and
  `pulse` effects.
- **Web control panel** — a Svelte app over a FastAPI backend, with a
  **pixel-accurate live preview** of the glass.
- **Bump bar** (v1.9.0) — a salvaged 10-key kitchen keypad controls the board and
  the desktop. See [Bump bar](#bump-bar-tg3-m4220).

Kept but hidden from the panel: the display's own **hardware marquee** (top row
only, one fixed speed) and its 12 **code pages** (alternate character sets).
Both still work; the panel just doesn't offer them.

---

## Architecture

Four cooperating processes. They share only files, one socket and the web API.
The **daemon is the only process that opens the serial port.**

```
  browser ◄──HTTP──► WEB  (web/app.py, :8000)  ◄──HTTP──  BUMP BAR service
                      │                ▲                 (checkout.bumpbar)
           writes state.json    reads status.json
                      ▼                │
               ┌──────────────────────┴────────────────┐
 Open-Meteo ◄──┤ DAEMON  (checkout.daemon)             │   9600 8N1, write-only
 news feeds ◄──┤ one ~30 Hz loop: state.json → frame → ├──► SERIAL ──► VFD 2×20
 (background   │ renderer → driver; writes status.json │
  threads)     └──────────────────────▲────────────────┘
                                      │ unix datagram socket (newest frame wins)
               ┌──────────────────────┴────────────────┐
               │ AUDIOVIZ  (checkout.audioviz)         │
               │ parec capture → FFT → bands → socket  │
               └───────────────────────────────────────┘
```

**Why it's split this way:**

- **One serial owner.** Two writers on the 9600-baud port would interleave their
  bytes and corrupt every frame. So only the daemon opens it, with an exclusive
  lock. Everyone else changes the display by *writing `state.json`*, which the
  daemon reads each loop.
- **Each file has one writer.** The web writes `state.json`; the daemon writes
  `status.json`, a mirror of the glass plus health. Neither writes the other's
  file, so there are no locks and no races. The bump bar service never writes
  `state.json` either: it calls the same web API the panel uses.
- **Audio has its own process and socket.** Spectrum data is ~21 frames a second
  of bar heights — far too much for `state.json`. It travels over a **unix
  datagram socket** (a local, message-at-a-time socket); the daemon keeps only the
  newest frame, so a slow reader never lags the glass. Audio can crash, restart or
  be absent without touching the serial port.
- **Network calls never block the loop.** Weather and news are fetched by
  background threads inside the daemon; the loop only reads their latest result.

---

## Hardware

The physical build, **measured on this exact unit** (full survey in
[`spec.md`](spec.md) §1). This section and the protocol notes are the IBM. The HP
has its own section: [HP LD220-HP](#hp-ld220-hp-second-display).

### The display
- **Unit:** IBM SurePOS 500 customer display, **P/N 15K2012** (iron-gray housing).
- **VFD board:** Futaba **M202MD10C** family — 2 lines × 20 characters, blue-green.
  No public datasheet; the protocol was recovered (see below).
- **Cable:** IBM genuine **54Y2454** (RJ-to-DB9, 1 m) — the matched SurePOS 500
  harness. The display end is the RJ jack ("port 4"); the host end is DB9.

### The interface ("injector box")
A sealed box: a USB cable to the host on one side, a 12 V barrel jack on the
other. Inside are a USB-to-RS-232 adapter and the power wiring.

- **Adapter:** an **OIKWAN USB-to-RS-232 (DB9 male, FTDI FT232R)**, USB id
  `0403:6001` → `/dev/ttyUSB0`. The display takes **true RS-232 directly**: no
  MAX3232, level shifter or signal inversion (bench-confirmed).
- **Power:** a 12 V 1 A regulated supply (5.5×2.1 mm, center-positive), with an
  inline 1 A fuse on the +12 V line.
- **Enclosure:** 2× panel-mount DB9-female screw-terminal breakouts (one for the
  cable, one for the adapter) in a Hammond 1591C ABS box; 22 AWG wire.

### DB9 pinout (bench-confirmed on this cable — the generic RS-232 chart is *wrong* for pins 7/8)

| DB9 pin | Measured                | Use                                                        |
|---------|-------------------------|------------------------------------------------------------|
| 1       | **+11.75 V back-feed**  | ⚠️ **HAZARD — leave unconnected** (it sources voltage)      |
| 3       | ~163 mV steady idle     | **DATA** — host TX → here                                  |
| 5       | 0 V                     | **GND**                                                    |
| 8       | +11.75 V                | **+12 V power in**                                         |

Final wiring: **pin 3 = DATA, pin 5 = GND, pin 8 = +12 V, pin 1 open.** The two
breakouts join DATA (3↔3) and GND (5↔5), and fused +12 V feeds cable pin 8. All
grounds are common.

> **⚠️ Bench finding — the back-feed hazard.** On this cable **pin 1 pushes ~12 V
> *back* through the harness** (it's the "display present" detect line). Wiring
> it can **destroy your adapter's TX pin.** Wire only pins 3, 5 and 8.

### The serial link
- **Write-only, 9600 8N1.** The host never reads from the display.
- **Bench finding — 9600 is the ceiling.** Treat it as a hard cap. The renderer
  and frame rate are designed around ~960 bytes a second: a full 40-cell frame
  takes ~40 ms on the wire, so ~21 frames a second is the practical limit.

---

## Protocol notes (IBM)

Single-byte control codes — **not** ESC/POS, the common receipt-printer language
(`0x1B 0x40` printed a literal "@"). The command table comes from the
[SNMetamorph `FutabaVfdM202MD10C`](https://github.com/SNMetamorph/FutabaVfdM202MD10C)
source (our exact board), **bench-confirmed**. `driver.py` (IBM) and
`driver_epson.py` (HP) are the only code that emits bytes.

| Command                 | Bytes                                   |
|-------------------------|-----------------------------------------|
| Extended mode           | `0x00` + `0x01` enable / `0x00` disable |
| Select code page        | `0x02` + page byte (12 pages)           |
| Define character        | `0x03` + code + 7 row bytes + `0x00`    |
| Dimming / brightness    | `0x04` + `0x20`/`0x40`/`0x60`/`0xFF`    |
| Print ticker text       | `0x05` + text + `0x0D` (hardware marquee) |
| Backspace               | `0x08`                                  |
| Self test               | `0x0F`                                  |
| Set cursor position     | `0x10` + position byte                  |
| Disable vertical scroll | `0x11`                                  |
| Enable vertical scroll  | `0x12`                                  |
| Cursor on / off         | `0x13` / `0x14`                         |
| Reset                   | `0x1F`                                  |
| Write text              | printable ASCII (cursor auto-advances)  |

### Mandatory init — extended mode is everything
Every open and every reconnect sends:

```
0x1F            reset
0x00 0x01       enable extended mode   ← the missing piece
0x11            disable vertical scroll
```

> **Bench finding — the whole early saga was a missing init.** Without
> `0x00 0x01` + `0x11`, the display **scrolls up when the bottom-right cell is
> written**. Early versions invented a "39-cell limit", a "`0x27` phantom scroll",
> a glyph-anchor rule and a "no leading clear" rule to work around it. *All of them
> were side effects of never enabling extended mode.* With the init, **all 40
> cells are writable** and the position is plain `column + row*20`.
> `VFDDriver.initialize()` sends exactly these bytes.

### Addressing and writes
- Top line `0x00`–`0x13` (0–19), bottom line `0x14`–`0x27` (20–39).
- **Cursor-off must be last.** `0x14` hides the cursor, but *any* later write shows
  it again. So `0x14` ends every write.
- **Only changed cells are sent** (v1.4.0). When the daemon knows what the glass
  shows, it sends `0x10 pos <bytes>` for each run of changed cells, then one
  `0x14`. A one-cell change is 4 bytes instead of 45. If that would be longer than
  a full frame, it sends the full frame — always as one buffered write, so nothing
  flickers.
- **Four brightness levels** (bench-confirmed in extended mode):
  `0x04` + `0x20`/`0x40`/`0x60`/`0xFF`, applied live. Brightness is display-wide;
  there is no per-cell dimming.

### User glyphs — 9 non-contiguous slots
Codes **`0x15 0x16 0x17 0x18 0x19 0x1A 0x1C 0x1D 0x1E`** (slot 0..8; `0x1B` is
skipped). Define with `0x03 <code> <7 rows> 0x00`; show by writing the code byte.
Each row byte holds 5 dots in its low 5 bits; the driver shifts them left by 3
because the panel reads bits 3–7.

> **Bench finding — the whitespace-glyph trap.** Glyph codes **`0x1C`/`0x1D`/`0x1E`
> are ASCII control characters that Python's `str.split()` treats as whitespace.**
> A plain `split()` on rendered text silently drops them (this lost slots 6–8 in
> v0.5.x). **Split on the space character (`" "`) only**, and count a `{gN}` as
> exactly one cell.

> **Bench finding — the cursor is an underline.** The glass has a separate bar
> under each cell for the cursor. It can't serve as a per-cell effect: it lights
> only at the cursor, and every redraw sweeps it across the glass.

### The hardware marquee is deliberately limited
The built-in ticker (`0x05` + text + `0x0D`) scrolls on its own, but:

> **Bench finding — the hardware can't scroll and show a live clock.** The ticker
> runs on the **top row only**, at **one fixed speed** (bench probes found no
> speed setting), with a **45-character buffer**, and loops. **Any write to the
> bottom row mid-scroll stops it.** So a scrolling top row over a per-second clock
> is **impossible in hardware** — don't retry it. Message mode's software scroll
> exists for exactly that case, which is why the marquee is hidden.

---

## HP LD220-HP (second display)

An **HP LD220-HP** pole display: the same 2×20 blue-green VFD format, with its
own command set. It is another machine's display (IBM on one desk, HP on
another), not a second screen on one daemon. `CHECKOUT_DISPLAY=hp` picks
`EpsonDriver` (`checkout/driver_epson.py`); everything above the driver —
frames, panel, spectrum, weather, news — is shared unchanged.

### The unit
- **USB, no adapter box:** a Prolific PL2303 chip inside, USB id **`03f0:3524`**,
  kernel `pl2303` driver → `/dev/ttyUSB*`. 9600 8N1, write-only in practice.
- **Powered by the USB port alone** (the manual rates it 5–12 V). No 12 V supply.
- **The VFD's maker is unknown.** HP never named it, and the manual's tube spec
  says only "5 x 7 Dot Matrix".
- **The command mode is stored in the display** and only HP's Windows setup
  utility changes it. check-out needs **EPSON**, the factory default. The
  power-on self-test shows it: `EPROM OK · PASST: NONE · FW 6.6 · RS232 9600,N,8,1 ·
  COMMAND EPSON · CHAR USA/EUROPE`, then a scrolling welcome message.

### Protocol notes (Epson mode)
Escape-prefixed commands from the OEM "VFD LD220 User Manual V2.3" §4.1.2,
corrected on the bench. Full table in [`docs/hardware.md`](docs/hardware.md).

| Command | Bytes |
|---|---|
| Init (also **erases user glyphs**) | `1B 40` |
| Overwrite mode / cursor off | `1F 01` / `1F 43 00` |
| Move cursor (**1-based**) | `1F 24 col row` |
| Brightness (4 levels) | `1F 58 1..4` |
| Define all 9 glyphs | `1B 26 01 30 38` + 9 × 5 column bytes |
| User glyphs on / off | `1B 25 01` / `1B 25 00` |
| Clear | `0C` |

The cursor stays hidden after one `1F 43 00`, so writes need no trailing
cursor-off (the IBM needs `0x14` after every write).

### User glyphs — the manual is wrong three ways

> **Bench finding — no width byte.** The manual's `[a(p1..p5)] … a=5` reads like a
> `05` before each glyph's five column bytes. The unit takes that `05` as column 1.

> **Bench finding — bit 0 is the top row** of each column byte (Epson's own
> displays use bit 7). Tested with an `F` glyph, which looks wrong under any flip
> or mirror.

> **Bench finding — every define replaces the whole set.** Nine one-glyph defines
> left only the last glyph. So the driver keeps all nine bitmaps and sends them in
> **one** command at the codes `'0'..'8'`.

> **Bench finding — "glyphs on" applies per written character.** Text written with
> the set off stays plain after it is switched back on. So the driver turns glyphs
> on only around glyph cells and off before any real digit. Nothing is lost:
> `[ ] | ~` and `2026` print as themselves.

### Annunciators — on the glass, but dead

> **Bench finding — the extra shapes can't be lit** (2026-10-14, firmware 6.6).
> The glass carries triangles and other shapes besides the character cells. The
> manual's commands for them — `1F 23` (annunciator on/off) and `1F 2E`/`2C`/`3B`
> (period, comma, semicolon) — are accepted, but light nothing. The firmware takes
> annunciator columns 0–10 only (the manual says 0–20); a column of 12 is the byte
> `0C`, which is read as "clear screen". **Never send these.** Probe log in
> [`docs/hardware.md`](docs/hardware.md).

All seven HP bench checks passed on 2026-09-28: rows, glyph format, hidden cursor,
four brightness levels, glyphs surviving a clear, spectrum speed ("just like the
IBM"), and every mode by eye.

### Setting up a machine with the HP
```bash
sudo usermod -aG uucp "$USER"             # serial access (see Serial permissions)
python -m venv .venv && .venv/bin/pip install -r requirements.txt \
    -r web/requirements.txt -r requirements-audio.txt
deploy/install.sh --display hp            # finds the one serial device; panel on :8000
```
`install.sh --display` writes `~/.config/checkout/env` (`CHECKOUT_DISPLAY`,
`CHECKOUT_PORT`), which the daemon's service reads. With two USB-serial devices
plugged in, pass `--port /dev/serial/by-id/...`: `ttyUSB0` and `ttyUSB1` can swap
at boot.

**Testing both on one machine:** `deploy/bench-hp.sh` runs a temporary HP
instance (daemon, audio and panel on **:8001**, its own files under `bench-hp/`)
next to the installed IBM. It refuses to start until the installed daemon uses a
by-id port. Ctrl-C stops it.

**Known limit:** the preview draws text in the IBM's font (decoded from photos);
the HP's font differs slightly. Glyphs preview exactly.

---

## Bump bar (TG3 M4220)

A **TG3 KBA-M4220A** 10-key "bump bar" — the keypad a kitchen uses to clear orders
off a screen — connected over its RJ45-to-USB cable. To Linux it is a plain USB
keyboard typing `a`–`j`. The `checkout-bumpbar` service **grabs** it (takes it
exclusively), so no key reaches the desktop, and turns each key into an action.

| Key | Tap | Grey key, then this key |
|---|---|---|
| DECREASE / INCREASE | brightness − / + | volume − / + |
| PREVIOUS / NEXT | previous / next mode | previous / next track |
| PRINT | the mode's style: animation (clock, message), layout (spectrum), time feature (dynamic) | screenshot → clipboard |
| ROTATE PAGES | the mode's option: next saved message (message), bars/line (spectrum), half speed (dynamic) | next audio output |
| TOGGLE SCREENS | blank / unblank | mic mute |
| RECALL | play the latest news alert — or cancel one that is playing | lock screen |
| SERVE | open the last headline | play / pause |

**The grey key is a one-shot shift, not a held one.** The bar sends every key as
an instant tap — down and up within ~40 ms, however long it is held — so a held
key is invisible. Tap grey, then a key within 3 seconds. Volume and brightness
steps keep the shift armed, so grey then DECREASE ×3 is three volume steps. Tap
grey twice to cancel.

**Mounted upside down.** Our bar is rotated 180° (ports on top), so the map sends
each key's code to the key diagonally opposite.

**Remap** at `http://127.0.0.1:8000/#/bumpbar` (the **bump bar** link in the
header appears only on a machine where the service has run). The page draws the
pad in its real key colours, lists each key's two actions, and flashes a key when
you press it on the bar. It offers a fixed list of actions — never a typed
command, since any local program, and any web page in the browser, can reach the
API.

**Setup on a machine with a bar:**

```bash
deploy/install.sh --bumpbar     # adds checkout-bumpbar, installs evdev
sudo install -m 644 deploy/udev/70-checkout-bumpbar.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger --subsystem-match=input
```

The udev rule gives the logged-in user access to **this device only**. Joining the
`input` group instead would let every program read every keyboard. The switch on
the bar's edge only changes which letters the keys send (`a`–`j` or `k`–`t`); both
work. Bench facts (key codes, ports, the firmware's manager mode) are in
[`docs/hardware.md`](docs/hardware.md).

---

## Quick start (the daemon)

```bash
# 1. Install (a virtualenv is recommended)
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# 2. No hardware — print the outgoing bytes as hex
python -m checkout.daemon --dry-run

# 3. Live against the display
python -m checkout.daemon

# 4. Write a single frame, then exit (it stays on the glass) — handy for hardware tests
python -m checkout.daemon --once
```

You should see the date on the top line and a ticking `HH:MM:SS AM/PM` below it.

**The fast loop.** The daemon runs one loop at ~30 Hz (`CHECKOUT_LOOP_HZ`). Each
pass it checks `state.json`'s modified time and re-reads the file only when it
changed, works out the current frame, and writes to the port **only when the frame
changed**. So a still screen costs nothing, while `spectrum` gets its full frame
rate from the same code. `status.json` is written ~6 times a second
(`CHECKOUT_STATUS_HZ`).

> **Bench finding — wait for each write to drain, or it lags.** The port is
> non-blocking, so a bare `serial.write()` only drops bytes into the operating
> system's send buffer. The loop rendered ~30 frames a second but the wire carries
> ~21, so frames piled up in that buffer until it was full (~1–1.5 s), and the glass
> always showed frames that old — the spectrum trailed the music by 1–2 s. **Fix:
> `flush()` / `tcdrain()` after every write.** The daemon now waits until its bytes
> are on the wire, which paces it to the real 9600-baud speed.

---

## Web control panel (optional)

A Svelte single-page app served by FastAPI. **FastAPI never opens the serial
port** — it only reads `status.json` and writes `state.json`, using the daemon's
own `checkout.state` code so the format always matches.

Two pages:

- **Display** (`#/`) — left column: the live preview (a SurePOS-style black housing
  of phosphor dots, footed by make · model and a live/offline light), the glyph
  editor, and the glyph library. Right column: **Control** (the mode and its
  settings, then brightness and blank, with Self-test and Reset in its header),
  then **Saved messages**. The preview is drawn from `status.json`, so it mirrors
  the real glass: the clock ticking, brightness, blank, glyphs and spectrum bars.
- **Bump bar** (`#/bumpbar`) — the keypad map; see [Bump bar](#bump-bar-tg3-m4220).

```bash
pip install -r web/requirements.txt
( cd ui && npm install && npm run build )         # build the Svelte app -> ui/dist
uvicorn web.app:app --port 8000 --no-access-log   # serves the panel + /api
```

`--no-access-log` keeps the console quiet: the panel polls `/api/status` about
twice a second. For development: `uvicorn web.app:app --reload --no-access-log`
plus `cd ui && npm run dev` (Vite passes `/api` through to FastAPI).

---

## Dynamic mode (weather + news)

**The top line** is the date and time, `10/14/26 WED 11:52` (12-hour). **The
bottom line** is four labelled fields — **H**igh, **L**ow, **C**urrent and **R**ain
— each label a hand-drawn inverted glyph: `[H] 62° [L] 56° [C] 62° [R].02"`. High,
low and rain (inches) cover a **rolling 24 hours from now**, not the calendar day.
A field shows ` --` when its data is missing or over an hour old. Both lines are
always centered.

**Weather** comes from [Open-Meteo](https://open-meteo.com/): one small request,
no API key, for the latitude and longitude set in the panel. A background thread
fetches once per Open-Meteo update (every 15 minutes), only while dynamic mode is
on, and retries from 60 s up to 15 minutes on failure.

**Time features** animate the colon, locked to the wall clock (half speed is an
option):

| Feature | The colon cell |
|---|---|
| `on` | a steady `:` |
| `tick` | `:` then blank, once a second |
| `twinkle` | a star: dot, diamond, four corner dots, and back |
| `pulse` | the colon's two dots, then a taller centre column |
| `pacman` | a different layout: the date and time on the left, and in the last two cells pacman eating a ghost, a heart or another pacman. **Solo** shows the chosen sprite alone; it switches on by itself when the date and time fill the line |

The first four end the line with an AM or PM glyph.

**News alerts** (optional) pick **topics**, each backed by fixed feeds:
**tech** = NYT Technology, BBC Technology and Phoronix; **politics** = NYT
Politics; plus a **local** topic backed by a regional news site. Every few minutes (`Check`, default
2) the daemon reads each feed's **lead story**. A new lead becomes an alert: the
top line shows `NEWS ALERT` between bar glyphs, and the bottom line scrolls
`OUTLET: headline` in from the right, then the screen returns to the weather.
Panel settings:

- **Gap** (default 10 min) — at most one alert per gap. A lead that arrives
  inside the gap waits, and the newest plays when the gap ends. Nothing new means
  nothing shown.
- **Speed** — the scroll step in ms. **Repeat** — extra passes of the headline.
- **Flash** — `none`, `3x` or `continuous` brightness effect on the alert.
- **Show latest** — plays the newest lead now.

Headlines are cleaned to ASCII. The feeds are parsed with Python's standard XML
parser on purpose: expat ≥ 2.4.1 refuses "entity bomb" and external-entity
attacks (tests pin this). `/api/status` exposes the last headline played
(`news_shown`: outlet, title, link, time), so other tools — a status bar, the bump
bar's SERVE key — can open it.

---

## Spectrum analyzer (optional)

A real-time audio analyzer at ~21 frames a second. A **separate process**
(`python -m checkout.audioviz`) captures audio, runs an FFT (the math that splits
sound into frequencies), and streams frames to the daemon over the unix socket.
Capture runs only while the mode is `spectrum`.

```bash
pip install -r requirements-audio.txt   # numpy + sounddevice (PortAudio)
python -m checkout.audioviz --list      # list devices -> devices.json
python -m checkout.audioviz             # capture + stream to the daemon
```

Then set the mode to `spectrum` and pick a **source**:

- **`system`** — what's playing, via the PipeWire/PulseAudio **monitor** of the
  default output (a monitor is a recording of an output).
- **`mic`** — the default (or chosen) input; falls back to `sounddevice`/PortAudio
  if PulseAudio is absent.

The **Device** list is short on purpose: "Auto" plus the real monitors (system) or
inputs (mic), labelled; no raw ALSA hardware nodes.

**Volume doesn't matter (auto-gain).** Bars scale against recent overall loudness,
so they fill the display based on the *music*, not the system volume. A silence
floor lets them fall flat instead of amplifying hiss. **Sensitivity** biases the
auto-gain; **Smoothing** sets how slowly bars fall (0 = snappy). Spectrum borrows
the 9 glyph slots for its bar shapes and restores your glyphs when you leave.

**System packages (Arch):** `pipewire-pulse` (`pactl` / `pw-record`) and
`portaudio` (mic fallback / `sounddevice`).

### Layouts and styles

The **style** (Bars / Line) and **layout** (Full / Stereo-V / Stereo-H) are
independent.

| Layout       | Top row / bottom row                      | Resolution                          |
|--------------|-------------------------------------------|-------------------------------------|
| **Full**     | one mono spectrum across both rows        | 20 bands, double height (0..14)     |
| **Stereo-V** | LEFT spectrum / RIGHT spectrum            | 19 bands each, one cell tall (0..7) |
| **Stereo-H** | LEFT level meter / RIGHT level meter      | 19 cells × **5 columns = 95 steps** |

- **Bars** fill solidly up to the level; **Line** lights only the peak — one row
  (vertical) or one gliding **column** (horizontal, 5 per cell = 95 fine steps).
- **Inverted L/R labels.** Cell 0 of each stereo row is a hand-drawn inverted
  glyph (lit frame, dark letter), so it reads as a label, not a bar.
- **Shared auto-gain, on purpose.** Left and right scale against **one** reference
  (the loudness of both channels), so a louder channel *looks* louder and you can
  **see the stereo balance**. Separate gain per channel would hide it.
- **Tagged socket frames.** Each datagram is `byte 0 = layout tag` + that layout's
  data: `full` → 20 heights, `stereo_v` → 19 + 19, `stereo_h` → 2 levels. A
  malformed or mid-switch frame decodes to `None` and the daemon skips it.
- **The 9-glyph budget.** full = 7 height glyphs; stereo_v = 7 + L + R = 9 (exact
  fit); stereo_h = 5 column glyphs + L + R = 7. The daemon redefines the slots
  whenever the layout *or* style changes.

### Bench findings — the spectrum latency saga

For several releases the spectrum "popped to the top and fell to zero ~2× a second,
1–2 s late." It *looked* like a DSP (signal-processing) bug every time. **The DSP
was correct all along** — each cause was in capture or transport, found by
measuring directly, not by reading docs. In order of discovery:

- **`pw-record` / `pw-cat` starve a pipe.** Piped from a monitor, they deliver
  *one* good buffer, then near-silence (RMS ~0.00003, where RMS is average
  loudness). **`parec` keeps going** (~0.2). So capture tries `parec` first and
  `pw-record` only as a fallback. (PortAudio's ALSA backend can't see monitors *at
  all* — that's why system audio uses native capture.)
- **`parec` buffers in bursts.** Without a latency hint, `parec` holds ~750 ms and
  releases audio in **bursts** (gaps up to ~2000 ms). With **`--latency-msec=10`**
  the gaps are a steady ~21 ms. Those bursts *were* the pop-and-drop and the delay.
- **Serial backlog.** Writes piled up in the operating system's send buffer (see
  the [fast loop](#quick-start-the-daemon) finding). **Fix: drain after each
  write.**

**The lesson:** measure at the boundary. Each of these posed as a DSP bug across
several releases; a `parec | hexdump` and a loudness print found them in minutes.

**The latency floor (don't chase it).** A small delay remains: the FFT window, the
monitor tap (which sits *after* the speakers' output), `parec` and the serial
link. It's ~70–90 ms on the bench and **can't be removed**; it's physics, not a bug.

**Tuned defaults** (in `audioviz.py` / `config.py`): `PAREC_LATENCY_MS = 10`,
`BLOCK = 256` (FFT frame), `LOOP_HZ = 30`.

---

## Configuration (env vars)

| Variable                       | Default                                   | Purpose                                 |
|--------------------------------|-------------------------------------------|-----------------------------------------|
| `CHECKOUT_DISPLAY`             | `ibm`                                     | which display: `ibm` or `hp`            |
| `CHECKOUT_PORT`                | `/dev/ttyUSB0`                            | serial device (use a `/dev/serial/by-id/` path) |
| `CHECKOUT_BAUD`                | `9600`                                    | baud rate (the hard cap — see above)    |
| `CHECKOUT_LOOP_HZ`             | `30`                                      | daemon loop rate (Hz)                   |
| `CHECKOUT_STATUS_HZ`           | `6`                                       | `status.json` write rate (Hz)           |
| `CHECKOUT_TICK_MS`             | `250`                                     | legacy per-tick sleep (kept for `--once`) |
| `CHECKOUT_STATE_PATH`          | `./state.json`                            | web writes, daemon reads                |
| `CHECKOUT_STATUS_PATH`         | `./status.json`                           | daemon writes, web reads                |
| `CHECKOUT_LIBRARY_PATH`        | `./library.json`                          | saved messages and glyphs (web only)    |
| `CHECKOUT_SPECTRUM_SOCK`       | `$XDG_RUNTIME_DIR/checkout-spectrum.sock` | audioviz → daemon socket                |
| `CHECKOUT_DEVICES_PATH`        | `./devices.json`                          | listed audio devices (audioviz)         |
| `CHECKOUT_UI_DIST`             | `ui/dist`                                 | built panel directory (web only)        |
| `CHECKOUT_BUMPBAR_PATH`        | `./bumpbar.json`                          | the key map (web writes, service reads) |
| `CHECKOUT_BUMPBAR_STATUS_PATH` | `./bumpbar-status.json`                   | bump bar service status                 |
| `CHECKOUT_BUMPBAR_DEVICE`      | `/dev/input/by-id/usb-Heng_Yu_Technology_M4220-event-kbd` | the bar's input device |
| `CHECKOUT_API`                 | `http://127.0.0.1:8000`                   | where the bump bar service reaches the web API |
| `CHECKOUT_DEBUG_TX`            | _(unset)_                                 | `=1` hex-logs every serial write        |

Everything else — mode, message, brightness, animation, spectrum and audio
settings, glyphs, weather location, news — lives in `state.json` and is set from
the panel. The keys and their defaults are listed, with comments, in
`checkout/state.py`.

---

## Serial permissions

Your user must be in the serial device's group (on Arch, `uucp`):

```bash
sudo usermod -aG uucp "$USER"   # then log out and back in
```

**The services won't see the new group after a plain re-login.** They run under
the systemd user manager, which keeps the groups it started with until every one
of your sessions ends. Until then, this lets the daemon in (lost on unplug or
reboot):

```bash
sudo setfacl -m u:$USER:rw /dev/ttyUSB0
```

`deploy/install.sh` prints both lines when you're missing the port's group.

---

## Running as a service (start on login)

`deploy/` installs check-out as **systemd _user_ services** that start when you
log in:

| Service | Runs | Role |
|---------|------|------|
| `checkout-daemon`   | `python -m checkout.daemon`   | owns the serial port, drives the glass |
| `checkout-audioviz` | `python -m checkout.audioviz` | audio capture + FFT → spectrum bars |
| `checkout-web`      | `uvicorn web.app:app …`       | serves the panel + API on `http://127.0.0.1:8000` |
| `checkout-bumpbar`  | `python -m checkout.bumpbar`  | only with `--bumpbar`: the keypad |

```bash
deploy/install.sh      # build the panel if needed, install + enable + start
deploy/install.sh --display hp [--port /dev/serial/by-id/...]   # this machine has the HP
deploy/install.sh --bumpbar    # also install the bump bar service
deploy/bench-hp.sh     # temporary HP instance on :8001 next to the installed one
deploy/uninstall.sh    # stop, disable, remove the unit files
```

The installer finds the repo from its own location and fills it into the unit
templates (`deploy/systemd/*.service`), so nothing personal is committed — the
units ship with a `__CHECKOUT_REPO__` placeholder. On machines whose dotfiles are
managed elsewhere (here, chezmoi), that tool can own the units and the env file
instead; don't use both, or each overwrites the other.

**Start order doesn't matter.** The units carry **no** systemd ordering between
them; they find each other at runtime (audioviz reconnects to the daemon's socket
whenever it appears). An earlier cosmetic `After=` line, combined with
`WantedBy=default.target`, formed a boot-time **ordering cycle**. systemd broke
it by silently dropping audioviz's start, so the spectrum didn't start on login.
v1.3.1 removed the ordering; if you installed an older build, re-run
`deploy/install.sh`.

**Logs and control:**

```bash
journalctl --user -u checkout-daemon -f          # follow a service's log
systemctl --user status checkout-daemon          # state
systemctl --user restart checkout-web            # restart one
```

**Why user services, not headless.** These units run inside your login session;
`loginctl enable-linger` is deliberately **not** used. Spectrum's system-audio
capture taps your **PipeWire monitor**, which exists only inside an active login
session. A headless box would capture silence. Every other mode would work
headless, but one consistent install is simpler.

---

## Design principles

- **Measured, not assumed.** There's no datasheet; the bench is the source of
  truth. The hardest bugs — the init-sequence scroll, the capture starvation, the
  `parec` bursts, the serial backlog — were all found by measuring, never in docs.
- **One owner per resource.** One process holds the port; every file has one
  writer. Nothing races.
- **Hide what can't work.** Features that can't work are removed or hidden, not
  left half-wired — e.g. the marquee's impossible live-clock row, and the HP's
  dead annunciators.
- **Versioning:** `major.minor.patch`, read as **"big.small.bug."**

---

## Tests

```bash
python -m pytest                 # Python: drivers, renderer, daemon, spectrum, state, web, bump bar
cd ui && npm run verify          # panel: svelte-check (types + a11y) + vitest + vite build
```

`npm run verify` is required for any panel change: zero errors and no
accessibility warnings before commit.

---

## Roadmap

Release history and plans are in [`docs/roadmap.md`](docs/roadmap.md). Next ideas:

- **A continuous news ticker** (e.g. a message row) — `checkout/news.py`'s
  `NewsFetcher` is the reusable headline source; dynamic mode's alerts already use it.
- **More frames, and rotation** between modes.

---

## Credits

- **IBM command set** — [SNMetamorph/FutabaVfdM202MD10C](https://github.com/SNMetamorph/FutabaVfdM202MD10C)
  (MIT): the Futaba M202MD10C protocol — command bytes, the extended-mode init
  (`0x00 0x01`) that fixed the vertical scroll, the 9 user-glyph codes
  (`0x15`–`0x1E`), and the brightness, code-page, cursor and reset commands.
  The extended-mode discovery is credited to `abomin`.
- **HP command set** — the OEM "VFD LD220 User Manual V2.3" (§4.1.2, Epson mode),
  bundled in the [`ld220`](https://rubygems.org/gems/ld220) Ruby gem; its glyph
  details were corrected on the bench (see above).
- **Preview font** — [Eigenbaukombinat/vfd_kassendisplay](https://github.com/Eigenbaukombinat/vfd_kassendisplay)
  (Unlicense): the real 5×7 character bitmaps, decoded from its per-character
  photos of the display.

These are published facts (command bytes, glyph bitmaps), each independently
bench-confirmed on our unit; the driver and all other code here is original.

**Weather data** by [Open-Meteo.com](https://open-meteo.com/), licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Dynamic mode fetches it
live from their free non-commercial API; it is not stored or redistributed.
