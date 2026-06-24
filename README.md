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

## Web control surface (optional)

```bash
pip install -r web/requirements.txt
( cd ui && npm install && npm run build )     # build the Svelte UI -> ui/dist
uvicorn web.app:app --port 8000 --no-access-log   # serves UI + /api
```

`--no-access-log` keeps the console quiet (the UI polls `/api/status` ~2×/s).

## Spectrum analyzer (optional) — `python -m checkout.audioviz`

SPECTRUM mode shows a 20-band, double-height (14-level) audio analyzer at ~21fps.
A SEPARATE process captures audio, FFTs it, and streams bar heights to the daemon
over a unix datagram socket (the daemon stays the sole serial owner).

```bash
pip install -r requirements-audio.txt          # numpy + sounddevice (PortAudio)
python -m checkout.audioviz --list             # enumerate input devices
python -m checkout.audioviz                     # capture + stream to the daemon
```

Then set mode `spectrum` (UI or `state.json`). Pick the **source** in the UI:
`system` captures playback via a PipeWire/PulseAudio monitor source; `mic`
captures the default input. Gain/decay tune sensitivity + smoothing. Spectrum
borrows the 9 glyph slots for the bars and restores your custom glyphs on exit.

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
