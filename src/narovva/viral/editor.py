"""Which of the viral stories is worth posting (informative, not gossip or a match
score). Hooks are written by narovva.hooks.writer; `write_hook` is kept as a shortcut."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from ..hooks.writer import clean_hook, restates, write_package  # noqa: F401  (re-exported)
from ..llm import LLMUnavailable
from .detect import Story

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


def write_hook(llm, brief, style: str = "auto", audience: str = "") -> str | None:
    """Just the hook text (see narovva.hooks.writer.write_package for the full package)."""
    pkg = write_package(llm, brief, style=style, audience=audience)
    return pkg.hook if pkg else None


_ACRONYM = re.compile(r"\b([A-Z]{2,3})\b")


def spoken(text: str) -> str:
    """Hook as the voice should say it: short acronyms letter by letter ('AI' -> 'A I')."""
    return _ACRONYM.sub(lambda m: " ".join(m.group(1)), text)
