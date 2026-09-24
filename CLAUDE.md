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

See `docs/hardware.md` — the LED module, the
serial link, and the reverse-engineered protocol.

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
- `frames/base.py` — `Frame` interface; `frames/{clock,message,ticker,weather}.py`.
- `glyphs.py` — shared hand-drawn label/icon bitmaps (inverted L/R/H/C, degree, colon fade).
- `state.py` — atomic load/save of `state.json` + `status.json`.
- `daemon.py` — the SINGLE FAST LOOP + entrypoint; diffs frames, reconnects, shuts down clean.
- `spectrum.py` — spectrum protocol + bar rendering + DSP + `SpectrumReceiver`/`Sender` (shared).
- `audioviz.py` — the audio capture + FFT process (separate; streams bars over a socket).
- `weather.py` — Open-Meteo request/reply, the weather bottom line, and `WeatherFetcher`.

### Single fast loop (v0.9.0)
The daemon runs ONE fast loop (~30Hz, `config.LOOP_HZ`), NOT a 250ms tick. Each
iteration: mtime-gates `state.json` (re-parse only when it changed — a single
`os.stat`), computes the active frame, and **emit-diffs** to the serial port
(writes only when the frame changed). Looping fast is free for normal modes
(clock/message/scroll/marquee touch the port only on content change) because
emit-diffing decouples loop rate from write rate; it's what gives `spectrum` its
frame rate — one code path, no mode-transition seam. Per-mode timing is driven
off elapsed wall-clock (`now_ms`): clock ticks 1/s, scroll steps at
`scroll_speed_ms`, marquee re-kicks on text change, animations by their ms params
— all unchanged behaviorally. `status.json` is THROTTLED to ~`config.STATUS_HZ`
(~6Hz) so the mirror file isn't churned 30×/s (still far inside the 5s liveness
window). The loop self-paces with `time.monotonic`; a slow serial write (spectrum)
naturally paces it below `LOOP_HZ`.

### Mode glyph sets (v1.4.0)
A mode that needs its own glyphs declares them in `daemon.mode_glyph_set(mode,
state)` → `(key, {slot: rows})`. `_sync_glyphs` defines the set when the key
changes and restores the user's `state.glyphs` when the new mode has none; a
reset/reconnect re-sends it. Spectrum (keyed by layout + style) and weather use
it. `status.json` `mode_glyphs` mirrors the loaded set so the preview draws it —
**do not copy bitmaps into the UI** for a new mode.

### Weather mode (v1.4.0)
Top `MM/DD/YY DAY HH:MM` (12-hour, no AM/PM); bottom `[H] 93°[L] 74°[C] 82°[R] 82%`
(four fixed 5-cell fields, ` --` when missing or ≥1 h stale). State:
`weather_lat`, `weather_lon`, `weather_colon` (`on` | `tick` | `throb` | `throb2` | `burst` | `burst2`; legacy
`pulse` → `throb`).
- **Fetch:** `WeatherFetcher` is a background THREAD in the daemon (not a
  service) — one ~600-byte Open-Meteo call, no key, stdlib `urllib`. It runs only
  in weather mode and fetches once per data refresh (`current.time` +
  `interval` 900 s + 60 s), retrying 60 s → 900 s on failure. The loop never
  waits on the network.
- **Colon:** the colon cell changes CHARACTER — `on` = the thin one-column
  colon (`COLON_THIN`); `tick` = thin colon then space each half second;
  `throb` / `burst` = a 12-frame loop once a second (blank, dot, thin, peak A,
  thin, dot, blank, dot, thin, peak B, thin, dot — then back to blank, so it runs
  evenly); `throb2` / `burst2` = the same over 2 s. The peaks (slots 7/8) are
  twist-R/L for throb, burst small/big for burst — `weather.glyph_set(colon)`
  picks them, and the glyph-set key `("weather", family)` redefines only on a
  throb ↔ burst switch. 5 labels + dot + thin + 2 peaks fill all 9 slots.
  **Never use the hardware cursor or brightness for it** (see the bench
  TODO below). Weather ignores `animation`.

