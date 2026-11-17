"""Lesson series: explainer posts that teach one idea each ("How AI works"),
alongside the news.

A series is a YAML file in config/lessons/: its name, the chapter label its
videos open on, and an ordered list of lessons. Each lesson has a title, the
hook it opens on (the everyday puzzle it answers), an optional metaphor the
writer may use, and a reference page -- usually a Wikipedia article, read
through Wikipedia's API as plain text -- that grounds every claim and figure,
exactly as the article text grounds a news post.

A channel teaches a series by listing a genre with `series:` set (see
GenreSetting). Each time that genre comes up in the rotation it posts the
series' next lesson not yet posted (the channel's dedup store remembers them,
as it remembers articles). When every lesson is posted the genre has nothing
new, and the rotation moves on to the next genre."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
import yaml
from info_snipe.models import Article as FeedArticle

logger = logging.getLogger(__name__)

LESSONS_DIR = Path("config/lessons")
REFERENCE_CHARS = 9000
# Wikipedia asks API clients to name themselves with a way to reach the project.
_UA = "narovva/1.0 (+https://github.com/CosmiX-6/narovva)"
_SKIP_SECTIONS = ("see also", "references", "external links", "notes", "further reading", "bibliography",
                  "citations", "sources", "footnotes")


@dataclass(frozen=True)
class Lesson:
    id: str
    title: str
    hook: str
    reference: str
    series: str          # the series' display name ("How AI works")
    series_key: str      # its file name ("how-ai-works")
    metaphor: str | None = None
    cover: str | None = None  # 2-5 words for the cover image (default: the title)

    @property
    def content_id(self) -> str:
        return f"lesson:{self.series_key}:{self.id}"


@dataclass
class Series:
    key: str
    name: str
    kicker: str
    lessons: list[Lesson] = field(default_factory=list)

    def by_content_id(self, content_id: str) -> Lesson | None:
        return next((x for x in self.lessons if x.content_id == content_id), None)


def load_series(key: str, directory: Path | str = LESSONS_DIR) -> Series:
    """Read config/lessons/<key>.yaml. Raises ValueError on a malformed file."""
    path = Path(directory) / f"{key}.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    name = str(raw.get("name") or key)
    series = Series(key=key, name=name, kicker=str(raw.get("kicker") or name).upper())
    seen: set[str] = set()
    for i, item in enumerate(raw.get("lessons") or []):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: lesson {i + 1} is not a mapping")
        lid, title, hook, ref = (str(item.get(k) or "").strip() for k in ("id", "title", "hook", "reference"))
        if not (lid and title and ref):
            raise ValueError(f"{path}: lesson {i + 1} needs id, title and reference")
        if lid in seen:
            raise ValueError(f"{path}: duplicate lesson id {lid!r}")
        if not ref.startswith("https://"):
            raise ValueError(f"{path}: lesson {lid!r} reference must be an https URL")
        seen.add(lid)
        series.lessons.append(Lesson(
            id=lid, title=title, hook=hook, reference=ref, series=name, series_key=key,
            metaphor=(str(item["metaphor"]).strip() if item.get("metaphor") else None),
            cover=(str(item["cover"]).strip() if item.get("cover") else None),
        ))
    return series


def pending(series: Series, store, genre: str, limit: int = 1) -> list[FeedArticle]:
    """The series' next lessons not posted yet, in order, as feed articles (so they flow
    through the same retry/dedup bookkeeping as news)."""
    ids = [x.content_id for x in series.lessons]
    unseen = store.filter_unseen(ids) if ids else set()
    out = []
    for lesson in series.lessons:
        if lesson.content_id in unseen:
            out.append(FeedArticle(
                content_id=lesson.content_id, title=lesson.title, url=lesson.reference,
                source_name=_source_name(lesson.reference), genre=genre, description=lesson.hook,
            ))
            if len(out) >= limit:
                break
    if not out:
        logger.warning("lesson series %r: every lesson has been posted; add more to config/lessons/%s.yaml",
                       series.key, series.key)
    return out


def reference_source(lesson: Lesson, timeout: float = 20.0) -> dict | str:
    """What the post is written from: for a Wikipedia page, its plain text from the API
    (a `#Section` anchor puts that section first, after the article's introduction) as
    a poster-core article dict; for any other page, its URL (poster-core fetches it)."""
    url = urlparse(lesson.reference)
    if not url.netloc.endswith("wikipedia.org") or not url.path.startswith("/wiki/"):
        return lesson.reference
    page = unquote(url.path[len("/wiki/"):])
    resp = httpx.get(
        f"https://{url.netloc}/w/api.php",
        params={"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1, "format": "json",
                "formatversion": 2, "titles": page.replace("_", " ")},
        headers={"User-Agent": _UA}, timeout=timeout,
    )
    resp.raise_for_status()
    pages = resp.json().get("query", {}).get("pages") or [{}]
    text = pages[0].get("extract") or ""
    if not text.strip():
        raise ValueError(f"no text for Wikipedia page {page!r}")
    title = pages[0].get("title") or page.replace("_", " ")
    return {
        "title": f"{lesson.title} ({title}, Wikipedia)",
        "text": focus_text(text, unquote(url.fragment).replace("_", " ")),
        "url": lesson.reference,
        "source_name": "Wikipedia",
    }


def focus_text(text: str, section: str = "", limit: int = REFERENCE_CHARS) -> str:
    """Wikipedia plain text, trimmed for the writer: reference-list sections dropped and,
    when `section` names one, that section moved up to follow the introduction."""
    # (the lookahead leaves the newline, so a heading straight after another one matches too)
    parts = re.split(r"\n\s*(={2,6})[ \t]*([^=\n]+?)[ \t]*\1[ \t]*(?=\n)", text)
    intro, sections = parts[0].strip(), []
    for i in range(1, len(parts) - 2, 3):
        name, body = parts[i + 1].strip(), parts[i + 2].strip()
        if name.lower() in _SKIP_SECTIONS:
            continue
        sections.append((name, body))
    if section:
        first = [s for s in sections if s[0].lower() == section.lower()]
        sections = first + [s for s in sections if s not in first]
        if not first:
            logger.warning("Wikipedia section %r not found; using the whole article", section)
    out = intro if not section else intro[:1500]
    for name, body in sections:
        if body:
            out += f"\n\n{name}\n{body}"
        if len(out) >= limit:
            break
    return out[:limit].strip()


def caption_reference(lesson: Lesson) -> str:
    """The credit line under a lesson's caption (Wikipedia text is CC BY-SA)."""
    if "wikipedia.org" in lesson.reference:
        return f"Reference: Wikipedia, \"{_page_title(lesson.reference)}\" (CC BY-SA 4.0)."
    return f"Reference: {lesson.reference}"


def _page_title(url: str) -> str:
    return unquote(urlparse(url).path.rsplit("/", 1)[-1]).replace("_", " ")


def _source_name(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return "Wikipedia" if host.endswith("wikipedia.org") else (host[4:] if host.startswith("www.") else host)


def check(key: str) -> int:
    """Fetch every lesson's reference and report what the writer would get; 1 if any fails."""
    series, bad = load_series(key), 0
    for lesson in series.lessons:
        try:
            src = reference_source(lesson)
            text = src["text"] if isinstance(src, dict) else ""
            anchor = unquote(urlparse(lesson.reference).fragment).replace("_", " ")
            found = not anchor or f"\n{anchor.lower()}\n" in "\n" + text.lower()[:REFERENCE_CHARS]
            status = "ok" if len(text) > 1500 and found else ("SECTION MISSING" if not found else "SHORT")
        except Exception as exc:  # report every lesson, not just the first failure
            status, text = f"FAILED ({exc})", ""
        bad += status != "ok"
        print(f"{status:16} {len(text):6}  {lesson.id:24} {lesson.reference}")
    print(f"{len(series.lessons)} lessons, {bad} problem(s)")
    return 1 if bad else 0


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 3 or sys.argv[1] != "check":
        sys.exit("usage: python -m narovva.lessons check <series>")
    sys.exit(check(sys.argv[2]))
