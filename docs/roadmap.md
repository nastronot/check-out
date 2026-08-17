<!-- Moved out of CLAUDE.md on 2026-08-16 under the four-tier standard
     (~/mathom/conventions/the-four-tiers.md). Tier 2: needed by someone
     cloning this repo, not needed on every turn. -->

# Roadmap

- **Phase 1:** driver, renderer, clock frame, daemon, state seam. (done)
- **Phase 2a (v0.3.0):** rich `state.json` schema + `status.json`; message/ticker
  frames; flash/blink animation; command nonce (self_test/reset/redefine_glyphs);
  glyphs + code pages wired. All driven by `state.json` (no web yet). (done)
- **Phase 2b (v0.4.0):** Svelte/FastAPI web control surface — FastAPI reads
  status.json / writes state.json (never the port) + serves the UI; Svelte app
  with the live phosphor preview + core controls. Glyph editor scaffolded. (done)
- **Phase 2c (v0.5.0):** the glyph editor — 9-slot 5×7 draw grid with click-drag
  paint, slot strip (shared dot-render), debounced auto-push to `state.glyphs`,
  clear + copy-from-character (seed from the real font). (done)
- **Phase 2d (v0.7.0):** saved library (`library.json`, web-owned) of messages +
  glyphs with CRUD/recall endpoints + UI panels; `blink` reworked to a brightness
  pulse (distinct from `flash`'s blank). (done)
- **Phase 3a (v0.9.0):** single fast daemon loop (emit-diffed, mtime-gated state,
  throttled status); `spectrum` audio analyzer — `audioviz` process (capture+FFT+
  20 log-bands+decay) streaming 20 bar heights to the daemon over a unix datagram
  socket; double-height bars via 7 height-glyphs (user glyphs restore on exit);
  preview renders the bars. (done)
- **v1.0.0:** serial writes drain to the wire (`tcdrain`) — paces the daemon to
  9600 baud so the OS TX buffer can't backlog (the spectrum latency-drift fix);
  tuned spectrum defaults (`PAREC_LATENCY_MS`=10, `BLOCK`=256). (done)
- **v1.0.1:** Smoothing slider reaches 0 (full snappy↔smooth range). (done)
- **v1.1.0:** spectrum `bars`|`line` style toggle (swappable 7-glyph sets) — sets
  up the style/glyph-swap pattern for the upcoming stereo modes. (done)
- **v1.2.0:** stereo spectrum layouts (`full`|`stereo_v`|`stereo_h`) — stereo
  capture + per-channel DSP (shared auto-gain), tagged socket protocol, L/R label
  + column glyphs, two stereo renderers, UI toggle + preview. (done)
- **v1.2.1:** custom inverted L/R label bitmaps; audio sliders share the
  Brightness slider styling (global `.phosphor-slider`). (done)
- **v1.3.0:** systemd USER services (`deploy/`) — daemon, audioviz, web start on
  login via install/uninstall scripts; user (not lingering/headless) so spectrum's
  PipeWire monitor capture has an active session; host-agnostic unit templates
  (`__CHECKOUT_REPO__` placeholder, install-time sed); `tests/test_deploy.py`. (done)
- **v1.3.1:** fixed a boot-time systemd **ordering cycle** that dropped audioviz at
  login — removed all inter-unit ordering (`After=checkout-daemon.service` on
  audioviz + `After=default.target` on daemon/web), which with the
  `WantedBy=default.target` wants formed a cycle systemd broke by deleting
  audioviz's start job. The services are order-independent by design (socket +
  `state.json` self-coordination), so the ordering was cosmetic. `test_deploy.py`
  now asserts no unit references another checkout-* unit / `default.target` in an
  ordering key. Re-run `deploy/install.sh` to pick up the fixed units. (done)
- **Phase 3:** more frames + rotation.
- Brightness byte first confirmed in v0.1.1 (then thought to be two levels:
  dim/bright; superseded by the four-level finding in v0.6.2).
- **v0.2.0:** adopted the authoritative Futaba M202MD10C command set + extended-mode
  init sequence — all 40 cells now writable, the old 39-cell/scroll workarounds removed.
  Vertical scroll exposed as a controllable feature.
