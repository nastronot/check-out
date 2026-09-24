# Dynamic News Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In dynamic mode, poll AP/BBC/NYT RSS for each source's lead story and show a NEWS ALERT banner + scrolling headline when a lead changes, then return to the time and weather.

**Architecture:** A generic background `Poller` is extracted from `WeatherFetcher`; `NewsFetcher` (in a self-contained `checkout/news.py`) reuses it. `DynamicFrame` gains a `tick()` that drives both fetchers and an alert lifecycle; a new `Frame.brightness()` hook lets it own the flash/throb effect. The daemon wires the tick, the alert glyph set, the brightness hook and a `show_news` command.

**Tech Stack:** Python 3.14 stdlib (`xml.etree`, `email.utils`, `html`, `unicodedata`, `urllib`), pytest; Svelte 4 + TypeScript.

**Spec:** `docs/superpowers/specs/2026-09-24-dynamic-news-design.md`

## Global Constraints

- No new dependencies; no test touches the network (feeds come from `tests/fixtures/news/*.xml`).
- The daemon loop never waits on the network (fetches run on the poller thread).
- The display only receives ASCII + user-glyph codes (headlines are cleaned to ASCII).
- Weather behaviour is unchanged by the poller extraction — `tests/test_weather.py` passes untouched.
- Version `1.5.0` (`checkout/__init__.py`, `ui/package.json`).
- Tests: `.venv/bin/python -m pytest -q`; UI gate: `cd ui && npm run verify`.
- Shared UI styles only (`.seg`, `.seg--sm`, `.ctl-row`, one-line `.field__hint`).

## Review Focus

1. A source that fails or returns junk must not blank the others' leads, nor raise an alert.
2. Toggling News off mid-alert, or leaving dynamic mid-alert, must end the alert and restore the normal glyphs.
3. A headline with non-ASCII text (curly quotes, em dash, accents) must render as clean ASCII, never `?`.
4. Show latest with nothing fetched yet must do nothing (no crash, no empty banner).
5. The same lead seen again (feed reorders, re-fetch) must never alert twice.

---

### Task 1: Extract the shared `Poller`

**Files:** Create `checkout/poller.py`; modify `checkout/weather.py`; test `tests/test_poller.py`.

**Interfaces — Produces:**
```python
class Poller:
    RETRY_START_S = 60; RETRY_MAX_S = 900
    def __init__(self, clock=time.time, log=None, autostart=True, name="poller")
    def set_key(self, key) -> None          # None = idle; a new key resets via _reset()
    def due_in(self, now: float) -> float | None
    def fetch_once(self) -> None
    def stop(self) -> None
    # subclass hooks
    def _fetch(self, key, now)              # network; raise on failure
    def _next_at(self, key, now) -> float   # when the next fetch is due after a success
    def _accept(self, key, result, now)     # store the result (called under the lock)
    def _has_result(self) -> bool           # False -> due now
    def _reset(self) -> None                # clear stored results (under the lock)
```
`weather.RETRY_START_S` / `RETRY_MAX_S` remain importable (tests use them).

- [ ] **Step 1:** `tests/test_poller.py` — a toy subclass counting fetches: idle with key None; due at once on a new key; `_next_at` respected; failure → backoff 60, 120… capped at 900; a key change mid-fetch drops the result; an unexpected exception in the thread is logged and backed off (thread survives).
- [ ] **Step 2:** Run — fails (no module).
- [ ] **Step 3:** Implement `Poller` by moving the thread/lock/Event/backoff/drop-stale logic out of `WeatherFetcher`; rewrite `WeatherFetcher(Poller)` with `set_location = set_key`, `_fetch` = `parse(get_json(build_url(*loc)))`, `_next_at` = `next_fetch_at(reading)`, `latest()`, `status()` unchanged. Keep `_get_json` as the injectable attribute (a weather test assigns it).
- [ ] **Step 4:** `pytest tests/test_poller.py tests/test_weather.py -q` — all pass, weather tests unmodified.
- [ ] **Step 5:** Commit `refactor: extract the shared background Poller from WeatherFetcher`.

### Task 2: `news.py` — sources, parsing, cleaning, lead

**Files:** Create `checkout/news.py`; test `tests/test_news.py`; fixtures `tests/fixtures/news/{ap,bbc,nyt}.xml` (saved 2026-09-24).

**Produces:** `Source`, `SOURCES`, `Headline`, `parse_rss(data: bytes, source: Source) -> list[Headline]`, `clean_title(text, strip_suffix="") -> str`, `lead(headlines, pick) -> Headline | None`.

- [ ] **Step 1:** Tests:
  - parse each fixture → 4 headlines with titles, links, `published` epoch.
  - AP `lead(..., "newest")` = the 23:45 item; BBC/NYT `lead(..., "first")` = item 0.
  - `clean_title("US diplomats told to say ‘super intelligence’ — not ‘artificial intelligence’ - AP News", " - AP News")` → `"US diplomats told to say 'super intelligence' - not 'artificial intelligence'"`.
  - `clean_title("Court Blocks Trump’s …", "")` → ASCII only; accents `é` → `e`; `&apos;`/`&amp;` unescaped; whitespace collapsed.
  - malformed XML → `ValueError`; an item with no pubDate → `published` None and never picked by `newest` over a dated one.
- [ ] **Step 2–4:** Run (fail) → implement → run (pass).
- [ ] **Step 5:** Commit `feat: news sources, RSS parsing and lead-story picking`.

### Task 3: `NewsFetcher` — polling and alert rules

**Files:** Modify `checkout/news.py`; test `tests/test_news.py`.

