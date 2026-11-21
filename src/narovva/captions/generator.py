"""Turn a poster_core.ContentBrief into a ready-to-post caption.

Reuses poster_core's LLMClient protocol (`complete_json(system, user) ->
dict`) directly -- no separate LLM client for narovva.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from poster_core import ContentBrief
from poster_core.analysis.llm import LLMClient

from ..config.schema import CaptionTone
from ..language import ENGLISH, Language
from ..platforms import PublishPlatform
from .hashtag_pools import POOLS, pool_for
from .rules import PLATFORM_CAPTION_RULES
from .trending import trending_for_category

_SYSTEM_PROMPT = (
    "You write social media captions for a news account. Given a structured "
    "brief of a news story, write one caption body and a list of hashtags. "
    "The caption must be grounded only in the facts given -- never invent "
    "details. Do not repeat the headline verbatim; write something that adds "
    "context or a hook to make someone stop scrolling. "
    "For hashtags: prefer tags from the provided candidate list (which combines "
    "trending and curated tags for this topic), then add 1-2 story-specific tags "
    "for named entities (companies, people, products) if they are genuinely "
    "relevant. Return only the most relevant tags up to the count requested -- "
    "quality over quantity. "
    'Respond as JSON: {"caption": "...", "hashtags": ["#example", ...]}.'
)

_EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF]+",
    flags=re.UNICODE,
)


@dataclass
class CaptionResult:
    text: str
    hashtags: list[str] = field(default_factory=list)
    truncated: bool = False


def generate_caption(
    brief: ContentBrief,
    *,
    publish_platform: PublishPlatform,
    tone: CaptionTone,
    llm: LLMClient,
    language: Language = ENGLISH,
    genre: str | None = None,
) -> CaptionResult:
    """`language`: with a Hindi voice the caption is written in Hinglish (see narovva.language)."""
    rules = PLATFORM_CAPTION_RULES[publish_platform]
    max_hashtags = min(tone.max_hashtags, rules.max_hashtags)
    user_prompt = _build_user_prompt(brief, tone, max_hashtags=max_hashtags, genre=genre)
    system = _SYSTEM_PROMPT if not language.caption_note else (
        _SYSTEM_PROMPT.replace("Respond as JSON", language.caption_note + " Respond as JSON"))
    raw = llm.complete_json(system, user_prompt)

    caption_text = str(raw.get("caption") or brief.headline or "").strip()
    if not tone.emoji or not rules.allow_emoji:
        caption_text = _EMOJI_RE.sub("", caption_text).strip()

    hashtags = _normalize_hashtags(raw.get("hashtags") or [])
    hashtags = _dedupe_preserve_order(hashtags + _normalize_hashtags(tone.extra_hashtags))

    style = "none" if rules.hashtag_style == "none" else tone.hashtag_style
    max_hashtags = min(tone.max_hashtags, rules.max_hashtags)
    hashtags = hashtags[:max_hashtags] if style != "none" else []

    assembled, truncated = _assemble(caption_text, hashtags, style, rules.max_chars)
    return CaptionResult(text=assembled, hashtags=hashtags, truncated=truncated)


def _build_candidate_hashtags(brief: ContentBrief, max_candidates: int = 30, genre: str | None = None) -> list[str]:
    """Merge trending + curated pool into a ranked candidate list for the LLM. A genre with its own pool (gaming)
    picks the pool and the trending topic; otherwise the brief's category does."""
    category = getattr(brief.category, "value", str(brief.category))
    topic = genre if genre and genre.lower() in POOLS else category
    trending = trending_for_category(topic)
    pool = pool_for(category, genre)
    # Trending first (most timely), then curated pool. Deduplicate case-insensitively.
    seen: set[str] = set()
    candidates: list[str] = []
    for tag in trending + pool:
        key = tag.lower()
        if key not in seen:
            seen.add(key)
            candidates.append(tag)
        if len(candidates) >= max_candidates:
            break
    return candidates


def _build_user_prompt(brief: ContentBrief, tone: CaptionTone, max_hashtags: int = 8, genre: str | None = None) -> str:
    category = getattr(brief.category, "value", str(brief.category))
    lines = [
        f"Voice/tone: {tone.voice}",
        f"Headline: {brief.headline}",
    ]
    if brief.hook:
        lines.append(f"Hook: {brief.hook}")
    lines.append(f"Summary: {brief.summary}")
    if brief.why_it_matters:
        lines.append(f"Why it matters: {brief.why_it_matters}")
    if brief.notable_quote:
        attribution = f" -- {brief.notable_quote.attribution}" if brief.notable_quote.attribution else ""
        lines.append(f'Notable quote: "{brief.notable_quote.text}"{attribution}')
    if brief.key_facts:
        lines.append("Key facts: " + "; ".join(brief.key_facts[:3]))
    if brief.closing_line:
        lines.append(f"Closing line: {brief.closing_line}")
    lines.append(f"Category: {category}")
    candidates = _build_candidate_hashtags(brief, genre=genre)
    if candidates:
        lines.append(f"Candidate hashtags (trending + curated, pick up to {max_hashtags}): "
                     + " ".join(candidates))
    return "\n".join(lines)


def _normalize_hashtags(tags: list[str]) -> list[str]:
    out = []
    for tag in tags:
        tag = str(tag).strip().lstrip("#")
        tag = re.sub(r"[^A-Za-z0-9_]", "", tag)
        if tag:
            out.append(f"#{tag}")
    return out


def _dedupe_preserve_order(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for tag in tags:
        key = tag.lower()
        if key not in seen:
            seen.add(key)
            out.append(tag)
    return out


def _assemble(caption: str, hashtags: list[str], style: str, max_chars: int) -> tuple[str, bool]:
    if style == "inline" and hashtags:
        hashtag_block = " " + " ".join(hashtags)
    elif style == "footer" and hashtags:
        hashtag_block = "\n\n" + " ".join(hashtags)
    else:
        hashtag_block = ""

    budget = max_chars - len(hashtag_block)
    truncated = False
    if len(caption) > budget:
        budget = max(0, budget - 1)  # room for the ellipsis
        caption = caption[:budget].rstrip() + "…"
        truncated = True

    return caption + hashtag_block, truncated
