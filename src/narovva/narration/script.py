"""Write the spoken script: one short line per slide, for the ear."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_MAX_WORDS = 20

_SYSTEM = (
    "You write the voice-over for a fast, vertical tech/AI news Reel, one spoken line per slide. "
    "Rules: write for the EAR, not the eye -- short, conversational, punchy sentences; second person "
    "and present tense where natural. Line 1 is the hook: tension or a question, never a statement of "
    "the headline. Each middle line is 8-16 words, adds one idea, and must NOT read the on-screen text "
    "word for word. The last slide is a call to follow the channel by name. Use ONLY facts present in "
    "the slide data -- never invent numbers, names, quotes or claims. Spell numbers as words "
    '("sixty-seven percent", "one point two billion dollars") and spell out abbreviations that are read '
    'letter by letter with spaces ("A I", "G P U"). No emojis, no hashtags, no stage directions. '
    'Respond as JSON: {"lines": ["...", "..."]} with EXACTLY one line per slide, in order.'
)


def _slide_payload(i: int, spec: dict) -> dict:
    out = {"slide": i + 1, "kind": spec.get("kind")}
    for key in ("kicker", "heading", "body"):
        if spec.get(key):
            out[key] = spec[key]
    if spec.get("facts"):
        out["facts"] = spec["facts"]
    if spec.get("timeline"):
        out["timeline"] = spec["timeline"]
    if spec.get("money"):
        out["money_trail"] = spec["money"]
    if spec.get("comparison"):
        out["comparison"] = spec["comparison"]
    if spec.get("quote"):
        out["quote"] = spec["quote"]
    return out


def _fallback_line(spec: dict, brand: str, last: bool) -> str:
    if last:
        return f"Follow {brand.title()} for daily breakdowns."
    return (spec.get("heading") or spec.get("body") or "").rstrip(".") + "."


def write_script(llm, brief, specs: list[dict], *, brand: str) -> list[str]:
    """One line per spec. Any line the model fumbles is replaced by a safe
    fallback derived from the slide, so the result always matches `specs`."""
    user = (
        f"Channel: {brand}\nStory tone: {brief.tone}\nHeadline: {brief.headline}\n"
        f"Summary: {brief.summary}\nSlides ({len(specs)}):\n"
        + json.dumps([_slide_payload(i, s) for i, s in enumerate(specs)], ensure_ascii=False)
    )
    try:
        raw = llm.complete_json(_SYSTEM, user)
        lines = raw.get("lines") if isinstance(raw, dict) else None
    except Exception as exc:
        logger.warning("narration script LLM call failed (%s); using slide text", exc)
        lines = None
    if not isinstance(lines, list):
        lines = []
    out: list[str] = []
    for i, spec in enumerate(specs):
        text = str(lines[i]).strip() if i < len(lines) and lines[i] else ""
        if not text or len(text.split()) > _MAX_WORDS:
            text = _fallback_line(spec, brand, last=(i == len(specs) - 1))
        out.append(text)
    return out
