# Dynamic news alerts — design (v1.5.0)

Status: approved in chat 2026-09-24.

## Goal

While the display is in **dynamic** mode with **News** on, poll news feeds for
each source's **lead story**. When a lead changes, interrupt the normal
dynamic screen with an alert, then return to it:

```
top    {g2}{g3}{g5}{g0} NEWS ALERT {g6}{g4}{g3}{g7}      (fade-in bars, exactly 20 cells)
bottom <headline scrolling left, 6-space gap, 1 + repeat passes>
```

Optional brightness effect during the alert: none / flash / throb.

## Decisions (from the user)

- The news fetching is **reusable and modular** — a continuous news ticker on
  message (or elsewhere) may use it later. No stubs for that are left in place.
- Transport: **RSS**. Sources for now: **AP** (via Google News RSS — AP blocks
  its own feeds), **BBC**, **NYT**. Multi-select.
- Trigger: a source's **lead story** changes (not "newest item anywhere", which
  churns every few minutes). Measured 2026-09-24: BBC and NYT order by editorial
  importance (lead = first item); Google News orders AP by relevance (lead =
  newest by `pubDate`).
- **Silent start:** the first lead seen from each source is recorded, not
  alerted. A **Show latest** button plays the alert for the newest lead on demand.
- Repeat is an option (default 1 → two passes). Scroll speed is its own variable
  setting. Check interval is an option. Effect: none / flash / throb.
- The old message-row `news` source extension point (v0.8.0) is **removed** — the
  plan pivoted; the modular fetcher is the extension point now.

## Components

### 1. `checkout/poller.py` — the shared background poller

Extracted from `WeatherFetcher` (behaviour unchanged, its tests pass as-is):
a daemon thread that sleeps on an `Event` until the next fetch is due; a *key*
(what to fetch — a location, a source set) set cheaply every tick, `None` =
idle; a new key resets the stored result; a reply for a key that changed while
the request was out is dropped; failures keep the last good result and back off
60 s → 900 s; an unexpected exception is logged and backed off, never kills the
thread. Subclasses supply `_fetch(key, now)` (may raise), `_next_at(result,
key, now)` and `_accept(key, result, now)` (store, under the lock).

`WeatherFetcher` keeps its public API (`set_location`, `latest`, `due_in`,
`fetch_once`, `status`, `stop`).

### 2. `checkout/news.py` — sources, parsing, `NewsFetcher`

- `Source(key, name, url, pick, strip_suffix)`; `SOURCES = {"ap", "bbc", "nyt"}`.
  AP: Google News RSS `site:apnews.com when:1d`, pick `newest`, strip
  `" - AP News"`. BBC/NYT: their top-stories RSS, pick `first`.
- `Headline(source, title, link, published)` — `published` epoch seconds.
- `parse_rss(xml_bytes, source) -> list[Headline]` (stdlib `xml.etree`,
  `email.utils`); raises `ValueError` on malformed XML.
- `clean_title(text, strip_suffix)` — HTML entities, the suffix, curly quotes /
  dashes / ellipsis to ASCII, accents stripped, whitespace collapsed; the display
  only shows ASCII.
- `lead(headlines, pick)` — first item, or newest by `published`.
- `NewsFetcher(Poller)`: key = (sorted source keys, interval s). One poll fetches
  every selected source (8 s timeout each; a failed source keeps its last lead
  and records its error; the poll fails only if all fail). Per source it keeps
  the current lead; the **first** lead per source is recorded silently; a later
  lead whose `link` differs is a candidate, and the newest candidate becomes the
  pending alert (one at a time — no backlog). Interface: `set_config(sources,
  interval_s)`, `latest()` (newest current lead), `take_alert()`, `status()`.

### 3. The alert — `DynamicFrame`

- `DynamicFrame.tick(now, state)` (called by the daemon each tick; replaces the
  weather `set_location` call): configures the weather and news fetchers (news
  only when enabled), expires a finished alert, starts the pending one.
- `show_latest(now)` — start an alert for `latest()` (the `show_news` command).
- `alerting(now)`; `render` draws the banner + the headline window
  (`ticker_window(title, offset, gap=6)`, offset = elapsed // speed).
- Duration = passes × (len(title) + 6) steps × `news_speed_ms`, passes =
  1 + `news_repeat`.
- New generic `Frame.brightness(now, state, base) -> int | None` hook; the
  daemon uses it (when not None) instead of the animation brightness. Dynamic
  returns the effect curve during an alert:
  - `flash`: triangle 0→3→0 three times (120 ms steps), then steps up to
    `base`; then `base`.
  - `throb`: triangle 0→3→0 continuously (150 ms steps) until the alert ends.
- Glyph set during an alert: `("dynamic", "news")` = the 7 distinct banner bars
  (g3's bar is used twice). Afterwards the normal dynamic set reloads.
- Banner bars live in `glyphs.py` built by a `bar(*columns)` helper — e.g.
  `{g2}` = `bar(2, 3, 4, 5)`.

### 4. State (`state.json`, validated in `_backfill`)

| Key | Default | Rule |
|---|---|---|
| `news_enabled` | `false` | bool |
| `news_sources` | `["ap", "bbc", "nyt"]` | known keys only, order kept |
| `news_interval_min` | `5` | int 1..60 |
| `news_repeat` | `1` | int 0..5 |
| `news_speed_ms` | `250` | int 60..1000 |
| `news_effect` | `"none"` | none / flash / throb |

Command `show_news` (the existing nonce channel). `status.json` gains `news`
(per-source lead + error, newest, alert on/off) while dynamic + news are on.

### 5. UI

A **News** section in the dynamic panel (shared `.ctl-row` / `.seg` styles):
switch, AP/BBC/NYT toggles, interval, repeat, speed, NONE/FLASH/THROB, **Show
latest**, one-line readout (newest headline · source · time, or the error).

### 6. Removed

The message-row `news` source stubs: `state.py` (`_SCROLL_SOURCES` comments,
`scroll_*_source` comments), `ui/src/lib/types.ts` (`ScrollSource` doc),
`ControlPanel.svelte` (`SCROLL_SOURCES` comment), and the plan text in
`spec.md`, `docs/history.md`, `README.md` roadmap.

## Error handling

- A source fails → its last lead stays, its error shows in the readout.
- All fail → the poller backs off (60 s → 15 min).
- Malformed feed → treated as a failure for that source.
- Show latest with nothing fetched yet → no-op (readout says why).

## Testing

Stored feed fixtures (no network): RSS parsing, lead picking, title cleaning,
silent-first / changed-lead / newest-wins / no-replay alert logic, per-source
failure isolation, alert duration and window, flash and throb curves, banner
glyph set in and out, `show_news` command, state validation, the weather suite
unchanged on the shared poller, UI checks.

## Out of scope

A news row on message (the fetcher supports it later), more sources, Atom feeds,
cross-source duplicate detection.
