"""Write the spoken script: one short line per slide, for the ear."""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

_MAX_WORDS = 15

_SYSTEM = (
    "You write the voice-over for a fast, vertical news Reel that decodes the story behind the headline — "
    "one spoken line per slide. "
    "Rules: write for the EAR, not the eye -- short, conversational, punchy sentences; second person "
    "and present tense where natural. Line 1 is the hook: tension or a question, never a statement of "
    "the headline, and at most 8 words. Each middle line is 6-12 words and adds ONE idea that must NOT "
    "read the on-screen text word for word. Scene-type guidance: "
    "'why' scenes → name the underlying force or incentive driving the story; "
    "'impact' scenes → say concretely who wins and who pays; "
    "'bigger_picture' scenes → zoom out and place the event in its larger context; "
    "'scream' scenes → say the number loudly with its unit and why it shocks. "
    "Be brisk: this is a 30-second news update, cut every filler word. The last slide is a "
    "five-word call to follow the channel by name. Use ONLY facts present in "
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


_SPELLED = re.compile(r"\b[A-Z](?: [A-Z])+\b")


def caption_text(line: str) -> str:
    """The spoken line as it should read on screen: letter-by-letter spellings
    written for the voice ('A I', 'G P U') are joined back ('AI', 'GPU')."""
    return _SPELLED.sub(lambda m: m.group(0).replace(" ", ""), line)


_HAS_WORDS = re.compile(r"[A-Za-z0-9]{2,}")
_GENERIC = {
    "stats": "Here are the numbers that matter.",
    "comparison": "Here's how the two compare.",
    "timeline": "Here's how it unfolded.",
    "money_flow": "Now, follow the money.",
    "quote": "And here's what they said.",
    "evidence": "Here's what the evidence shows.",
    "why": "Here's what's really driving this.",
    "impact": "Here's who wins and who pays.",
    "bigger_picture": "Here's the bigger picture.",
    "scream": "That number says it all.",
    "conclusion": "Here's why it matters.",
}


def speakable(text: str) -> bool:
    """True if a TTS engine has real words to say (not '.', '...', an emoji)."""
    return bool(_HAS_WORDS.search(text or ""))


def _fallback_line(spec: dict, brand: str, last: bool) -> str:
    """A safe, speakable line derived from the slide itself; never empty."""
    if last:
        return f"Follow {brand.title()} for daily breakdowns."
    candidates = [spec.get("heading"), spec.get("body")]
    candidates += list(spec.get("facts") or [])[:1]
    candidates += [e.get("what") for e in (spec.get("timeline") or [])[:1]]
    candidates += [m.get("actor") for m in (spec.get("money") or [])[:1]]
    comparison = spec.get("comparison") or {}
    candidates += [comparison.get("title")]
    candidates += [(spec.get("quote") or {}).get("text")]
    for text in candidates:
        if text and speakable(text):
            return str(text).strip().rstrip(".!?") + "."
    return _GENERIC.get(spec.get("kind"), "Here's the next detail.")


def write_script(llm, brief, specs: list[dict], *, brand: str, hook: str | None = None) -> list[str]:
    """One line per spec. Any line the model fumbles is replaced by a safe
    fallback derived from the slide, so the result always matches `specs`.
    `hook` (already written for the ear) is spoken as line 1 instead of the model's."""
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
        if not speakable(text) or len(text.split()) > _MAX_WORDS:
            text = _fallback_line(spec, brand, last=(i == len(specs) - 1))
        out.append(text)
    if hook and out and speakable(hook):
        out[0] = hook
    return out