### Cell-diff writes (v1.4.0)
When the glass holds a known frame (`last_emit` is a show), the daemon calls
`driver.show_changes(old, new)`: only changed cells, `0x10 pos <bytes>` per run
(runs ≤2 cells apart merge, never across rows), one `0x14` at the end; a full
`show()` when that is no longer. A one-cell change is 4 bytes instead of 45.
**Anything that writes the glass outside the emit path must set `last_emit` to
None** (`_invalidate_caches` does; a mode change does) or the diff is computed
against the wrong glass.

## Build history

Phases 2 through 3a, v0.3.0 to v0.9.0, are in
`docs/history.md`. This file describes what the code does now.

## Versioning
Semver `major.minor.patch` read as **"big.small.bug"**.

## How to run
```bash
# Daemon (owns the serial port)
pip install -r requirements.txt
python -m checkout.daemon --dry-run   # no display; prints outgoing bytes as hex
python -m checkout.daemon             # live, opens the serial port

# Web control surface (Phase 2b) — separate process, never opens the port
pip install -r web/requirements.txt
( cd ui && npm install && npm run build )   # build the Svelte app -> ui/dist
uvicorn web.app:app --port 8000 --no-access-log   # serves UI + /api; shares state/status json
# dev: `uvicorn web.app:app --reload --no-access-log` + `cd ui && npm run dev` (vite proxies /api)
# --no-access-log: the UI polls /api/status ~2x/s; skip per-request 200 spam (errors/warnings still show)

# Spectrum analyzer (Phase 3a) — separate process, never opens the port
pip install -r requirements-audio.txt   # numpy + sounddevice (PortAudio)
python -m checkout.audioviz --list      # enumerate input devices -> devices.json
python -m checkout.audioviz             # capture + stream bars to the daemon (set mode "spectrum")
```
Env overrides: `CHECKOUT_PORT`, `CHECKOUT_BAUD`, `CHECKOUT_LOOP_HZ`,
`CHECKOUT_STATUS_HZ`, `CHECKOUT_STATE_PATH`, `CHECKOUT_STATUS_PATH`,
`CHECKOUT_LIBRARY_PATH` (web-only), `CHECKOUT_UI_DIST`, `CHECKOUT_SPECTRUM_SOCK`,
`CHECKOUT_DEVICES_PATH` (audioviz). Weather needs outbound HTTPS to
`api.open-meteo.com` from the daemon. `CHECKOUT_TICK_MS` is legacy (the loop now
uses `LOOP_HZ`; kept for `--once`).

## Serial permissions
The dev user must belong to the device's group (on Arch this is `uucp`) or run
with `sudo`:
```bash
sudo usermod -aG uucp "$USER"   # then re-login
```

