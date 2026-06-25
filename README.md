# check-out

A salvaged **IBM SurePOS 500** customer display (P/N 15K2012) — a Futaba
**M202MD10C** 2-line × 20-character blue-green vacuum-fluorescent display — reverse-
engineered into a self-hosted status board and real-time **stereo spectrum
analyzer**. There's no public datasheet for this panel; everything here was
recovered from one published command set and **bench-confirmed on the actual
unit**. It drives the display over a **write-only 9600-baud serial link** from a
long-running daemon, with an optional web control surface and a separate audio
process. The constraint — two lines, twenty characters — is the aesthetic.

> This README is the comprehensive reference: the physical build, the reverse-
> engineered protocol, the architecture, and — most valuably — the **bench
> findings**, the hard-won "why" that isn't in any datasheet. If you have the same
> salvaged display, start here. The deeper internal spec lives in
> [`spec.md`](spec.md) and [`CLAUDE.md`](CLAUDE.md).

---

## What it does

- **Clock** — `DD MON YYYY` / `HH:MM:SS AM/PM`, locale-independent, ticking once a
  second without flicker.
- **Messages** — static (word-wrapped or newline-split across the two lines) or
  software **scroll** (per-row source, direction, and speed).
- **Hardware marquee** — the display's built-in autonomous ticker on the top row.
- **Custom glyphs** — a 9-slot 5×7 glyph editor + an unlimited saved library, with
  `{g0}`..`{g8}` placeholders to mix glyphs into text.
- **Brightness + animations** — four brightness levels; `flash` / `blink` / `pulse`.
- **Code pages** — 12 selectable character sets.
- **Stereo spectrum analyzer** — a real-time audio analyzer in three layouts
  (Full / Stereo-V / Stereo-H) × two styles (Bars / Line).
- **Web control surface** — a Svelte single-page app over a FastAPI backend with a
  **live pixel-accurate phosphor preview** of the glass.

---

## Architecture

Three cooperating processes, coupled only through files and one socket. The
**daemon is the sole owner of the serial port** — nothing else ever touches it.

```
        ┌─────────────────────────── web (optional) ───────────────────────────┐
        │  Svelte UI (ui/dist)  ──HTTP──►  FastAPI (web/app.py)                  │
        │      ▲  polls /api/status                 │ writes state.json          │
        └──────┼────────────────────────────────────┼───────────────────────────┘
               │                                     ▼
         status.json  ◄── (daemon writes) ──┐   state.json  (web/audioviz read)
               ▲                             │        │
               │                       ┌─────┴────────▼──────────────────────────┐
               │                       │            DAEMON  (checkout.daemon)     │
               └───────────────────────┤  ONE fast loop (~30 Hz):                │
                                       │   state.json → active frame → renderer  │
                                       │   → VFDDriver → SERIAL  (sole owner)     │
                                       │   emit-diff writes; status.json heartbeat│
                                       └───────────▲───────────────┬─────────────┘
                                                   │               │ 9600 8N1, write-only
                       unix DGRAM socket           │               ▼
              (20-byte tagged frames, newest-wins) │           ┌────────┐
                                                   │           │  VFD   │ 2×20
        ┌──────────────────────────────────────────┴──┐        └────────┘
        │   AUDIOVIZ  (checkout.audioviz)              │
        │   parec capture → deinterleave → numpy FFT   │
        │   → 20/19-band / level → encode → socket     │
        │   reads audio_* + spectrum_* from state.json │
        └──────────────────────────────────────────────┘
```

**Why it's split this way:**

- **Single serial owner.** The 9600-baud port can't be shared — two writers would
  interleave bytes and corrupt frames. Exactly one process (the daemon) opens it.
  Everyone else influences the display by *writing `state.json`*, which the daemon
  reads each loop.
- **File ownership is one-directional.** The web UI writes `state.json` and the
  daemon writes `status.json`; neither writes the other's file. No locks, no races
  — just two single-writer files.
