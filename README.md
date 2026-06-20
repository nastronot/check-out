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

## Configuration (env vars)

| Variable              | Default          | Purpose                    |
|-----------------------|------------------|----------------------------|
| `CHECKOUT_PORT`       | `/dev/ttyUSB0`   | serial device              |
| `CHECKOUT_BAUD`       | `9600`           | baud rate                  |
| `CHECKOUT_TICK_MS`    | `250`            | daemon loop period (ms)    |
| `CHECKOUT_STATE_PATH` | `./state.json`   | path to the state file     |

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
