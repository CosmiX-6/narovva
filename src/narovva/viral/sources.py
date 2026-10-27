"""Raw material for viral detection: recent headlines from many outlets, and
Google Trends' "trending now" searches. Every fetch is best-effort: a feed
that is down or blocks us is skipped, never an error."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import mktime

import feedparser
import httpx

logger = logging.getLogger(__name__)

_UA = "Mozilla/5.0 (compatible; narovva/1.0; +https://github.com/CosmiX-6/narovva)"

# General top-stories feeds from large outlets in several countries: a story many of
# them carry at once is what "everyone is talking about". Checked reachable 2026-10.
DEFAULT_FEEDS = [
    "https://feeds.bbci.co.uk/news/rss.xml",
    "https://feeds.bbci.co.uk/news/world/rss.xml",
    "https://feeds.bbci.co.uk/news/technology/rss.xml",
    "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://www.theguardian.com/international/rss",
    "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "https://www.aljazeera.com/xml/rss/all.xml",
    "https://abcnews.go.com/abcnews/topstories",
    "https://www.cbsnews.com/latest/rss/main",
    "https://feeds.skynews.com/feeds/rss/world.xml",
    "https://rss.dw.com/rdf/rss-en-all",
    "https://www.france24.com/en/rss",
    "https://feeds.feedburner.com/ndtvnews-top-stories",
    "https://indianexpress.com/feed/",
    "https://www.livemint.com/rss/news",
    "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
    "https://www.thehindu.com/news/national/feeder/default.rss",
    "https://techcrunch.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://www.engadget.com/rss.xml",
    "https://www.wired.com/feed/rss",
    "https://www.sciencedaily.com/rss/top.xml",
]

_TRENDS_NS = {"ht": "https://trends.google.com/trending/rss"}


@dataclass
class Headline:
    title: str
    url: str
    source: str
    published_at: datetime | None
    summary: str = ""
    image_url: str | None = None


@dataclass
class Trend:
    query: str
    traffic: int
    started_at: datetime | None
    geo: str
    news: list[Headline] = field(default_factory=list)


def _get(url: str, timeout: float = 15.0) -> bytes | None:
    try:
        r = httpx.get(url, headers={"User-Agent": _UA}, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as exc:
        logger.info("viral: feed %s unreachable (%s)", url, exc)
        return None
    if r.status_code >= 400:
        logger.info("viral: feed %s -> HTTP %s", url, r.status_code)
        return None
    return r.content


def _entry_time(entry) -> datetime | None:
    t = entry.get("published_parsed") or entry.get("updated_parsed")
    if not t:
        return None
    try:
        return datetime.fromtimestamp(mktime(t), tz=UTC)
    except (OverflowError, ValueError):
        return None


def _entry_image(entry) -> str | None:
    for key in ("media_content", "media_thumbnail"):
        media = entry.get(key)
        if media and media[0].get("url"):
            return media[0]["url"]
    return None


def parse_feed(raw: bytes, fallback_source: str) -> list[Headline]:
    parsed = feedparser.parse(raw)
    source = (parsed.feed.get("title") or fallback_source).strip()
    out = []
    for e in parsed.entries:
        title, link = (e.get("title") or "").strip(), e.get("link")
        if title and link:
            out.append(Headline(
                title=title, url=link, source=source, published_at=_entry_time(e),
                summary=(e.get("summary") or "")[:400], image_url=_entry_image(e),
            ))
    return out


def fetch_headlines(feed_urls: list[str], *, workers: int = 8) -> list[Headline]:
    """Every entry of every reachable feed (fetched in parallel)."""
    urls = list(dict.fromkeys(feed_urls))

    def one(url: str) -> list[Headline]:
        raw = _get(url)
        if raw is None:
            return []
        try:
            return parse_feed(raw, url)
        except Exception as exc:  # a malformed feed is skipped
            logger.info("viral: feed %s unparseable (%s)", url, exc)
            return []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, urls))
    reachable = sum(1 for r in results if r)
    logger.info("viral: %d headlines from %d/%d feeds", sum(map(len, results)), reachable, len(urls))
    return [h for r in results for h in r]


def parse_traffic(text: str | None) -> int:
    """'20,000+' / '2K+' / '1M+' -> 20000 / 2000 / 1000000."""
    s = (text or "").strip().upper().rstrip("+").replace(",", "")
    mult = 1
    if s.endswith("K"):
        mult, s = 1_000, s[:-1]
    elif s.endswith("M"):
        mult, s = 1_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return 0


def parse_trends(raw: bytes, geo: str) -> list[Trend]:
    root = ET.fromstring(raw)
    trends = []
    for item in root.iter("item"):
        started = None
        if item.findtext("pubDate"):
            try:
                started = parsedate_to_datetime(item.findtext("pubDate")).astimezone(UTC)
            except (TypeError, ValueError):
                started = None
        news = []
        for n in item.findall("ht:news_item", _TRENDS_NS):
            title = (n.findtext("ht:news_item_title", namespaces=_TRENDS_NS) or "").strip()
            url = (n.findtext("ht:news_item_url", namespaces=_TRENDS_NS) or "").strip()
            if title and url:
                news.append(Headline(
                    title=title, url=url,
                    source=(n.findtext("ht:news_item_source", namespaces=_TRENDS_NS) or "Google Trends").strip(),
                    published_at=started,
                    image_url=n.findtext("ht:news_item_picture", namespaces=_TRENDS_NS),
                ))
        query = (item.findtext("title") or "").strip()
        if query:
            trends.append(Trend(
                query=query, traffic=parse_traffic(item.findtext("ht:approx_traffic", namespaces=_TRENDS_NS)),
                started_at=started, geo=geo, news=news,
            ))
    return trends


def fetch_trends(geos: list[str]) -> list[Trend]:
    out: list[Trend] = []
    for geo in dict.fromkeys(g.upper() for g in geos):
        raw = _get(f"https://trends.google.com/trending/rss?geo={geo}")
        if raw is None:
            continue
        try:
            out.extend(parse_trends(raw, geo))
        except ET.ParseError as exc:
            logger.info("viral: Google Trends %s unparseable (%s)", geo, exc)
    logger.info("viral: %d trending searches from %s", len(out), ", ".join(geos))
    return out