- **Audio capture is local and heavy.** The spectrum data is ~21 frames/sec of bar
  heights — far too much to route through `state.json`. It goes over a **unix
  datagram socket** instead (newest-frame-wins, so a slow reader can never lag the
  display). Only lightweight *settings* travel via `state.json`. Keeping audio in
  its own process also means it can crash, restart, or be absent without ever
  touching the serial port.

---

## Hardware

The physical build, **bench-verified on this exact unit** (see [`spec.md`](spec.md)
§1 for the full survey). Everything below was measured, not assumed.

### The display
- **Unit:** IBM SurePOS 500 customer display, **P/N 15K2012** (iron-gray housing).
- **VFD board:** Futaba **M202MD10C** family — 2 lines × 20 chars, blue-green VFD.
  No public datasheet; the protocol was reverse-engineered (see below).
- **Cable:** IBM genuine OEM **54Y2454** (RJ-to-DB9, 1 m) — the matched SurePOS 500
  harness. Display side is the RJ jack ("port 4"); host side is DB9.

### The interface ("injector box")
A sealed dongle: a USB cable to the host on one side, a 12 V barrel jack on the
other; inside, a USB-RS-232 adapter and the power-injection wiring.

- **Adapter:** an **OIKWAN USB-to-RS-232 (DB9 male, FTDI)** adapter → `/dev/ttyUSB0`.
  The display takes **true RS-232 directly** — *no MAX3232 / level shifter / inversion
  needed* (bench-confirmed: normal polarity, inversion OFF).
  (FTDI **FT232R**, USB id `0403:6001` — confirmed via `udevadm info /dev/ttyUSB0`.)
- **Power:** a 12 V 1 A regulated supply (5.5×2.1 mm center-positive barrel jack),
  fused with an inline 1 A fuse on the +12 V line.
- **Breakouts/enclosure:** 2× panel-mount DB9-female screw-terminal breakouts
  (one mates the cable, one the adapter) in a Hammond 1591C ABS box; 22 AWG wire.

### DB9 pinout (BENCH-CONFIRMED on this exact cable — the generic RS-232 chart is *wrong* for pins 7/8 here)

| DB9 pin | Measured                | Use                                                        |
|---------|-------------------------|------------------------------------------------------------|
| 1       | **+11.75 V back-feed**  | ⚠️ **HAZARD — leave unconnected** (sources voltage back out) |
| 3       | ~163 mV steady idle     | **DATA** — host TX → here                                  |
| 5       | 0 V                     | **GND**                                                    |
| 8       | +11.75 V                | **+12 V power in**                                         |

Final wiring: **pin 3 = DATA, pin 5 = GND, pin 8 = +12 V, pin 1 left open.** Power
injection joins DATA (3↔3) and GND (5↔5) across the two breakouts and feeds fused
+12 V onto cable pin 8; all grounds common.

