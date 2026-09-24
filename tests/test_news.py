"""News: sources, RSS parsing, title cleaning, lead picking, NewsFetcher alerts.

Feeds come from tests/fixtures/news/*.xml (real replies saved 2026-09-24,
trimmed to 4 items) — no test touches the network.
"""

import pathlib
from datetime import datetime, timezone

import pytest

from checkout import news

FIX = pathlib.Path(__file__).parent / "fixtures" / "news"


def _feed(key):
    return (FIX / f"{key}.xml").read_bytes()


def _ts(*args):
    return datetime(*args, tzinfo=timezone.utc).timestamp()


# --- parsing ---------------------------------------------------------------------
@pytest.mark.parametrize("key", ["ap", "bbc", "nyt"])
def test_parse_reads_every_item(key):
    items = news.parse_rss(_feed(key), news.SOURCES[key])
    assert len(items) == 4
    assert all(h.source == key and h.title and h.link and h.published for h in items)


def test_parse_reads_the_publish_time():
    items = news.parse_rss(_feed("bbc"), news.SOURCES["bbc"])
    assert items[0].published == _ts(2026, 9, 23, 21, 1, 6)


def test_parse_rejects_malformed_xml():
    with pytest.raises(ValueError):
        news.parse_rss(b"<rss><channel><item>", news.SOURCES["bbc"])


def test_parse_keeps_an_undated_item_with_no_time():
    xml = (b"<rss><channel><item><title>A</title><link>x</link></item>"
           b"</channel></rss>")
    (item,) = news.parse_rss(xml, news.SOURCES["bbc"])
    assert item.published is None


# --- cleaning --------------------------------------------------------------------
def test_ap_titles_lose_the_suffix_and_become_ascii():
    items = news.parse_rss(_feed("ap"), news.SOURCES["ap"])
    assert items[1].title == ("US diplomats told to say 'super intelligence' - not "
                              "'artificial intelligence' - after Trump's call")


@pytest.mark.parametrize("raw,clean", [
    ("Trump’s ban", "Trump's ban"),
    ("“Quoted”", '"Quoted"'),
    ("Wait…", "Wait..."),
    ("Café São Paulo", "Cafe Sao Paulo"),
    ("Tom &amp; Jerry &apos;s", "Tom & Jerry 's"),
    ("  lots   of\n space ", "lots of space"),
])
def test_clean_title(raw, clean):
    assert news.clean_title(raw) == clean


def test_clean_title_only_strips_a_trailing_suffix():
    assert news.clean_title("AP News - story - AP News", " - AP News") == "AP News - story"


# --- lead story ------------------------------------------------------------------
def test_lead_is_first_for_bbc_and_nyt_and_newest_for_ap():
    lead = {k: news.lead(news.parse_rss(_feed(k), news.SOURCES[k]), news.SOURCES[k].pick)
            for k in ("ap", "bbc", "nyt")}
    assert lead["bbc"].title.startswith("Blood tests find")          # first, not newest
    assert lead["nyt"].title.startswith("Court Blocks Trump's")
    assert lead["ap"].title.startswith("US diplomats told")          # newest (23:45)


def test_lead_newest_ignores_undated_items():
    dated = news.Headline("ap", "dated", "d", 100.0)
    undated = news.Headline("ap", "undated", "u", None)
    assert news.lead([undated, dated], "newest") is dated
    assert news.lead([], "first") is None


# --- hostile feeds: the stdlib parser (expat >= 2.4.1) must refuse them ---------
_BOMB = (b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa">'
         + b"".join(f'<!ENTITY {n} "{("&" + p + ";") * 10}">'.encode()
                    for p, n in zip("abcdefg", "bcdefgh"))
         + b']><rss><channel><item><title>&h;</title></item></channel></rss>')
_XXE = (b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b'<rss><channel><item><title>&x;</title></item></channel></rss>')


@pytest.mark.parametrize("payload", [_BOMB, _XXE], ids=["billion-laughs", "external-entity"])
def test_hostile_feeds_are_rejected_not_expanded(payload):
    with pytest.raises(ValueError):
        news.parse_rss(payload, news.SOURCES["bbc"])


# --- NewsFetcher: lead changes become alerts ------------------------------------
def _rss(*items):
    """A minimal feed from (title, link, 'YYYY-MM-DD HH:MM') tuples, in order."""
    body = "".join(
        f"<item><title>{t}</title><link>{link}</link>"
        f"<pubDate>{datetime.fromisoformat(d).strftime('%a, %d %b %Y %H:%M:%S')} GMT</pubDate></item>"
        for t, link, d in items)
    return f"<rss><channel>{body}</channel></rss>".encode()


class _Clock:
    def __init__(self, t=_ts(2026, 9, 24, 12, 0)):
        self.t = t

    def __call__(self):
        return self.t


class _Web:
    """Serves feeds by source key; a value that is an Exception is raised."""

    def __init__(self, **feeds):
        self.feeds = dict(feeds)

    def __call__(self, url, timeout):
        key = next(k for k, s in news.SOURCES.items() if s.url == url)
        reply = self.feeds[key]
        if isinstance(reply, BaseException):
            raise reply
        return reply


