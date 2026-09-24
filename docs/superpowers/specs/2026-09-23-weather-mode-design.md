# Weather mode — design (v1.4.0)

Status: approved in chat 2026-09-23; this file is the written spec.

> **Superseded in part (bench, 2026-09-23):** the cursor-based `tick` and the
> brightness `pulse` below did not work on the glass (the cursor is an underline
> that stays on; brightness is display-wide). Both now change the colon
> CHARACTER, and the daemon writes only changed cells. See the v1.4.0 "Bench
> correction" entry in `docs/history.md` for what shipped.

## Goal

A `weather` mode that works as an accurate clock and shows today's weather for a
configured latitude/longitude:

```
09/23/26 WED 08:33          <- top: date, weekday, 12-hour HH:MM (no AM/PM)
[H] 93°[L] 74°[C] 82°[R] 82%  <- bottom: high, low, current, chance of rain
```

`[H] [L] [C] [R]` are inverted-letter label glyphs (lit frame, letter cut out
dark); `°` is a degree glyph. All are defined in code, on demand, when the mode
is entered — never read from the user's `state.json` glyph slots.

The colon in `HH:MM` stands in for the hidden seconds. A state setting
`weather_colon` picks one of three behaviours:

| Value | Behaviour |
|---|---|
| `on` | Solid: a plain colon, no cursor, no animation. |
| `tick` (default) | The hardware cursor block sits on the colon's cell for the first half of every second and is off for the second half. |
| `pulse` | Display brightness sweeps up and back down once per second. Brightness is a whole-display setting on this hardware, so the whole panel breathes, not only the colon. |

## Decisions (from the user)

- Location is latitude + longitude only (no geocoding).
- The colon has three settings: on (solid), tick (cursor on/off), pulse
  (brightness up and down once per second).
- Fetch only as often as the data changes: Open-Meteo refreshes `current` every
  900 s, so fetch every 15 minutes, aligned to its refresh.
- Glyphs are coded independently; the mockup's slots may disappear.
- Reuse existing code rather than duplicate it.

## Assumptions (stated, not asked)

- 12-hour time without AM/PM (mockup `08:33` at ~8:38 PM).
- Fahrenheit.
- Rain = today's maximum precipitation probability (matches daily high/low).

## Data source

Open-Meteo forecast API, no key, one call (probed live 2026-09-23, 592 bytes):

```
https://api.open-meteo.com/v1/forecast?latitude=<lat>&longitude=<lon>
  &current=temperature_2m
  &daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max
  &temperature_unit=fahrenheit&timezone=auto&forecast_days=1
```

Used fields: `current.time`, `current.interval`, `current.temperature_2m`,
`daily.temperature_2m_max[0]`, `daily.temperature_2m_min[0]`,
`daily.precipitation_probability_max[0]`, `utc_offset_seconds` (to turn the
location-local `current.time` into an absolute instant).

## Components

### 1. `checkout/glyphs.py` — shared hand-drawn bitmaps