> **⚠️ Bench finding — the back-feed hazard.** On this cable **pin 1 sources ~12 V
> *back* through the harness** (it's the "VFD present"/detect line). Wiring it can
> **destroy your adapter's TX pin.** Leave pin 1 permanently unconnected. Only pins
> 3, 5, and 8 are wired.

### The serial link
- **Write-only, 9600 8N1.** Host RX is unused in this build.
- **Bench finding — 9600 is the ceiling.** Bring-up confirmed 9600 8N1 works
  directly; 9600 is treated as the **hard cap** for this link. Don't try to speed
  it up — the renderer and frame rate are designed around the ~960 bytes/sec budget
  (a full 40-cell frame ≈ 40 ms on the wire ⇒ ~21 fps is the practical ceiling).

---

## Protocol notes (reverse-engineered)

Single-byte control codes — **not** ESC/POS (`0x1B 0x40` printed a literal "@", so
ESC-prefixed commands don't apply). The command table was recovered from the
[SNMetamorph `FutabaVfdM202MD10C`](https://github.com/SNMetamorph/FutabaVfdM202MD10C)
source (our exact board) and **bench-confirmed**. `driver.py` is the only code that
emits these bytes.

| Command                 | Bytes                                  |
|-------------------------|----------------------------------------|
| Extended mode           | `0x00` + `0x01` enable / `0x00` disable |
| Select code page        | `0x02` + page byte (12 pages)           |
| Define character        | `0x03` + code + 7 row bytes + `0x00`    |
| Dimming / brightness    | `0x04` + `0x20`/`0x40`/`0x60`/`0xFF`    |
| Print ticker text       | `0x05` + text + `0x0D` (hardware marquee) |
| Backspace               | `0x08`                                 |
| Self test               | `0x0F`                                 |
| Set cursor position     | `0x10` + position byte                 |
| Disable vertical scroll | `0x11`                                 |
| Enable vertical scroll  | `0x12`                                 |
| Cursor on / off         | `0x13` / `0x14`                        |
| Reset                   | `0x1F`                                 |
| Write text              | printable ASCII (auto-advances)        |

### Mandatory init — extended mode is everything
Every `open()`/reconnect must send:

```
0x1F            reset
0x00 0x01       enable extended mode   ← the missing piece
0x11            disable vertical scroll
```

> **Bench finding — the whole early saga was a missing init.** Without
> `0x00 0x01` + `0x11`, the display **scrolls when the bottom-right cell is
> written**. Earlier versions invented a "39-cell limit", a "`0x27` phantom
> scroll", a glyph-anchor rule, and a "no leading clear" rule to work around it —
> *all of them were artifacts of never enabling extended mode.* With the init
> sequence, **all 40 cells are writable** and addressing is plain
> `position = column + row*20`. `VFDDriver.initialize()` sends exactly these bytes.

### Addressing & frame rules
- Top line `0x00`–`0x13` (0–19), bottom line `0x14`–`0x27` (20–39).
- **Cursor-off must be last.** `0x14` hides the cursor, but *any* later write
  re-enables it — there's no persistent off. So `0x14` is the final byte of every
  frame. The whole frame is built as **one buffered write** (no flicker).
- **Four brightness levels** (bench-confirmed under extended mode):
  `0x04` + `0x20`/`0x40`/`0x60`/`0xFF` (Min/Med/Med+/Max), applied live.

### User glyphs — 9 non-contiguous slots
Codes **`0x15 0x16 0x17 0x18 0x19 0x1A 0x1C 0x1D 0x1E`** (slot 0..8; `0x1B` is
skipped). Define with `0x03 <code> <7 rows> 0x00`; display by writing the code
byte. Rows are 5×7, editor-natural (low 5 bits = columns 1..5); the driver shifts
them `<<3` because the panel reads columns from bits 3–7.

> **Bench finding — the whitespace-glyph trap.** Glyph codes **`0x1C`/`0x1D`/`0x1E`
> are ASCII control characters that Python's `str.split()` treats as whitespace.**
> A naive `split()` on rendered text silently drops glyph runs (this dropped slots
> 6–8 in v0.5.x). **Split on the space *character* (`" "`) only**, and count a
> `{gN}` as exactly one cell. A future tinkerer *will* hit this.

### The hardware marquee is deliberately limited
The built-in ticker (`0x05` + text + `0x0D`) is autonomous, but:

> **Bench finding — you cannot scroll + clock at the same time in hardware.** The
> ticker is **TOP-ROW ONLY**, runs at a **FIXED medium speed** (no speed parameter
> exists — bench probes found none), has a **45-char buffer**, and loops. Crucially,
> **a write to the *bottom* row that lands mid-scroll STOPS the top scroll.** So a
> continuous top-row marquee *with a live per-second clock on the bottom row* is
> **impossible in hardware** — don't re-attempt it. (A single static bottom write
> is fine; it's the repeated per-second write that halts the scroll.) The software
> **`scroll`** mode exists precisely for "scrolling text + live clock" cases.

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

# 4. Emit a single frame then exit (leaves it on screen) — handy for hardware tests
python -m checkout.daemon --once
```

You should see a centered date on the top line and a ticking `HH:MM:SS` on the
bottom line.

**The fast loop.** The daemon runs ONE loop at ~30 Hz (`CHECKOUT_LOOP_HZ`). Each
iteration it **mtime-gates `state.json`** (re-parses only when it changed),
computes the active frame, and **emit-diffs** to the serial port — it only writes
when the rendered frame actually changed. So static modes (clock between ticks,
idle messages) cost nothing, while `spectrum` gets its full frame rate from the
same code path. `status.json` is throttled to ~6 Hz (`CHECKOUT_STATUS_HZ`).

> **Bench finding — drain the serial write, or it lags.** The port is opened
> non-blocking, so a bare `serial.write()` is fire-and-forget into the OS TX
> buffer. At ~30 fps renders but only ~21 fps of actual wire drain, frames pile up
> in that kernel buffer until it's full (~1–1.5 s), and the glass always shows
> frames that old — a creeping latency drift (the spectrum bars trailing ~1–2 s
> behind the music). **Fix: `flush()` / `tcdrain()` after every write** so the
> daemon blocks until the bytes are actually on the wire and paces itself to the
> real 9600-baud speed. The TX buffer can never back up.

---

## Web control surface (optional)

A Svelte SPA served by a FastAPI backend. **FastAPI never opens the serial port** —
it only reads `status.json` and writes `state.json`, reusing `checkout.state` so
the format matches the daemon byte-for-byte. The preview is a pixel-accurate 2×20
of phosphor dots driven from `status.json`, so it mirrors the real glass (clock
ticks, marquee motion, brightness, blank, and the spectrum bars).

```bash
pip install -r web/requirements.txt
( cd ui && npm install && npm run build )         # build the Svelte UI -> ui/dist
uvicorn web.app:app --port 8000 --no-access-log   # serves the UI + /api
```

`--no-access-log` keeps the console quiet (the UI hot-polls `/api/status` ~2×/s).
For development: `uvicorn web.app:app --reload --no-access-log` plus
`cd ui && npm run dev` (Vite proxies `/api`).

---

## Spectrum analyzer (optional) — `python -m checkout.audioviz`

A real-time audio analyzer at ~21 fps. A **separate process** captures audio, FFTs
it, and streams frames to the daemon over the unix datagram socket (the daemon
stays the sole serial owner). Capture runs only while mode is `spectrum`.

```bash
pip install -r requirements-audio.txt   # numpy + sounddevice (PortAudio)
python -m checkout.audioviz --list      # enumerate devices -> devices.json
python -m checkout.audioviz             # capture + stream to the daemon
```

Then set mode `spectrum` (UI or `state.json`) and pick a **source**:

- **`system`** — what's playing, via a PipeWire/PulseAudio **monitor** source
  (auto-picks the default sink's `.monitor`).
- **`mic`** — the default (or chosen) input; falls back to `sounddevice`/PortAudio
  if Pulse is absent.

The **Device** dropdown is minimal — "Auto" plus the handful of real Pulse monitors
(system) or inputs (mic), labeled; no raw ALSA/hw nodes.

**Volume-independent (auto-gain).** Bars normalize against recent broadband
loudness, so they fill the display based on *content*, not system volume — turn the
volume down and the bars stay full. A silence floor lets them fall flat (no
amplifying hiss). **Sensitivity** biases the auto-gain; **Smoothing** is the visual
release/decay (0 = snappy, higher = slower fall). Spectrum borrows the 9 glyph
slots for its bar glyphs and restores your custom glyphs on exit.

**System packages (Arch):** `pipewire-pulse` (`pactl` / `pw-record`) and
`portaudio` (mic fallback / `sounddevice`).

### Bench findings — the spectrum latency saga

For several releases the spectrum "popped to the top and fell to zero ~2×/sec with
a 1–2 s delay." It *looked* like a DSP bug every time. **The DSP was correct the
whole time** — each cause was a capture/transport problem, found by direct bench
measurement, not by reading docs. In order of discovery:

- **Capture tool — `pw-record`/`pw-cat` starve a pipe.** Piped from a `.monitor`,
  they deliver *one* good buffer then drop to near-silence (RMS ~0.00003). **`parec`
  sustains** (~0.2). Tool priority is **parec-first**, `pw-record` only as a
  fallback. (Note: PortAudio's ALSA backend can't see `.monitor` sources *at all* —
  that's why native capture is used for system audio.)
- **`parec` block-buffering.** Without a latency hint, `parec` buffers ~750 ms and
  dumps audio in **bursts** (gaps up to ~2000 ms). With **`--latency-msec=10`**, gaps
  are steady ~21 ms. This burst delivery *was* the pop-to-top / fall-to-zero pump
  plus the 1–2 s delay.
- **Serial TX backlog.** Fire-and-forget `serial.write()` into a non-blocking port
  let ~30 fps renders pile into the OS TX buffer (which drains ~21 fps),
  accumulating ~1–1.5 s of latency drift. **Fix: `flush()`/`tcdrain` after each
  write** paces the daemon to the wire (see the fast-loop note above).

**The meta-lesson:** measure at the boundary. Each of these masqueraded as a DSP
bug across multiple releases; a `parec | hexdump` and an RMS print found them in
minutes where the datasheet (there isn't one) never could.

**Structural latency floor (don't chase it).** A small residual offset remains —
FFT window + the PipeWire monitor tap (post-output, *behind* the speakers) + parec
+ serial. It's bench-estimated at ~70–90 ms and is **irreducible**; it's physics,
not a bug.

**Tuned defaults** (all in `audioviz.py` / `config.py`, all tunable):
`PAREC_LATENCY_MS = 10`, `BLOCK = 256` (FFT frame), `LOOP_HZ = 30`.

---

## Stereo modes (detail)

The Bars/Line **style** and the Full/Stereo-V/Stereo-H **layout** toggle
independently. Style applies across all layouts; the fine horizontal resolution
applies only to Stereo-H (Stereo-V is inherently 7 vertical levels per cell).

| Layout       | Top row / bottom row                      | Resolution                          |
|--------------|-------------------------------------------|-------------------------------------|
| **Full**     | one mono spectrum across both rows         | 20 bands, double-height (0..14)     |
| **Stereo-V** | LEFT spectrum / RIGHT spectrum             | 19 bands each, one cell tall (0..7) |
| **Stereo-H** | LEFT level meter / RIGHT level meter       | 19 cells × **5 columns = 95 steps** |

- **Bars** fills solidly to the level (whole cells + a partial leading cell to the
  exact column); **Line** lights only the peak — a single row (vertical) or a single
  gliding **column** (horizontal, 5 px/cell = 95 fine steps).
- **Inverted L/R labels.** Cell 0 of each stereo row is a hand-designed inverted
  glyph (lit frame, dark letter) so it reads as a label, not a bar.
- **Shared auto-gain (deliberate).** L and R normalize against **one** reference
  (the broadband loudness of *both* channels), not independent per-channel gain — so
  a louder channel reads visibly louder and you can **see the stereo balance**.
  Independent gain would hide it.
- **Tagged socket protocol.** Every datagram is `byte 0 = layout tag` + a per-layout
  payload — `full` → 20 heights, `stereo_v` → 19 + 19, `stereo_h` → 2 levels.
  `decode_frame` returns a dict or `None` on a malformed / mid-switch frame (the
  daemon ignores it, never crashes).
- **9-glyph-slot budget, redefined on mode change.** full = 7 height glyphs;
  stereo_v = 7 + L + R = 9 (exact fit); stereo_h = 5 column glyphs + L + R = 7. The
  daemon redefines the slots whenever the layout *or* style changes.

`spectrum_layout` and `spectrum_style` live in `state.json` (set by the UI), **not**
as environment variables.

---

## Configuration (env vars)

| Variable                 | Default                                   | Purpose                                 |
|--------------------------|-------------------------------------------|-----------------------------------------|
| `CHECKOUT_PORT`          | `/dev/ttyUSB0`                            | serial device                           |
| `CHECKOUT_BAUD`          | `9600`                                    | baud rate (the hard cap — see above)    |
| `CHECKOUT_LOOP_HZ`       | `30`                                      | daemon fast-loop rate (Hz)              |
| `CHECKOUT_STATUS_HZ`     | `6`                                       | `status.json` write rate (Hz)           |
| `CHECKOUT_TICK_MS`       | `250`                                     | legacy per-tick sleep (kept for `--once`) |
| `CHECKOUT_STATE_PATH`    | `./state.json`                            | web writes, daemon reads                |
| `CHECKOUT_STATUS_PATH`   | `./status.json`                           | daemon writes, web/UI reads             |
| `CHECKOUT_LIBRARY_PATH`  | `./library.json`                          | saved messages/glyphs (web-only)        |
| `CHECKOUT_SPECTRUM_SOCK` | `$XDG_RUNTIME_DIR/checkout-spectrum.sock` | audioviz → daemon socket                |
| `CHECKOUT_DEVICES_PATH`  | `./devices.json`                          | enumerated audio devices (audioviz)     |
| `CHECKOUT_UI_DIST`       | `ui/dist`                                 | built UI directory (web-only)           |
| `CHECKOUT_DEBUG_TX`      | _(unset)_                                 | `=1` hex-logs every serial write        |

Per-mode behavior (mode, message, brightness, animation, spectrum layout/style,
audio source/sensitivity/smoothing, glyphs, …) is **not** env-configured — it lives
in `state.json` and is driven by the web UI. See the `state.json` schema in
[`CLAUDE.md`](CLAUDE.md).

---

## Serial permissions

The port is write-only at 9600 8N1. Your user must be in the device's group (on
Arch this is `uucp`) or run with `sudo`:

```bash
sudo usermod -aG uucp "$USER"   # then re-login
```

---

## Design principles / lessons

- **Empirical over assumed.** There's no datasheet; the bench is the source of
  truth. Every hardware/protocol fact here was measured on the actual unit — the
  hardest bugs (the init-sequence scroll, the capture starvation, the parec
  burst-buffering, the serial backlog) were all found by direct measurement, never
  by documentation.
- **Serial over USB quirks; one owner.** The display takes RS-232 directly (no level
  shifter). Exactly one process holds the port; everything else is filesystem- and
  socket-coupled, single-writer-per-file, so there are no races.
- **Scope discipline.** Things that can't work are *removed or hidden*, not left
  half-wired — e.g. the marquee's impossible live-clock bottom row was removed and
  the UI control hidden, rather than shipping a broken toggle.
- **Versioning:** `major.minor.patch` read as **"big.small.bug."**

---

## Tests

```bash
python -m pytest                 # Python: driver, renderer, daemon, spectrum, state, web

cd ui && npm run verify          # JS: svelte-check (types + a11y) + vitest + vite build
```

`npm run verify` is the mandatory gate for any UI change — it must pass with zero
errors and no a11y warnings before commit.

---

## Roadmap / planned

- **Always-on via systemd.** A headless/lingering service runs the display and all
  non-audio modes fine. Caveat: the **PipeWire monitor capture** for `spectrum`
  likely needs an **active user session** (the monitor source lives in the user's
  PipeWire graph), so a fully headless box may run everything *except* system-audio
  spectrum without a session workaround.
  <!-- TODO: confirm headless PipeWire/spectrum capture under a systemd user service. -->
- **News feed into SCROLL.** The per-row content-source enum is already news-ready
  (`message` | `clock`, with a documented `news` extension point in `state.py` and
  the daemon's `_scroll_row`) — wiring a live news source is a drop-in.
- **Additional display frames + rotation** between modes.
---

## Credits

- **Command set** — [SNMetamorph/FutabaVfdM202MD10C](https://github.com/SNMetamorph/FutabaVfdM202MD10C)
  (MIT): the authoritative Futaba M202MD10C protocol — command bytes, the
  extended-mode init (`0x00 0x01`) that fixed the vertical-scroll behavior, the 9
  user-glyph codes (`0x15`–`0x1E`), and the brightness/code-page/cursor/reset
  commands. Extended-mode discovery credited to `abomin`.
- **Preview charset** — [Eigenbaukombinat/vfd_kassendisplay](https://github.com/Eigenbaukombinat/vfd_kassendisplay)
  (Unlicense): the real 5×7 glyph bitmaps, decoded from its per-character display
  photos.

These are published facts (command bytes, glyph bitmaps), each independently
bench-confirmed on our unit; the driver and all other code here is original.