def _fetcher(web, sources=("bbc", "nyt"), interval=300):
    f = news.NewsFetcher(get_bytes=web, clock=_Clock(), autostart=False)
    f.set_config(list(sources), interval)
    return f


BBC_1 = _rss(("Lead one", "b1", "2026-09-24 10:00"), ("Other", "b2", "2026-09-24 11:00"))
BBC_2 = _rss(("Lead two", "b3", "2026-09-24 11:30"), ("Lead one", "b1", "2026-09-24 10:00"))
NYT_1 = _rss(("NYT lead", "n1", "2026-09-24 09:00"))
NYT_2 = _rss(("NYT new lead", "n2", "2026-09-24 11:45"))


def test_first_sighting_is_silent_but_is_the_latest():
    f = _fetcher(_Web(bbc=BBC_1, nyt=NYT_1))
    f.fetch_once()
    assert f.take_alert() is None
    assert f.latest().title == "Lead one"               # newest lead across sources


def test_a_changed_lead_alerts_once():
    web = _Web(bbc=BBC_1, nyt=NYT_1)
    f = _fetcher(web)
    f.fetch_once()
    web.feeds["bbc"] = BBC_2
    f.fetch_once()
    alert = f.take_alert()
    assert (alert.source, alert.title) == ("bbc", "Lead two")
    assert f.take_alert() is None


def test_when_several_change_the_newest_wins_and_there_is_no_backlog():
    web = _Web(bbc=BBC_1, nyt=NYT_1)
    f = _fetcher(web)
    f.fetch_once()
    web.feeds.update(bbc=BBC_2, nyt=NYT_2)
    f.fetch_once()
    assert f.take_alert().title == "NYT new lead"       # 11:45 beats 11:30
    assert f.take_alert() is None


def test_a_lead_that_returns_does_not_alert_again():
    web = _Web(bbc=BBC_1, nyt=NYT_1)
    f = _fetcher(web)
    f.fetch_once()
    web.feeds["bbc"] = BBC_2
    f.fetch_once()
    f.take_alert()
    web.feeds["bbc"] = BBC_1                             # the old lead is back on top
    f.fetch_once()
    assert f.take_alert() is None


def test_a_failing_source_does_not_stop_the_others():
    web = _Web(bbc=BBC_1, nyt=NYT_1)
    f = _fetcher(web)
    f.fetch_once()
    web.feeds.update(bbc=BBC_2, nyt=OSError("timed out"))
    f.fetch_once()
    assert f.take_alert().title == "Lead two"
    s = f.status()
    assert "timed out" in s["sources"]["nyt"]["error"]
    assert s["sources"]["nyt"]["title"] == "NYT lead"   # kept its last lead
    assert s["sources"]["bbc"]["error"] is None


def test_junk_from_one_source_is_a_failure_for_that_source_only():
    web = _Web(bbc=b"<html>not a feed", nyt=NYT_1)
    f = _fetcher(web)
    f.fetch_once()
    assert f.status()["sources"]["bbc"]["error"]
    assert f.latest().title == "NYT lead"


def test_when_every_source_fails_the_poller_backs_off():
    f = _fetcher(_Web(bbc=OSError("down"), nyt=OSError("down")))
    f.fetch_once()
    assert f.due_in(f._clock()) == news.NewsFetcher.RETRY_START_S


def test_next_check_follows_the_interval():
    f = _fetcher(_Web(bbc=BBC_1, nyt=NYT_1), interval=120)
    f.fetch_once()
    assert f.due_in(f._clock()) == 120


def test_no_sources_is_idle_and_a_new_source_set_starts_silent_again():
    web = _Web(bbc=BBC_1, nyt=NYT_1)
    f = _fetcher(web)
    f.set_config([], 300)
    assert f.due_in(0) is None
    f.set_config(["bbc"], 300)
    f.fetch_once()
    assert f.take_alert() is None                        # silent on the first sighting


def test_unknown_sources_are_ignored():
    f = _fetcher(_Web(bbc=BBC_1), sources=("bbc", "cnn"))
    f.fetch_once()
    assert set(f.status()["sources"]) == {"bbc"}


# --- review fixes -------------------------------------------------------------------
EMPTY = b"<rss><channel></channel></rss>"


def test_a_feed_with_no_items_is_an_error_not_a_tight_loop():
    f = _fetcher(_Web(bbc=EMPTY, nyt=EMPTY))
    f.fetch_once()
    assert f.due_in(f._clock()) == news.NewsFetcher.RETRY_START_S      # backed off
    assert "no items" in f.error


def test_an_empty_source_shows_an_error_while_the_others_work():
    f = _fetcher(_Web(bbc=EMPTY, nyt=NYT_1))
    f.fetch_once()
    assert "no items" in f.status()["sources"]["bbc"]["error"]
    assert f.latest().title == "NYT lead"
    assert f.due_in(f._clock()) == 300


@pytest.mark.parametrize("raw,clean", [
    ("bad\x7fbyte\x01here", "badbytehere"),     # control characters and DEL never reach the glass
    ("£5m and €3", "GBP5m and EUR3"),
    ("Straße", "Strasse"),
])
def test_clean_title_is_printable_ascii_only(raw, clean):
    out = news.clean_title(raw)
    assert out == clean and all(0x20 <= ord(c) <= 0x7E for c in out)