- **v0.3.1:** bench-confirmed the user-glyph pipeline — 9 non-contiguous codes,
  bitmap columns in bits 3-7 (fixed the v0.3.0 low-5-bit encoding), `{gN}` message
  placeholders, code-page name map. Glyph + code-page bench TODOs resolved.
- **v0.4.0:** web control surface — FastAPI (`web/`) over the JSON files +
  Svelte phosphor UI (`ui/`) with the live preview and core controls. Daemon
  untouched. `checkout.state` gained `load_status` + `merge_patch` for reuse.
- **v0.4.1:** fixed the UI build (it shipped uncompiled) — `lang="ts"` + typed
  handlers (no inline TS casts in markup), a11y clean; added `npm run verify`
  (svelte-check + vitest + vite build) as the mandatory pre-commit gate.
- **v0.4.2:** VfdPreview now renders live status — canvas buffer sized via
  ResizeObserver (ctx → size → draw, dpr-scaled, never 0×0) with reactive redraw
  each poll. Daemon coerces an invalid brightness to "bright" once (no per-tick
  log spam). Added a favicon.
- **v0.4.3:** VfdPreview redraw now uses explicit reactive data deps (derived
  top/bottom/bright passed to drawFrame, not a strippable `void` no-op) and an
  un-gated first-frame diagnostic log; added a test tying the canvas decode path
  to litCount. Daemon: after self_test/reset/reconnect it invalidates the
  display-state cache AND skips the rest of that tick, so the NEXT tick re-asserts
  scroll/brightness/code-page/glyphs — fixes the clock scrolling after a self-test.
