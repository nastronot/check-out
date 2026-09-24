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
