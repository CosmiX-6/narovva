"""The two judgement calls a person would make: which of the viral stories is worth
posting (informative, not gossip or a match score), and the opening hook."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from ..llm import LLMUnavailable
from .detect import Story, tokens

logger = logging.getLogger(__name__)

_EDITOR_SYSTEM = (
    "You are the editor of an Instagram news channel that explains the stories everyone is talking "
    "about. From the candidate stories (each already carried by several outlets in the last few hours) "
    "choose the ones most likely to be shared AND that are genuinely informative: they explain an event "
    "with real consequences -- technology, AI, science, health, money and the economy, business, policy, "
    "world events, safety, the climate. Reject: sports results, previews and transfers; celebrity "
    "gossip and entertainment reviews; lotteries and horoscopes; graphic crime with no wider lesson; "
    "opinion pieces; local stories with no wider interest. Prefer stories that are fresh, surprising, "
    "affect many people, and can be explained with facts in 30 seconds. "
    'Respond as JSON: {"picks": [<candidate numbers, best first, at most 3>]}. '
    'If none qualifies, respond {"picks": []}.'
)

_HOOK_SYSTEM = (
    "You write the opening hook of a 30-second vertical news Reel: the first words on screen and the "
    "first words spoken, which decide whether a viewer keeps watching. A plain description of the event "
    "is NOT a hook -- the headline already does that. Styles: 'curiosity' opens a gap only the story "
    "closes (a pointed question, a surprising contrast, a 'why' the viewer cannot answer yet); 'stakes' "
    "says plainly what is at risk or what changes for the viewer -- urgent, never alarmist. Examples "
    "(headline -> hook): 'Fed holds rates steady' -> 'Why your loan just got more expensive.'; "
    "'Israeli settlers attack EU diplomats in West Bank' -> 'Who attacks diplomats -- and gets away "
    "with it?'; 'Nvidia unveils phone AI chip' -> 'Your next phone thinks without the cloud.'. "
    "Rules: 4 to 9 words; true to the facts given (never invent numbers, names or claims); do not "
    "restate the headline; no clickbait phrases ('you won't believe', 'shocking', 'this one trick'); "
    "no emojis, hashtags or ALL CAPS; at most one question mark. Give three different options, best "
    'first. Respond as JSON: {"hooks": ["...", "...", "..."], "style": "curiosity" or "stakes"}.'
)

_BANNED = ("you won't believe", "won't believe", "shocking", "this one trick", "mind-blowing", "jaw-dropping")


def editor_pick(
    llm, stories: list[Story], *, now: datetime, limit: int = 12, audience: str = "",
) -> list[Story]:
    """The stories worth posting, best first. If the model is unavailable or
    answers badly, the detection order stands (the keyword filter already ran)."""
    shortlist = stories[:limit]
    if not shortlist:
        return []
    payload = [
        {
            "n": i + 1,
            "headline": s.title,
            "also": [h.title for h in s.headlines[1:3]],
            "outlets": len(s.sources),
            "minutes_old": round(s.age_minutes(now)),
            **({"hot_search": f"{s.trend.query} ({s.trend.traffic}+ searches)"} if s.trend else {}),
        }
        for i, s in enumerate(shortlist)
    ]
    try:
        system = _EDITOR_SYSTEM + (
            f" This channel currently serves one audience: {audience}. Choose only stories this audience "
            "can use in their work, however viral the others are." if audience else ""
        )
        raw = llm.complete_json(system, "Candidates:\n" + json.dumps(payload, ensure_ascii=False))
        picks = raw.get("picks") if isinstance(raw, dict) else None
        if not isinstance(picks, list):
            raise ValueError(f"no picks list in {str(raw)[:120]!r}")
        chosen = []
        for p in picks:
            try:
                idx = int(p) - 1
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(shortlist) and shortlist[idx] not in chosen:
                chosen.append(shortlist[idx])
        logger.info("viral: editor picked %s of %d", [shortlist.index(s) + 1 for s in chosen], len(shortlist))
        return chosen[:3]
    except LLMUnavailable:
        raise
    except Exception as exc:
        logger.warning("viral: editor call failed (%s); using the detection order", exc)
        return shortlist[:3]


def clean_hook(text: str | None, headline: str = "") -> str | None:
    """A usable hook, or None: 3-11 words, no banned phrases, not the headline."""
    if not text:
        return None
    hook = " ".join(str(text).strip().strip('"“”\'').split())
    hook = re.sub(r"[!]{2,}|[?]{2,}", lambda m: m.group(0)[0], hook)
    words = hook.split()
    if not 3 <= len(words) <= 11 or not re.search(r"[A-Za-z]{2,}", hook):
        return None
    low = hook.lower()
    if any(b in low for b in _BANNED) or low.rstrip(".?!") == headline.lower().rstrip(".?!"):
        return None
    if sum(w.isupper() and len(w) > 4 for w in words) >= 2:  # shouting
        return None
    if restates(hook, headline):
        return None
    if hook[-1] not in ".?!":
        hook += "."
    return hook


def restates(hook: str, headline: str) -> bool:
    """A statement made mostly of the headline's own words is a summary, not a hook.
    (A question may reuse the subject: 'Why are diplomats under attack?')"""
    h, head = tokens(hook), tokens(headline)
    if not h or not head:
        return False
    share = len(h & head) / len(h)
    return share >= 0.75 or (share >= 0.5 and "?" not in hook)


def _first_good(raw, headline: str) -> str | None:
    options = []
    if isinstance(raw, dict):
        options = list(raw.get("hooks") or []) if isinstance(raw.get("hooks"), list) else []
        options.append(raw.get("hook"))
    for option in options:
        hook = clean_hook(option, headline)
        if hook:
            return hook
    return None


def write_hook(llm, brief, style: str = "auto", audience: str = "") -> str | None:
    """Opening hook from the analysed story (so it can only use real facts)."""
    facts = "; ".join(list(getattr(brief, "key_facts", []) or [])[:4])
    user = "\n".join(filter(None, [
        f"Wanted style: {style if style != 'auto' else 'whichever fits this story better'}",
        f"Audience: {audience} -- 'stakes' means what changes in their work" if audience else "",
        f"Headline: {brief.headline}",
        f"Summary: {brief.summary}",
        f"Why it matters: {brief.why_it_matters}" if getattr(brief, "why_it_matters", None) else "",
        f"Key facts: {facts}" if facts else "",
        f"Tone: {brief.tone}",
    ]))
    hook = None
    for attempt in range(2):
        try:
            raw = llm.complete_json(_HOOK_SYSTEM, user)
        except LLMUnavailable:
            raise
        except Exception as exc:
            logger.warning("viral: hook call failed (%s)", exc)
            break
        hook = _first_good(raw, brief.headline)
        if hook:
            break
        logger.info("viral: hooks rejected (%s); asking again", str(raw)[:200])
        user += ("\nYour last options only described the event or broke a rule. Open a question "
                 "or name the stakes instead.")
    if hook is None:  # poster-core's own hook, when it is short enough
        hook = clean_hook(getattr(brief, "hook", None), brief.headline)
    logger.info("viral: hook %r", hook)
    return hook


_ACRONYM = re.compile(r"\b([A-Z]{2,3})\b")


def spoken(text: str) -> str:
    """Hook as the voice should say it: short acronyms letter by letter ('AI' -> 'A I')."""
    return _ACRONYM.sub(lambda m: " ".join(m.group(1)), text)
