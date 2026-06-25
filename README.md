# check-out

A status board for a salvaged **IBM SurePOS 2x20 VFD** customer display, driven
over a write-only serial link. A daemon owns the serial port, reads desired state
from a JSON file each tick, and renders the active frame onto the 2-line × 20-char
blue-green display. Phase 1 ships a working clock plus the architecture seams a
web UI plugs into later.

## Quick start

```bash
# 1. Install dependencies (a virtualenv is recommended)
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt

# 2. Run with no hardware — prints the outgoing bytes as hex
python -m checkout.daemon --dry-run

# 3. Run live against the display
python -m checkout.daemon

# Emit a single frame then exit (leaves it on screen) — handy for hardware tests
python -m checkout.daemon --once
```

You should see a centered date on the top line and a ticking `HH:MM:SS` on the
bottom line, updating once per second without flicker.

The daemon runs ONE fast loop (~30Hz, `CHECKOUT_LOOP_HZ`): it re-parses
`state.json` only when its mtime changes, computes the active frame, and
EMIT-DIFFs to the serial port (so normal modes only write on change), while
`status.json` is throttled (~`CHECKOUT_STATUS_HZ`). Looping fast costs nothing
for static modes and gives the spectrum analyzer its frame rate.

Each serial write **drains to the wire** (`flush()`/`tcdrain`) before returning,
so the daemon paces to the real 9600-baud speed instead of dumping ~30fps frames
into the OS TX buffer — that buffer backlog was the spectrum **latency drift**
(bars trailing ~1–2s behind the music). Draining keeps the buffer empty, so
spectrum renders at the true wire ceiling with no growing lag.

## Web control surface (optional)

```bash
pip install -r web/requirements.txt
( cd ui && npm install && npm run build )     # build the Svelte UI -> ui/dist
uvicorn web.app:app --port 8000 --no-access-log   # serves UI + /api
```

`--no-access-log` keeps the console quiet (the UI polls `/api/status` ~2×/s).

## Spectrum analyzer (optional) — `python -m checkout.audioviz`

SPECTRUM mode shows a real-time audio analyzer at ~21fps. A SEPARATE process
captures audio, FFTs it, and streams frames to the daemon over a unix datagram
socket (the daemon stays the sole serial owner).

**Style** (`BARS` | `LINE`) and **Layout** (`FULL` | `STEREO-V` | `STEREO-H`)
toggle independently:
- **Full** — one mono spectrum, 20 bands, double-height (14 levels).
- **Stereo-V** — top row = LEFT channel, bottom = RIGHT; a 19-band spectrum each.
- **Stereo-H** — a horizontal level meter per channel (95-column fine resolution).
- **Bars** fills solidly; **Line** lights only the peak (a single row/column).

Capture is stereo (`parec --channels=2`, deinterleaved); auto-gain is **shared**
across L/R so a louder channel reads visibly louder — you can see the balance.

```bash
pip install -r requirements-audio.txt          # numpy + sounddevice (PortAudio)
python -m checkout.audioviz --list             # enumerate devices -> devices.json
python -m checkout.audioviz                     # capture + stream to the daemon
```

Then set mode `spectrum` (UI or `state.json`) and pick the **source**:

- **`system`** — captures what's playing via a PipeWire/PulseAudio **monitor**
  source, natively with **`parec`** (preferred) / `pw-record` (PortAudio can't see
  `.monitor` sources). Auto-picks the monitor of the current default sink
  (`pactl get-default-sink` + `.monitor`).
- **`mic`** — captures the default (or chosen) input (`pactl get-default-source`),
  also via `parec`; falls back to `sounddevice`/PortAudio if Pulse is absent.

> **Note:** `parec` is preferred because `pw-record`/`pw-cat`, piped, deliver one
> good buffer from a `.monitor` then starve to near-silence here (bench-confirmed
> v0.9.5). And `parec` itself is run with **`--latency-msec`** — without a
> latency hint it block-buffers ~750ms and dumps audio in bursts (bench: ~21ms
> gaps with the flag vs up to ~2000ms without), which showed up as the bars
> "popping to the top then falling to zero ~2×/sec" with a 1–2s delay (v0.9.6).
> Together these were the real cause behind the long spectrum-tuning saga — the
> DSP was correct, just being fed bursts. The bench-tuned defaults are
> `PAREC_LATENCY_MS=10` and `BLOCK=256` (both tunable in `audioviz.py`).

The **Device** dropdown is minimal: just "Auto" + the handful of real monitors
(system) or inputs (mic), labeled — no raw ALSA/hw nodes. Auto is usually right.

**Volume-independent (auto-gain).** The bars normalize against recent loudness,
so they fill the display based on CONTENT regardless of system volume — turn the
volume down and the bars stay full. A silence floor lets them fall flat on
silence (no amplifying hiss). **Sensitivity** biases it (center is fine);
**Smoothing** is the visual decay. Spectrum borrows the 9 glyph slots for the
bars and restores your custom glyphs on exit.

**System packages** (Arch): `pipewire-pulse` (for `pactl`/`pw-record`) and
`portaudio` (mic fallback / `sounddevice`).

## Configuration (env vars)

| Variable              | Default          | Purpose                    |
|-----------------------|------------------|----------------------------|
| `CHECKOUT_PORT`       | `/dev/ttyUSB0`   | serial device              |
| `CHECKOUT_BAUD`       | `9600`           | baud rate                  |
| `CHECKOUT_LOOP_HZ`    | `30`             | fast-loop rate (Hz)        |
| `CHECKOUT_STATUS_HZ`  | `6`              | status.json write rate (Hz)|
| `CHECKOUT_STATE_PATH` | `./state.json`   | path to the state file     |
| `CHECKOUT_SPECTRUM_SOCK` | `$XDG_RUNTIME_DIR/checkout-spectrum.sock` | audioviz→daemon socket |

## Serial permissions

The port is write-only at 9600 8N1. Your user must be in the device's group (on
Arch this is `uucp`) or run with `sudo`:

```bash
sudo usermod -aG uucp "$USER"   # then re-login
```

## Tests

```bash
python -m pytest
```

## More

See [CLAUDE.md](CLAUDE.md) for the full hardware reference (command bytes,
addressing table, pin map), the architecture, and the roadmap.

## Credits

- **Command set** — [SNMetamorph/FutabaVfdM202MD10C](https://github.com/SNMetamorph/FutabaVfdM202MD10C)
  (MIT): the authoritative Futaba M202MD10C protocol — command bytes, the
  extended-mode init (`0x00 0x01`) that fixed the vertical-scroll behavior, the 9
  user-glyph codes (`0x15`–`0x1E`), and the brightness/code-page/cursor/reset
  commands. Extended-mode discovery credited to `abomin`.
- **Preview charset** — [Eigenbaukombinat/vfd_kassendisplay](https://github.com/Eigenbaukombinat/vfd_kassendisplay)
  (Unlicense): the real 5×7 glyph bitmaps, decoded from its per-character display
  photos.

These are published facts (command bytes, glyph bitmaps), independently
bench-confirmed on our unit; the driver and all other code here is original.