Single source for label/icon bitmaps (editor-natural rows: 7 ints, low 5 bits =
columns 1..5). Holds `LABEL_L`, `LABEL_R` (moved from `spectrum.py`, values
unchanged), new `LABEL_H`, `LABEL_C`, `DEGREE`, and `label_glyph(letter)`.
`spectrum.py` imports from here. Bitmaps (from the user's mockup):

```
H #####  C #####  ° ..#..
  #.#.#    #...#    .#.#.
  #.#.#    #.#.#    ..#..
  #...#    #.###    .....
  #.#.#    #.#.#    .....
  #.#.#    #...#    .....
  #####    #####    .....
```

### 2. Mode glyph sets — generic swap in the daemon

Replaces the spectrum-only `spectrum_active` enter/exit logic.

- `mode_glyph_set(mode, state) -> (key, {slot: rows}) | None` — the one place a
  mode declares the glyphs it needs. `spectrum` returns
  `(("spectrum", layout, style), spectrum.layout_glyphs(layout, style))`;
  `weather` returns `(("weather",), weather.WEATHER_GLYPHS)`; others `None`.
- Daemon keeps `ctx["mode_glyphs_key"]`. Each tick: if the key differs from the
  loaded one, define the new set (then `initialize()` + invalidate caches), or,
  when the new mode has no set, restore `state.glyphs` (by clearing
  `last_glyphs`). User-glyph application is skipped while a mode set is loaded.
- Spectrum-specific bits (socket receiver, decay) stay in spectrum's path;
  only the glyph ownership moves.
- `status.json` gains `glyphs`: the map actually loaded on the display (the
  mode set, else `state.glyphs`). The preview decodes glyph cells from it.

### 3. Clock formatting reuse (`frames/clock.py`)

- Extract `_hour12(now)`; `clock_time` uses it.
- Add `short_date_time(now)` -> `MM/DD/YY DAY HH:MM`, hand-formatted
  (locale-independent), weekday from a `_DAYS` tuple.

### 4. `checkout/weather.py` — reading, formatting, fetcher

- `Reading` (dataclass): `high, low, current, rain` (numbers or None),
  `observed_at` (UTC datetime), `interval_s`, `fetched_at`.
- `build_url(lat, lon)`, `parse(payload) -> Reading` (raises `ValueError` on a
  malformed reply), `bottom_line(reading, now) -> str` (exactly 20 cells:
  four 5-cell fields `glyph + f"{n:>3}" + °/%`; values rounded; ` --` when None,
  when the reading is older than `STALE_S` = 3600, or when a value doesn't fit
  in 3 chars), `WEATHER_GLYPHS` + the slot constants.
- `next_fetch_at(reading) = observed_at + interval_s + 60 s` (floor: now + 60 s).
- `WeatherFetcher`: a daemon thread started lazily on first use. The daemon
  calls `fetcher.want(lat, lon)` each weather tick and `fetcher.latest()` to
  read. It fetches immediately when the location changes or there is no
  reading; otherwise at `next_fetch_at`. On failure it keeps the last good
  reading, records `error`, and retries at 60 s doubling to 900 s. It sleeps on
  an `Event` (woken by a location change or shutdown) — never polls. HTTP is
  stdlib `urllib` with a 10 s timeout; the opener is injectable for tests.
  Idle (no requests) whenever the mode isn't `weather`.

### 5. `frames/weather.py` + the colon tick

- `Frame` gains an optional `cursor(now, top, bottom) -> int | None` (default
  `None`) returning a linear cell 0..39 AFTER alignment.
- `WeatherFrame.render` returns `short_date_time(now)` and either
  `bottom_line(...)` or `SET LOCATION` (no lat/lon). `cursor` returns the index
  of the `:` in the aligned top line while `now.microsecond < 500_000`, else
  `None`.
- `cursor` only names a cell when `weather_colon` is `tick`.
- `pulse` reuses the existing `animation_brightness` triangle with
  `step_ms = 1000 // 6` (one 0→3→0 sweep per second), phase-locked to the
  wall-clock second. In weather mode the colon setting owns brightness
  animation; the global `animation` is forced to `none` there (the same rule
  marquee and spectrum already follow).
- `VFDDriver.show(top, bottom, cursor=None)`: with a cursor, the buffer ends
  `0x10 <pos> 0x13` instead of `0x14`. Bytes stay within the confirmed set.
- The emit tuple carries the cursor, so emit-diffing writes ~2×/s in weather.
- **Bench gate:** before building on it, confirm on glass that `0x10 pos 0x13`
  shows the cursor block at `pos` (and how it looks over the colon).

### 6. State, status, web, UI

- `state.json`: `weather_lat`, `weather_lon` (float or null; out-of-range or junk
  -> null in `_backfill`); `weather_colon` (`on`|`tick`|`pulse`, junk -> `tick`).
- `status.json`: `glyphs`, `cursor` (cell or null), `weather`
  (`{reading…, observed_at, fetched_at, error}` or null).
- Web: no new endpoints — `PUT /api/state` already carries the new keys.
- UI: `weather` in `MODES`; a Weather panel with lat/lon number inputs (debounced
  patch, like marquee text), an On / Tick / Pulse colon toggle, and a
  last-updated/error readout; `VfdPreview`
  decodes glyphs from `status.glyphs` (falls back to state glyphs) and draws the
  cursor block at `status.cursor`.

## Error handling

| Situation | Display |
|---|---|
| No lat/lon | bottom `SET LOCATION` |
| Lat/lon set, no reading yet | fields ` --` |
| Fetch fails, last reading < 1 h old | last reading; `status.weather.error` set |
| Last reading ≥ 1 h old | fields ` --` |
| Malformed reply | treated as a failed fetch |

The clock (top line) never depends on the network.

## Testing

- `glyphs`: L/R bitmaps equal the pre-move values; H/C/° match the spec.
- `weather`: `parse` on the probed payload + malformed ones; `bottom_line` is
  exactly 20 cells for 93/74/82/82, 100°, −10°, 100%, None, stale, overflow;
  `next_fetch_at` alignment + floor; fetcher with a fake opener (immediate fetch
  on location change, backoff on failure, keeps last good).
- `clock`: `short_date_time` across AM/PM/midnight/noon; `clock_time` unchanged.
- `driver`: `show(..., cursor=n)` bytes end `0x10 n 0x13`; default unchanged.
- `daemon`: glyph-set swap on spectrum↔weather↔clock (define, restore user
  glyphs); existing spectrum tests pass; weather emit toggles cursor at the
  half-second only in `tick`; `on` never sets a cursor; `pulse` sweeps 0→3→0
  within one second; colon index follows `align_top`.
- `state`: lat/lon backfill + range checks; `weather_colon` coercion. UI: `npm run verify`.
- No test touches the real network.

## Out of scope

Units toggle, geocoding by place name, multi-day forecast, applying the colon
tick to `clock` mode (the hook supports it; not wired this round).