- **v0.4.4:** replaced the placeholder preview font with the REAL M202MD10C
  charset, decoded from photos of our exact panel (one per char code) in
  Eigenbaukombinat/vfd_kassendisplay. The preview now matches the glass
  dot-for-dot (e.g. 'A' lights 16 dots, not the placeholder's 18).
- **v0.4.5–v0.4.8:** preview polish — square dots (rounded), tighter intra-cell
  dot pitch (denser glyphs, character spacing unchanged), final `DOT_PITCH_X` 5.8.
- **v0.5.0:** the glyph editor (Phase 2c) — `GlyphCanvas` draw grid + slot strip
  on a shared `dotrender.paintCell`, `glyphedit.ts` low-5-bit encode, debounced
  auto-push (`setGlyphLocal` + `pushGlyphs`). VfdPreview refactored onto the same
  `paintCell` so editor and preview render identically.
- **v0.5.1–v0.5.3:** message textarea (Enter = line break) + per-line 20-char
  budget; status heartbeat every tick (alive in static modes); `{gN}` counted/fit
  as one cell (fixed glyph-codes-as-whitespace dropping slots 6–8).
- **v0.6.0:** independent per-line justification — `align_top` / `align_bottom`
  (`left`/`center`/`right`) wired through `render_lines`, with per-line LEFT/
  CENTER/RIGHT controls in the UI.
- **v0.6.1:** clock format `DD MON YYYY` / `HH:MM:SS AM/PM` (12-hour,
  locale-independent month abbreviations).
- **v0.6.2:** FOUR brightness levels (`0x04` + `0x20`/`0x40`/`0x60`/`0xFF`),
  bench-confirmed under extended mode. `state.brightness` is now an int 0..3
  (legacy `"dim"`/`"bright"` migrate to 0/3 and self-heal on load); UI 4-stop
  slider; preview renders 4 phosphor intensities.
- **v0.6.3:** header is the phosphor-tinted logo (CSS mask) + dynamic version
  from package.json.
- **v0.7.0:** saved message/glyph library (`web/library.py` + `library.json`,
  web-owned; daemon untouched) with CRUD + recall endpoints and `SavedMessages` /
  `GlyphLibrary` UI panels; `blink` is now a brightness pulse (dims to MIN on the
  off-phase) — clearly distinct from `flash`'s hard blank, and the preview
  animates both via status.
- **v0.7.1:** drag-and-drop glyph library — drag a glyph onto a slot to load it,
  drag within the library to reorder (`/api/library/glyphs/order`); removed the
  `→gN` buttons; click/tap fallback keeps it touch/keyboard-reachable.
- **v0.7.2:** `pulse` animation — a stepped triangle-wave brightness sweep
  (`0→3→0`, `animation_params.step_ms`) that breathes through the 4 levels;
  PULSE added to the animation control. invert intentionally omitted (hardware
  can't per-pixel invert arbitrary text).
- **v0.7.3:** two scrolling systems — `marquee` (hardware ticker `0x05`, top-only
  autonomous + FIXED speed, free static/clock bottom via `show_bottom`) and
  `scroll` (software, 2-line per-row direction + speed with a ~60ms floor;
  renamed from `ticker`, legacy migrates). Driver `start_ticker`/`show_bottom`;
  bench-confirmed fixed ticker speed + independent bottom row.
- **v0.8.0:** marquee/scroll UX honesty pass. **marquee** bottom is now STATIC
  TEXT ONLY — a live clock/news bottom is impossible (a per-second bottom write
  stops the hardware scroll), so `marquee_bottom="clock"` was removed (tolerated +
  normalized to `static`); added a constraints tip, hid the top-line justify, and
  the preview top now ADVANCES every tick (per-tick offset) so it scrolls.
  **scroll** is the flexible, news-ready home: per-row content source
  (`scroll_{top,bottom}_source` = `message`|`clock`, with a clear `news` extension
  point), per-row scroll/dir/speed kept, and the over-budget char warning removed
  in SCROLL (MESSAGE still warns). Layout: daemon status moved to the right column
  under Commands; masthead meta baseline-aligned to the logo.
- **v0.8.1:** declutter — split the mode-agnostic device settings (brightness,
  Blank, HW scroll, code page) out of Control into a new `DisplayPanel.svelte`
  (right-column order Control, Display, Saved Messages, Commands, Daemon). Control
  is now per-mode only. Animation is hidden in marquee mode and the daemon forces
  `"none"` there so a leftover animation can't affect the ticker. UI-only relocation
  (no state/daemon schema change beyond the marquee animation guard).
- **v0.8.2:** two fixes. (a) **marquee `{gN}` glyphs** — the hardware ticker renders
  user glyphs, but marquee sent the raw text so `{gN}` scrolled literally; the daemon
  now substitutes `{gN}`→glyph-code on `marquee_text` (before `start_ticker`) and
  `marquee_bottom_text`, with the 45-char limit counted post-substitution, and
  `status.top` substitutes so the preview shows the glyph. (b) **preview layout
  stability** — the two columns are now independent flex stacks (`layout__left`),
  removing the dead gap the old row-spanning grid injected under the fixed-size
  preview; the preview keeps a constant 2×20 aspect across mode/status changes.
- **v0.8.3:** three fixes. (a) **library→slot drag-drop** — dragging a library
  glyph onto an editor slot did nothing on desktop; the slot's `dragover` now
  `preventDefault()`s based on a shared `draggedGlyph` store (set on dragstart) so
  the `drop` fires reliably across components (custom-MIME visibility during
  dragover is browser-dependent), and the drop reads `dataTransfer` then the store.
  (b) **polling consolidated** — dropped the redundant `/api/health` hot-poll;
  `daemon_alive` is derived from `/api/status` freshness (`aliveFromStatus`),
  halving request volume; documented `uvicorn --no-access-log`. (c) **mobile
  order** — controls now sit directly under the preview on narrow screens.
- **v0.9.0:** audio **spectrum** analyzer + daemon loop refactor. The daemon is
  now ONE fast loop (~30Hz): mtime-gated state re-parse, emit-diffed serial
  writes, elapsed-time per-mode timing, throttled status — normal modes behave
  identically, spectrum gets its frame rate, no mode-transition seam. New
  `audioviz` process captures audio (mic / PipeWire-Pulse system monitor), FFTs,
  buckets into 20 log bands, decays (attack-fast/release-slow), and streams 20
  bar heights to the daemon over a unix datagram socket (newest-frame-wins,
  20-byte frames; settings via `state.json`, heavy data via the socket). Mode
  `spectrum` defines 7 height-glyphs and renders double-height bars at ~21fps,
  decays on stale, and restores the user's glyph slots on exit; the preview draws
  the bars from `status.bars`. UI gains a SPECTRUM mode with source/device/gain/
  decay controls (`/api/devices` ← `devices.json`).
- **v0.9.1:** two real-machine (Arch/PipeWire) audioviz fixes. (a) **segfault on
  device switch** — the PortAudio (mic) restart now fully tears down (null handle
  → `stop()` THEN `close()`, guarded), debounces rapid switches (~400ms → one
  restart), and catches a failed open (→ zeros, no crash). (b) **system monitor
  not found** — PortAudio can't see PipeWire `.monitor` sources, so system audio
  is now captured natively via `pw-record`/`parec` on the monitor (enumerated via
  `pactl`; default = default-sink `.monitor`); `select_capture` never silently
  uses the mic for `system`. The device list is labeled (monitors vs inputs) and
  the UI filters it by source. Bench-validated: system + monitor + playback →
  non-zero bars; cycling devices no longer crashes.
- **v0.9.2:** spectrum "just works" regardless of volume. (a) **Auto-gain** —
  bars normalize against a decaying-max reference of recent loudness
  (`update_ref`/`normalize_levels`), so they're CONTENT-driven, not volume-driven
  (turn the system volume down, bars stay full). A **silence floor**
  (`signal_rms` < `SILENCE_FLOOR_RMS`) lets them fall flat without amplifying
  hiss, and the reference doesn't ratchet up on silence. The gain slider is now
  **Sensitivity** (biases auto-gain). (b) **Minimal device picker** — the dropdown
  lists only the real Pulse monitors/inputs (labeled), auto-picking the
  default-sink monitor / default source; the raw ALSA/hw/plugin junk is gone
  (~5 vs ~25 entries). Mic now also captures via `pw-record` (PortAudio fallback).
- **v0.9.3:** auto-gain envelope fixes (confirmed on glass). (1) `REF_FLOOR`
  1e-2 → **1e-4** so it sits below quiet-music levels — it was pinning the
  reference at low volume, so volume still shrank the bars (it's now a pure
  divide-by-zero epsilon; the RMS silence gate handles noise). (2) the reference
  tracks `percentile_peak` (~85th) instead of the single loudest band, and
  `AUTOGAIN_RANGE_DB` 42 → **28**, so the spectrum fills instead of one bass band
  pinning the top. (3) `update_ref` is now an **envelope follower** (smooth
  `AUTOGAIN_ATTACK` rise, not an instant snap) so transients don't pump the whole
  display; the bar-height `decay_levels` smoothing is confirmed wired (prev
  persists). Constants carry a tuning guide.
- **v0.9.4:** auto-gain "fills then sinks" fix. v0.9.3's reference tracked an
  85th-percentile of the frame's bands (= the loudest ~15%), and `normalize_levels`
  mapped "at ref → top", so only the loudest bands could reach the top and the
  median-and-below collapsed (and on init `ref` starts tiny, so all clamp to top
  then sink as it rises). Now the reference is `band_mean` (broadband MEAN
  loudness, not a per-band percentile), and `normalize_levels` is **centered with
  headroom** (a band at ref → mid-high, louder → top, quieter → down), so typical
  music SPREADS across the display and is stable. `AUTOGAIN_RELEASE` 0.99 → **0.95**
  (recovers in ~0.5-1s). Sim: pink-ish broadband → max 14 / median ~9 / all 20
  bands lit, stable (no sink), volume-independent.
- **v0.9.5:** the ACTUAL "fills then dies" root cause — capture, not DSP.
  `pw-record`/`pw-cat` piped from a `.monitor` deliver one good buffer then STARVE
  to near-silence (RMS 0.00769 → 0.00003…, bench-proven with a bare pipe);
  `parec --device=<src> --format=s16le …` sustains (RMS ~0.23). `_capture_tool()`
  now PREFERS parec (was pw-record), pw-record kept as fallback. Reverses the
  v0.9.1 guess that "parec emits nothing" (that was a bad invocation). The
  v0.9.2–v0.9.4 DSP was correct, just starved.
- **v0.9.6:** the FINAL spectrum root cause (ends the saga) — parec was
  BLOCK-BUFFERING. Bench (a bare pipe): without a latency hint parec dumps ~30
  chunks at ~0ms apart then a ~760ms (up to ~2000ms) gap, repeating — a ~750ms
  buffer in bursts, which the daemon saw as the pop-to-top / fall-to-zero PUMP
  plus a 1-2s delay. `parec_command` now passes `--latency-msec=20`
  (`PAREC_LATENCY_MS`) → steady ~21ms gaps (max 31ms, zero >100ms). Confirmed on
  glass: bars bounce smoothly with music, no pump, no delay. The DSP was right
  all along — it was being fed bursts.
- **v1.0.0:** the LAST spectrum-latency root cause — the SERIAL TX BUFFER backing
  up. The daemon renders spectrum at `LOOP_HZ` (~30fps) and `show()` → `_write()`
  did `self._serial.write(data)` fire-and-forget into the OS TX buffer (port
  opened `timeout=0`, non-blocking). But 9600 baud only drains ~21fps, so ~9
  frames/s accumulated in the kernel buffer until full (~1-1.5s) and the glass
  always rendered frames that old — the spectrum delay that drifted in then held,
  trailing ~1-2s after the music paused. Proven: a standalone 30fps socket
  receiver tracked the music perfectly; only the serial-writing daemon lagged.
  Fix: `_write()` now calls `self._serial.flush()` (POSIX pyserial =
  `termios.tcdrain` — blocks until transmitted) AFTER each write, so the daemon
  paces to the real wire speed and NEVER queues more than the current frame —
  zero backlog by construction. Applies to ALL writes (normal modes emit-diff +
  write rarely, so the drain there is negligible — one uniform path). Also
  formalized the bench-tuned spectrum defaults: `PAREC_LATENCY_MS` 20 → **10**
  and `BLOCK` 1024 → **256** (`LOOP_HZ` stays 30 — 60 felt worse). Confirmed on
  glass: bars track the music with only the minimal fixed pipeline latency, no
  drift; pausing stops the bars within ~one frame.
- **v1.0.1:** the Smoothing slider (`audio_decay`) now reaches **0** (was floored
  at 0.5 in the UI), so the bars can do a crisp/snappy instant fall — `decay_levels`
  and the state clamp already accepted `[0, 0.999]`, only the slider blocked it.
  Purely a visual feel control, separate from pipeline latency.
- **v1.1.0:** spectrum **render style** — a `spectrum_style` toggle (`bars` |
  `line`) with two swappable 7-glyph sets in the same slots 0..6. **bars** = the
  existing filled double-height columns; **line** = only the PEAK row lit per band
  (`line_glyph` lights one row, `line_to_cells` empties the bottom cell once the
  peak rides into the top cell). The daemon redefines the 7 slots on a live style
  change (`_define_spectrum_glyphs`, tracked in `ctx["spectrum_style"]`), renders
  via the style's cell mapping, and mirrors `spectrum_style` into status so the
  preview (`spectrumbars.ts` `spectrumCells`) draws bars vs line. UI: a BARS|LINE
  segmented toggle in the spectrum controls. This establishes the style +
  swappable-glyph-set seam that the stereo modes (next release) reuse.
- **v1.2.0:** **stereo spectrum layouts** — a `spectrum_layout` toggle (`full` |
  `stereo_v` | `stereo_h`) on top of the v1.1.0 Bars/Line style. `stereo_v` = a
  19-band spectrum per channel (top=L, bottom=R, one cell tall); `stereo_h` = one
  horizontal level meter per channel at 95-column (19×5) resolution; `full` =
  the original mono double-height. Needed real changes through the stack: parec
  capture is now `--channels=2`, deinterleaved (mono = `(L+R)/2`); per-channel DSP
  (19-band / broadband-level) with a **SHARED** auto-gain reference across L/R so
  the balance is visible; a **tagged variable socket protocol** (layout byte +
  per-layout payload, `decode_frame`→dict, malformed-safe); inverted L/R label
  glyphs + column-fill / single-column glyphs; `layout_glyphs(layout,style)`
  redefined on a layout OR style change; `render_stereo_v` / `render_stereo_h`;
  a daemon layout branch + status carrying per-channel data; a UI LAYOUT toggle;
  and the preview rendering all three layouts (labels + 95-column h-res). This
  reuses (and generalizes) the v1.1.0 glyph-swap seam.
- **v1.2.1:** two polish changes. (a) the stereo L/R label glyphs are now the
  user's hand-designed inverted bitmaps (`LABEL_L`/`LABEL_R` in `spectrum.py`,
  with a matching copy in `spectrumbars.ts`) instead of the auto-generated ones —
  same slots/budgets, bitmap contents only. (b) the audio **Sensitivity** and
  **Smoothing** sliders now share the Brightness slider's track/handle styling: it
  was extracted to a global `.phosphor-slider` class (`app.css`) used by all three
  (no tick labels on the audio sliders; ranges/handlers unchanged).