**Consumes:** `Poller` (Task 1), parsing (Task 2). **Produces:** `NewsFetcher(get_bytes=..., clock=..., log=..., autostart=True)` with `set_config(sources: list[str] | None, interval_s: int)`, `latest() -> Headline | None`, `take_alert() -> Headline | None`, `status() -> dict | None`.

- [ ] **Step 1:** Tests with a fake `get_bytes(url)` serving fixtures / mutated copies:
  - first poll records leads silently: `take_alert()` is None; `latest()` is the newest lead.
  - a changed BBC lead on the next poll → `take_alert()` returns it once, then None.
  - two sources change in one poll → the newer `published` wins; the other is not queued.
  - a lead that returns to a previous link doesn't alert (seen-links memory).
  - one source raises → the others still update; `status()["sources"]["nyt"]["error"]` set; the failing source keeps its last lead.
  - all fail → `due_in` = backoff.
  - `set_config(None, …)` → idle; a new source set resets leads (silent again).
  - `_next_at` = now + interval.
- [ ] **Step 2–4:** fail → implement → pass.
- [ ] **Step 5:** Commit `feat: NewsFetcher — lead-change alerts on the shared poller`.

### Task 4: State keys

**Files:** `checkout/state.py`; `tests/test_state.py`.

- [ ] Tests for the six keys' defaults and coercion (spec table): junk sources dropped, order kept, `[]` allowed; interval/repeat/speed clamped ints; effect validated; enabled bool.
- [ ] Implement in `defaults()` + `_backfill`; commit `feat: news settings in state`.

### Task 5: Banner glyphs, brightness hook, alert in `DynamicFrame`

**Files:** `checkout/glyphs.py`, `checkout/frames/base.py`, `checkout/frames/dynamic.py`, `checkout/weather.py` (news glyph set constant is in `frames/dynamic.py` or `news.py` — keep the banner in `glyphs.py`); tests `tests/test_frames.py`, `tests/test_glyphs.py`.

**Produces:**
- `glyphs.bar(*columns) -> list[int]`; `NEWS_BANNER_LEFT`, `NEWS_BANNER_RIGHT` (lists of bar rows).
- `Frame.brightness(now, state, base) -> int | None` (default None).
- `DynamicFrame(weather_fetcher, news_fetcher)`; `.tick(now, state)`, `.show_latest(now) -> bool`, `.alerting(now) -> bool`, `.alert_glyphs() -> dict[int, list[int]]`, `render`, `brightness`.
- `news_banner() -> str` (20 cells), `alert_window(title, elapsed_ms, speed_ms) -> str`, `alert_duration_ms(title, repeat, speed_ms) -> int`, `flash_level(elapsed_ms, base) -> int`, `throb_level(elapsed_ms) -> int`.

- [ ] Tests: `bar(2,3,4,5) == [30]*7` etc. matching g0/g2–g7; banner is 20 cells with 7 distinct glyph codes + " NEWS ALERT "; alert window scrolls one cell per speed step with a 6-space gap; duration = (1+repeat)·(len+6)·speed; alert ends and the normal top returns; flash curve = 0,1,2,3,2,1 ×3 at 120 ms then up to base then base; throb repeats 0..3..0 at 150 ms; effect none → None; tick with news off → no alert even if pending; show_latest with no latest → False; turning news off mid-alert ends it.
- [ ] Implement; commit `feat: news alert in dynamic — banner, scrolling headline, flash/throb`.

### Task 6: Daemon wiring

**Files:** `checkout/daemon.py`; `tests/test_daemon.py`.

- [ ] Tests: dynamic tick calls `DYNAMIC_FRAME.tick`; during an alert the glyph key is `("dynamic", "news")` and the banner glyphs are defined; after it the normal key returns; brightness override applied (flash writes 0x04 levels) and `animation` still ignored; `show_news` command starts an alert (no display reset); status carries `news` while enabled; leaving dynamic ends the alert.
- [ ] Implement: replace the weather `set_location` call with `DYNAMIC_FRAME.tick(now, state)`; `mode_glyph_set` → news set while alerting; `_apply_settings(..., override=frame.brightness(...))`; `_run_command` handles `show_news`; `_write_status` adds `news`; `run()` stops both fetchers.
- [ ] Commit `feat: wire news alerts into the daemon`.

### Task 7: UI

**Files:** `ui/src/lib/types.ts`, `ui/src/lib/components/ControlPanel.svelte`, `ui/src/lib/news.ts` (+ `ui/src/test/news.test.ts`).

- [ ] `newsSummary(status.news)` pure helper + tests (newest headline · source · time; error; empty).
- [ ] News section in dynamic: switch; AP/BBC/NYT toggles (`aria-pressed`, multi-select); interval / repeat / speed number inputs in `.ctl-row`s; NONE/FLASH/THROB `.seg`; **Show latest** button (`postCommand('show_news')`); readout.
- [ ] `npm run verify`; commit `feat(ui): news controls in the dynamic panel`.

### Task 8: Remove the old stubs, docs, version, ship

- [ ] Remove the message-row `news` extension-point comments (`state.py`, `types.ts`, `ControlPanel.svelte`) and the plan text (`spec.md`, `docs/history.md`, README roadmap) — replace with one line pointing at `checkout/news.py` as the reusable fetcher.
- [ ] CLAUDE.md: architecture list (`poller.py`, `news.py`), a "News alerts" paragraph; history entry; roadmap entry; version 1.5.0.
- [ ] Full suite + `npm run verify`; rebuild UI; restart services; confirm a live fetch via `status.news`; push.