## Running as a service (v1.3.0, ordering fix v1.3.1)
`deploy/` installs check-out as **three systemd USER services** that start on
login: `checkout-daemon` (`python -m checkout.daemon`), `checkout-audioviz`
(`python -m checkout.audioviz`), `checkout-web`
(`uvicorn web.app:app --host 127.0.0.1 --port 8000 --no-access-log`). All three:
`WorkingDirectory`/`ExecStart` rooted at the repo's `.venv`, `Restart=on-failure`
`RestartSec=2`, `[Install] WantedBy=default.target`.
- **Order-independent, NO inter-unit ordering (v1.3.1).** The three units carry NO
  `After=`/`Before=`/`Wants=`/`Requires=` referencing each other or
  `default.target` — they self-coordinate at runtime (audioviz polls `state.json`
  and reconnects to the daemon's datagram socket regardless of start order;
  `SpectrumSender` drops silently if the daemon isn't listening yet; the daemon
  owns the socket lazily). A prior cosmetic `After=checkout-daemon.service` (plus
  the daemon/web `After=default.target`), combined with the `WantedBy=default.target`
  wants, formed a boot-time **ordering cycle** (`default.target` → audioviz →
  daemon → `default.target`); systemd broke it by DELETING audioviz's start job, so
  the spectrum silently didn't start on login (a manual `systemctl --user restart
  checkout-audioviz` worked). Removing all inter-unit ordering fixes it.
- **Unit templates** live in `deploy/systemd/*.service` with a `__CHECKOUT_REPO__`
  placeholder — NO personal path/hostname committed. `deploy/install.sh` resolves
  the repo root from its own location, builds the UI if `ui/dist` is missing
  (warns if npm absent), `sed`-substitutes the real path into
  `~/.config/systemd/user/`, `daemon-reload`, then `enable --now` all three.
  `deploy/uninstall.sh` does `disable --now` + removes the units + reload.
- **USER services, NOT lingering/headless (the rationale):** spectrum's system-
  audio capture taps the user's **PipeWire monitor**, which only exists inside an
  active login session. `loginctl enable-linger` is deliberately NOT run — the
  services start on login so audioviz has the PipeWire graph. Logs:
  `journalctl --user -u checkout-daemon -f`; UI at `http://127.0.0.1:8000`.
- **Tests:** `tests/test_deploy.py` checks the units are well-formed INI with the
  required sections/keys + placeholder, the scripts are executable + `bash -n`
  clean (+ shellcheck when present) and the installer seds the placeholder and
  never enables lingering. Config files, so the bar is well-formed, not behavior.

## Roadmap

See `docs/roadmap.md`.

## Credits / third-party
- **Command set:** [SNMetamorph/FutabaVfdM202MD10C](https://github.com/SNMetamorph/FutabaVfdM202MD10C)
  (**MIT**) — the authoritative Futaba M202MD10C command protocol. The
  extended-mode initialization (`0x00 0x01`) that resolved the vertical-scroll
  behavior, the 9 user-glyph codes (`0x15`–`0x1E`), and the brightness /
  code-page / cursor / reset commands were all derived from this library's
  published source. The extended-mode discovery is credited to `abomin` in that
  library. (See §3 in spec.md.)
- **Preview charset:** the 5×7 glyph bitmaps in `ui/src/lib/font5x7.ts` were
  extracted from the character photos in
  [Eigenbaukombinat/vfd_kassendisplay](https://github.com/Eigenbaukombinat/vfd_kassendisplay)
  (`charsetweb/cropped_<ascii>.jpg`), released into the public domain
  (**Unlicense**). Decoded by sampling each photo's 5×7 dot grid.

This project uses these projects' **published facts** — command bytes and glyph
bitmaps — each **independently bench-confirmed on our unit**. The driver and all
other code here is original Python.

## Hardware-confirm TODOs (bench)
- [x] ~~Which character code(s) render the 9 user glyphs~~ — RESOLVED (v0.3.1):
  9 non-contiguous codes `0x15`–`0x1A`, `0x1C`–`0x1E` (`0x1B` skipped); bitmap
  columns are bits 3-7. See "User glyphs" in `docs/history.md`.
- [x] ~~Whether code pages (`0x02` + page) change the glyph set~~ — RESOLVED
  (v0.3.1): yes; 12 pages, confirmed names 0–5. See "Code pages" in `docs/history.md`.
- [x] ~~Whether extended mode exposes the library's claimed 4 brightness levels~~
  — RESOLVED (v0.6.2): yes, four levels `0x20`/`0x40`/`0x60`/`0xFF` confirmed on glass.
- [x] ~~Whether `0x10 pos 0x13` shows a cursor at a merely-positioned cell~~ —
  RESOLVED (v1.4.0 bench): yes, but it is an **underline**, not a block, and it
  stays on across later writes, so every repaint sweeps it visibly across the
  glass. Unusable as a colon tick; weather changes the colon character instead.
  Brightness (`0x04`) is display-wide — no per-cell dimming.
