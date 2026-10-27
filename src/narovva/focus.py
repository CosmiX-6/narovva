"""Editorial focus: keep only fresh stories for the focus audience, most useful first."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta

from .config.schema import FocusConfig

logger = logging.getLogger(__name__)

_SCREEN_SYSTEM = (
    "You are the editor of an Instagram channel for this audience: {audience}. From the candidate "
    "articles, choose the ones this audience can USE: a new model, tool, feature, API, pricing or limit "
    "change they will meet at work; a technique, workflow or benchmark that changes how they build or "
    "work; a security issue or outage in tools they rely on; a clear how-to or lesson from practice. "
    "Reject: funding, valuations, stock moves, lawsuits and corporate drama; vague opinion and hype; "
    "stories only tangentially about AI; minor product updates few people would notice. "
    'Respond as JSON: {{"picks": [<candidate numbers, most useful first, at most 5>]}}. '
    'If none is useful, respond {{"picks": []}}.'
)


def _norm(text: str) -> str:
    return f" {re.sub(r'[^a-z0-9]+', ' ', (text or '').lower())} "


def mentions(text: str, phrases: list[str]) -> bool:
    """Whole-word/phrase match ('ai' matches 'AI tools', not 'said')."""
    hay = _norm(text)
    return any(_norm(p) in hay for p in phrases if p.strip())


def on_topic(title: str, summary: str, focus: FocusConfig) -> bool:
    text = f"{title} {summary or ''}"
    if focus.include_keywords and not mentions(text, focus.include_keywords):
        return False
    return not mentions(title, focus.exclude_keywords)


def keep_on_topic(articles: list, focus: FocusConfig, *, now: datetime | None = None) -> list:
    """Fresh, on-topic articles (info-snipe Articles), in their original order."""
    now = now or datetime.now(UTC)
    cutoff = now - timedelta(hours=focus.max_age_hours)
    out = []
    for a in articles:
        if a.published_at is not None and a.published_at < cutoff:
            continue
        if on_topic(a.title, a.description or "", focus):
            out.append(a)
    return out


def screen(llm, articles: list, audience: str, *, limit: int = 15) -> list:
    """The articles worth posting for `audience`, most useful first. If the model
    is unavailable or answers badly, the keyword-filtered order stands."""
    shortlist = articles[:limit]
    if not shortlist or llm is None:
        return shortlist
    payload = [
        {"n": i + 1, "title": a.title, "source": a.source_name,
         "summary": re.sub(r"<[^>]+>", " ", a.description or "")[:240].strip()}
        for i, a in enumerate(shortlist)
    ]
    try:
        raw = llm.complete_json(_SCREEN_SYSTEM.format(audience=audience or "people who use AI at work"),
                                "Candidates:\n" + json.dumps(payload, ensure_ascii=False))
        picks = raw.get("picks") if isinstance(raw, dict) else None
        if not isinstance(picks, list):
            raise ValueError(f"no picks list in {str(raw)[:120]!r}")
    except Exception as exc:  # incl. LLMUnavailable: the analysis step reports that properly
        logger.warning("focus screen failed (%s); using the keyword-filtered order", exc)
        return shortlist
    chosen = []
    for p in picks:
        try:
            idx = int(p) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(shortlist) and shortlist[idx] not in chosen:
            chosen.append(shortlist[idx])
    logger.info("focus screen kept %d of %d: %s", len(chosen), len(shortlist), [a.title[:60] for a in chosen])
    return chosen
