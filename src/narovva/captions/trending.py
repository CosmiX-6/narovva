"""Google Trends-based trending hashtag lookup.

Queries pytrends for rising related searches for the article's category keyword,
converts the top results to hashtags, and caches them for one hour per keyword
so a channel that posts every two hours makes at most one Trends request per
category per hour.

Fails silently — any network error, rate-limit or import problem returns an
empty list so the caption pipeline continues with the curated pool alone.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

# Map ContentBrief category values → Google Trends search keywords.
_CATEGORY_KEYWORDS: dict[str, str] = {
    "ai":             "artificial intelligence",
    "technology":     "technology news",
    "science":        "science discovery",
    "finance":        "stock market news",
    "business":       "business news",
    "politics":       "world politics",
    "health":         "health news",
    "breaking":       "breaking news",
    "investigation":  "investigative journalism",
    "product_launch": "tech product launch",
    "disaster":       "natural disaster news",
    "sports":         "sports news",
    "general":        "top news today",
}

_CACHE: dict[str, tuple[float, list[str]]] = {}
_CACHE_TTL = 3600.0  # one hour


def _to_hashtag(query: str) -> str:
    """'artificial intelligence tools' → '#ArtificialIntelligenceTools'"""
    return "#" + "".join(word.capitalize() for word in query.strip().split())


def _fetch(keyword: str) -> list[str]:
    """Query Google Trends for rising related queries. Returns [] on any failure."""
    try:
        from pytrends.request import TrendReq
    except ImportError:
        logger.debug("pytrends not installed; skipping trending hashtags")
        return []
    try:
        pt = TrendReq(hl="en-US", tz=0, timeout=(10, 25), retries=1, backoff_factor=0.5)
        pt.build_payload([keyword], timeframe="now 7-d", geo="")
        related = pt.related_queries()
        rising = (related.get(keyword) or {}).get("rising")
        if rising is None or rising.empty:
            # Fall back to top queries when there's no rising data
            top = (related.get(keyword) or {}).get("top")
            if top is None or top.empty:
                return []
            queries = top["query"].head(6).tolist()
        else:
            queries = rising["query"].head(8).tolist()
        tags = [_to_hashtag(q) for q in queries if q and len(q.split()) <= 4]
        logger.debug("Google Trends: %d tags for %r: %s", len(tags), keyword, tags)
        return tags
    except Exception as exc:
        logger.debug("Google Trends lookup failed for %r: %s", keyword, exc)
        return []


def trending_for_category(category: str) -> list[str]:
    """Trending hashtags for a ContentBrief category, cached for 1 hour.

    Returns an empty list rather than raising on any failure so callers
    can always use this without a try/except.
    """
    keyword = _CATEGORY_KEYWORDS.get(str(category).lower(), "top news today")
    now = time.monotonic()
    cached_at, cached_tags = _CACHE.get(keyword, (0.0, []))
    if now - cached_at < _CACHE_TTL:
        return cached_tags
    tags = _fetch(keyword)
    _CACHE[keyword] = (now, tags)
    return tags
