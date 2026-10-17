"""Find the stories going viral right now: group fresh headlines that report the
same story, then score each story by how many different outlets carry it, whether
it matches a hot Google search, and how new it is."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .sources import Headline, Trend

_STOP = set("""
a an the and or but if of in on at to for from by with without into onto over under about after before
is are was were be been being has have had do does did will would can could should may might must
this that these those it its it's as than then so not no yes new news says say said report reports
live update updates latest video watch here what why how who when where which amid after says just
first more most over up out off his her their our your my we you they he she them us vs via
""".split())
_WORD = re.compile(r"[a-z0-9]+(?:['’][a-z]+)?")


def tokens(text: str) -> set[str]:
    words = _WORD.findall((text or "").lower().replace("’", "'"))
    out = set()
    for w in words:
        w = w.split("'")[0]
        if len(w) >= 3 and w not in _STOP:
            out.add(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w)
    return out


def same_story(a: set[str], b: set[str]) -> bool:
    """Two headlines describe the same story: they share 3+ content words, or 2+
    that make up at least half of the shorter headline."""
    shared = len(a & b)
    if shared >= 3:
        return True
    return shared >= 2 and shared / max(1, min(len(a), len(b))) >= 0.5


def _english(title: str) -> bool:
    letters = [c for c in title if c.isalpha()]
    return bool(letters) and sum(c.isascii() for c in letters) / len(letters) > 0.9


@dataclass
class Story:
    headlines: list[Headline]
    tokens: set[str]
    sources: set[str] = field(default_factory=set)
    trend: Trend | None = None
    score: float = 0.0
    newest: datetime | None = None
    oldest: datetime | None = None

    @property
    def title(self) -> str:
        return self.headlines[0].title

    def age_minutes(self, now: datetime) -> float:
        return (now - self.oldest).total_seconds() / 60 if self.oldest else 0.0


def _excluded(title: str, phrases: list[str]) -> bool:
    low = f" {re.sub(r'[^a-z0-9]+', ' ', title.lower())} "
    return any(f" {p.lower().strip()} " in low for p in phrases if p.strip())


def find_stories(
    headlines: list[Headline], trends: list[Trend], *, now: datetime, max_age_minutes: int,
    min_sources: int, exclude_keywords: list[str] = (), skip_titles: list[str] = (),
) -> list[Story]:
    """Stories carried by at least `min_sources` outlets within the freshness
    window, best first. `skip_titles` (recent posts) are never returned."""
    cutoff = now - timedelta(minutes=max_age_minutes)
    pool: list[Headline] = []
    seen_urls: set[str] = set()
    trend_urls: set[str] = set()
    for t in trends:
        for h in t.news:
            if h.url not in seen_urls:
                seen_urls.add(h.url)
                trend_urls.add(h.url)
                pool.append(h)
    for h in headlines:
        if h.url not in seen_urls:
            seen_urls.add(h.url)
            pool.append(h)
    fresh = [
        h for h in pool
        if h.published_at is not None and cutoff <= h.published_at <= now + timedelta(minutes=10)
        and _english(h.title) and not _excluded(h.title, list(exclude_keywords))
    ]
    fresh.sort(key=lambda h: h.published_at, reverse=True)

    stories: list[Story] = []
    member_tokens: list[list[set[str]]] = []
    for h in fresh:
        tk = tokens(h.title)
        if len(tk) < 2:
            continue
        for story, members in zip(stories, member_tokens):
            if any(same_story(tk, m) for m in members):
                story.headlines.append(h)
                story.tokens |= tk
                members.append(tk)
                break
        else:
            stories.append(Story(headlines=[h], tokens=set(tk)))
            member_tokens.append([tk])

    recent = [tokens(t) for t in skip_titles]
    out = []
    for s in stories:
        # Google Trends' own links are one signal, not several outlets: a story needs
        # the news feeds to carry it (the hot search is a bonus on top).
        s.sources = {h.source.lower() for h in s.headlines if h.url not in trend_urls}
        if any(h.url in trend_urls for h in s.headlines):
            s.sources.add("google trends")
        if len(s.sources) < min_sources:
            continue
        if any(same_story(s.tokens, r) for r in recent if r):
            continue
        times = [h.published_at for h in s.headlines]
        s.newest, s.oldest = max(times), min(times)
        s.trend = _matching_trend(s, trends)
        s.score = _score(s, now, max_age_minutes)
        out.append(s)
    out.sort(key=lambda s: s.score, reverse=True)
    return out


def _matching_trend(story: Story, trends: list[Trend]) -> Trend | None:
    best = None
    urls = {h.url for h in story.headlines}
    for t in trends:
        q = tokens(t.query)
        # A one-word search ("diplomat") is too vague to match on words alone.
        hit = any(n.url in urls for n in t.news) or (len(q) >= 2 and q <= story.tokens)
        if hit and (best is None or t.traffic > best.traffic):
            best = t
    return best


def _score(story: Story, now: datetime, max_age_minutes: int) -> float:
    """Outlets carrying it (the main signal), plus a hot-search bonus, scaled down
    as the story ages through the freshness window."""
    coverage = len(story.sources)
    search = min(3.0, math.log10(story.trend.traffic) - 1) if story.trend and story.trend.traffic > 10 else 0.0
    age = story.age_minutes(now) / max(1, max_age_minutes)
    freshness = 1.0 - 0.5 * min(1.0, max(0.0, age))
    return round((coverage + max(0.0, search)) * freshness, 3)
