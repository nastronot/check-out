"""News headlines: sources, RSS parsing, title cleaning, and the NewsFetcher.

Self-contained and reusable — dynamic mode's NEWS ALERT uses it today, and a
continuous ticker (on message, say) can use the same fetcher later. Nothing here
touches the serial port.

Each source is an RSS feed with a rule for its LEAD story — what the outlet is
leading with right now. BBC and NYT order their feeds by editorial importance,
so their lead is the first item; AP blocks its own feeds, so it comes through
Google News, which orders by relevance, so its lead is the newest item by
publish time (measured 2026-09-24). Watching leads (not "the newest item
anywhere", which changes every few minutes) is what makes a change alert-worthy.
"""

from __future__ import annotations

import html
import re
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from .poller import Poller


@dataclass(frozen=True)
class Source:
    key: str
    name: str            # short label for the UI
    url: str
    pick: str            # "first" (editorial order) | "newest" (by publish time)
    strip_suffix: str = ""


SOURCES: dict[str, Source] = {
    "ap": Source(
        "ap", "AP",
        "https://news.google.com/rss/search?q=site:apnews.com+when:1d"
        "&hl=en-US&gl=US&ceid=US:en",
        pick="newest", strip_suffix=" - AP News"),
    "bbc": Source("bbc", "BBC", "https://feeds.bbci.co.uk/news/rss.xml", pick="first"),
    "nyt": Source("nyt", "NYT", "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
                  pick="first"),
}


@dataclass(frozen=True)
class Headline:
    source: str
    title: str               # cleaned, ASCII
    link: str                # identity of the story
    published: float | None  # epoch seconds (UTC), or None when the feed omits it


# Typographic characters the display can't show -> their ASCII stand-ins.
_ASCII = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "″": '"',
    "–": "-", "—": "-", "‒": "-", "−": "-",
    "…": "...", " ": " ",
})


def clean_title(text: str, strip_suffix: str = "") -> str:
    """A headline as plain ASCII: entities decoded, typographic quotes/dashes
    replaced, accents dropped (``é`` -> ``e``), whitespace collapsed, and a
    trailing ``strip_suffix`` (e.g. `` - AP News``) removed."""
    text = html.unescape(text).translate(_ASCII)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"\s+", " ", text).strip()
    if strip_suffix and text.endswith(strip_suffix.strip()):
        text = text[: -len(strip_suffix.strip())].rstrip(" -")
    return text


def _published(text: str | None) -> float | None:
    try:
        return parsedate_to_datetime(text).timestamp() if text else None
    except (TypeError, ValueError):
        return None


def parse_rss(data: bytes, source: Source) -> list[Headline]:
    """The feed's items as Headlines, in feed order. Raises ValueError if the
    reply isn't well-formed XML.

    The stdlib parser is safe for remote feeds here: with expat >= 2.4.1 (Python
    3.14 ships 2.8) an entity-expansion "billion laughs" bomb is refused and an
    external entity is never fetched — both are rejected as a ParseError (tests
    pin this), so no defusedxml dependency is needed."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"malformed feed: {exc}") from None
    out = []
    for item in root.iter("item"):
        title = clean_title(item.findtext("title") or "", source.strip_suffix)
        link = (item.findtext("link") or item.findtext("guid") or title).strip()
        if title:
            out.append(Headline(source.key, title, link, _published(item.findtext("pubDate"))))
    return out


def lead(headlines: list[Headline], pick: str) -> Headline | None:
    """The source's lead story: the first item, or the newest dated one."""
    if not headlines:
        return None
    if pick == "newest":
        dated = [h for h in headlines if h.published is not None]
        return max(dated, key=lambda h: h.published or 0.0) if dated else headlines[0]
    return headlines[0]


# --- fetching -----------------------------------------------------------------
HTTP_TIMEOUT_S = 8
_SEEN_MAX = 200     # remembered story links, so a lead that returns never re-alerts


def _http_get_bytes(url: str, timeout: float) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "check-out news"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _iso(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc).isoformat()


class NewsFetcher(Poller):
    """Each selected source's lead story, polled on the shared Poller.

    The key is ``(source keys, interval seconds)``; :meth:`set_config` sets it
    every tick (no sources = idle). One poll fetches every selected source; a
    source that fails keeps its last lead and records its error, and only a poll
    where EVERY source fails counts as a failure (backoff).

    Alerts: the first lead seen from each source is recorded silently. After
    that, a lead whose link wasn't seen before is a candidate; the newest
    candidate becomes the pending alert, replacing any older one not yet taken
    (no backlog). :meth:`take_alert` hands it over once.
    """

    def __init__(self, get_bytes=_http_get_bytes, clock=time.time, log=None,
                 autostart: bool = True) -> None:
        super().__init__(clock=clock, log=log, autostart=autostart, name="news fetch")
        self._get_bytes = get_bytes
        self._leads: dict[str, Headline] = {}
        self._errors: dict[str, str] = {}
        self._pending: Headline | None = None
        self._seen: deque[str] = deque(maxlen=_SEEN_MAX)

    def set_config(self, sources: list[str] | None, interval_s: int) -> None:
        keys = tuple(sorted(k for k in (sources or []) if k in SOURCES))
        self.set_key((keys, int(interval_s)) if keys else None)

    def latest(self) -> Headline | None:
        """The newest current lead across the selected sources."""
        with self._lock:
            leads = list(self._leads.values())
        return max(leads, key=lambda h: h.published or 0.0) if leads else None

    def take_alert(self) -> Headline | None:
        """The pending alert, once (then None until a lead changes again)."""
        with self._lock:
            alert, self._pending = self._pending, None
        return alert

    def status(self) -> dict | None:
        """Per-source lead + error, and the newest lead — for status.json."""
        with self._lock:
            if self._result_key is None:
                return None
            sources = {
                key: {
                    "title": self._leads[key].title if key in self._leads else None,
                    "published": _iso(self._leads[key].published) if key in self._leads else None,
                    "error": self._errors.get(key),
                }
                for key in self._result_key[0]
            }
        newest = self.latest()
        return {
            "sources": sources,
            "latest": None if newest is None else {
                "source": newest.source, "title": newest.title,
                "published": _iso(newest.published)},
            "error": self.error,
        }

    # --- Poller hooks ---------------------------------------------------------
    def _fetch(self, key, now):
        leads, errors = {}, {}
        for src in key[0]:
            source = SOURCES[src]
            try:
                items = parse_rss(self._get_bytes(source.url, HTTP_TIMEOUT_S), source)
                leads[src] = lead(items, source.pick)
            except self.FETCH_ERRORS as exc:
                errors[src] = f"{type(exc).__name__}: {exc}"
        if not leads:
            raise OSError("every source failed: " + "; ".join(f"{k}: {e}" for k, e in errors.items()))
        return leads, errors

    def _next_at(self, key, now) -> float:
        return now + key[1]

    def _accept(self, key, result, now) -> None:
        leads, errors = result
        candidates = []
        for src, new in leads.items():
            if new is None:
                continue
            if src in self._leads and new.link not in self._seen:
                candidates.append(new)               # a changed lead (first sighting is silent)
            if new.link not in self._seen:
                self._seen.append(new.link)
            self._leads[src] = new
            self._errors.pop(src, None)
        self._errors.update(errors)
        if candidates:
            self._pending = max(candidates, key=lambda h: h.published or now)

    def _has_result(self) -> bool:
        return bool(self._leads)

    def _reset(self) -> None:
        self._leads.clear()
        self._errors.clear()
        self._pending = None
