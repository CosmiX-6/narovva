"""Write the spoken script -- one short line per slide, for the ear -- and,
in the same call, the on-screen direction that goes with it: each line as
the caption should read, the words to emphasise, the story's subject for
the reel's header, and verdict stamps. Everything the model returns is
checked against the slide data; anything that fails is dropped or replaced
by a safe fallback, so the result always lines up with the slides."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_MAX_WORDS = 15

_SYSTEM = (
    "You write the voice-over for a fast, vertical news Reel that decodes the story behind the headline — "
    "one spoken line per slide. "
    "Tell it like an investigator briefing the viewer: the hook opens a question, each middle line builds "
    "the case with one piece of evidence so the viewer needs the next line, and the line before the call "
    "to follow lands the verdict or the takeaway in one sentence. "
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
)

_DIRECTION = (
    "You also direct the on-screen graphics, in the same JSON. "
    '"screen": each line exactly as the burned-in caption should read it -- the same words, but numbers '
    'as digits ("67%", "$1.2B", "8") and abbreviations closed up ("AI", "GPU"). '
    '"marks": one object per slide, {"line": the 1-3 consecutive words of that caption a viewer must not '
    'miss, copied exactly, "heading": 1-2 consecutive words copied exactly from the slide heading to '
    'colour, or ""}. '
    '"subject": what the story is about in 1-3 words, for a case-file header (e.g. "STARLINK", '
    '"CHIP EXPORTS"). '
)


def _stamp_rules(max_stamps: int) -> str:
    return (
        '"stamps": one entry per slide -- null, or a verdict stamp {"text": 1-3 words in capitals, '
        '"tone": "negative" | "positive" | "neutral"} slammed onto the evidence, like "BLOCKED", "DENIED", '
        '"-20%", "RECORD HIGH". A stamp states what that slide\'s own data shows, never an opinion or a '
        "guess, and any number in it must appear in that slide's data. No stamp on the first or the last "
        f"slide; at most {max_stamps} stamps in total, and fewer is better. "
    )


def _respond(max_stamps: int) -> str:
    keys = '"lines": [...], "screen": [...], "marks": [...], "subject": "..."'
    if max_stamps:
        keys += ', "stamps": [...]'
    return f"Respond as JSON: {{{keys}}} with EXACTLY one line per slide, in order."


@dataclass
class Script:
    """One spoken line per slide, plus the on-screen direction for each."""

    lines: list[str]
    screen: list[str]                      # each line as the caption shows it
    subject: str | None = None             # 1-3 words, capitals, for the header
    stamps: list[dict | None] = field(default_factory=list)   # {"text", "tone"} or None, per slide
    line_marks: list[str | None] = field(default_factory=list)
    heading_marks: list[str | None] = field(default_factory=list)


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


_NUMBER = re.compile(r"\d[\d,.]*")
_STAMP_CHARS = re.compile(r"^[A-Z0-9%$€£₹+\-−.,!?'&/× ]+$")
_SUBJECT_CHARS = re.compile(r"^[A-Z0-9&.'+\-/ ]+$")
_TONES = ("negative", "positive", "neutral")


def numbers_in(text: str) -> set[str]:
    return {m.group(0).replace(",", "").rstrip(".") for m in _NUMBER.finditer(text or "")}


def grounded(text: str, source: str) -> bool:
    """Every figure in `text` also appears in `source` (so nothing is invented)."""
    return numbers_in(text) <= numbers_in(source)


def clean_subject(raw) -> str | None:
    text = " ".join(str(raw or "").upper().split()).strip(" .:")
    if not text or len(text) > 24 or len(text.split()) > 3 or not _SUBJECT_CHARS.match(text):
        return None
    return text


def clean_stamp(raw, source: str) -> dict | None:
    if not isinstance(raw, dict):
        return None
    text = " ".join(str(raw.get("text") or "").upper().split()).strip(" .")
    if not text or len(text) > 18 or len(text.split()) > 3 or not _STAMP_CHARS.match(text):
        return None
    if not grounded(text, source):
        return None
    tone = str(raw.get("tone") or "").lower()
    return {"text": text, "tone": tone if tone in _TONES else "negative"}


def phrase_in(raw, text: str, max_words: int) -> str | None:
    """`raw` as it appears in `text` (whole words, any case), or None."""
    phrase = " ".join(str(raw or "").split()).strip(" .,;:!?\"'")
    if not phrase or len(phrase.split()) > max_words or not text:
        return None
    m = re.search(r"(?<!\w)" + re.escape(phrase) + r"(?!\w)", text, re.IGNORECASE)
    return m.group(0) if m else None


def auto_mark(screen: str) -> str | None:
    """The phrase to put on the caption pill when the model chose none: the
    first figure, else a proper noun, else the longest word."""
    words = [w.strip(".,;:!?\"'()") for w in screen.split()]
    for w in words:
        if any(ch.isdigit() for ch in w):
            return w
    for w in words[1:]:
        proper_noun = len(w) >= 4 and w[:1].isupper() and not w.isupper()
        acronym = len(w) >= 2 and w.isupper() and w.isalpha()
        if proper_noun or acronym:
            return w
    longest = max(words, key=len, default="")
    return longest if len(longest) >= 7 else None


def _screen_line(raw, line: str, source: str) -> str:
    """The caption: the model's digit version of the spoken line if it is the
    same line (similar length, no figure that the slide does not state), else
    the spoken line itself with letter-by-letter spellings closed up."""
    spoken = caption_text(line)
    text = " ".join(str(raw or "").split())
    n, m = len(spoken.split()), len(text.split())
    if not text or not speakable(text) or not (0.5 * n <= m <= 1.25 * n + 1) or not grounded(text, source):
        return spoken
    return text


def _pick(raw: dict, key: str) -> list:
    value = raw.get(key)
    return value if isinstance(value, list) else []


def write_script(
    llm, brief, specs: list[dict], *, brand: str, max_stamps: int = 0,
    hook: str | None = None, hook_screen: str | None = None, audience: str = "",
) -> Script:
    """One line (and its direction) per spec. Any line the model fumbles is
    replaced by a safe fallback derived from the slide, so the result always
    matches `specs`; any direction that fails its checks is dropped.
    `hook` (already written for the ear) is spoken as line 1 instead of the
    model's, and `hook_screen` (as written) is its caption."""
    payloads = [_slide_payload(i, s) for i, s in enumerate(specs)]
    system = _SYSTEM + _DIRECTION + (_stamp_rules(max_stamps) if max_stamps else "") + _respond(max_stamps)
    user = (
        f"Channel: {brand}\n"
        + (f"Audience: {audience}. Speak to them: what this changes in how they build or work.\n" if audience else "")
        + f"Story tone: {brief.tone}\nHeadline: {brief.headline}\n"
        f"Summary: {brief.summary}\nSlides ({len(specs)}):\n"
        + json.dumps(payloads, ensure_ascii=False)
    )
    try:
        raw = llm.complete_json(system, user)
    except Exception as exc:
        logger.warning("narration script LLM call failed (%s); using slide text", exc)
        raw = None
    if not isinstance(raw, dict):
        raw = {}
    lines, screens, marks, stamps = _pick(raw, "lines"), _pick(raw, "screen"), _pick(raw, "marks"), _pick(raw, "stamps")

    out = Script(lines=[], screen=[], subject=clean_subject(raw.get("subject")))
    last = len(specs) - 1
    for i, spec in enumerate(specs):
        text = str(lines[i]).strip() if i < len(lines) and lines[i] else ""
        if not speakable(text) or len(text.split()) > _MAX_WORDS:
            text = _fallback_line(spec, brand, last=(i == last))
        # What a figure on screen may come from: the slide's own data (not its position number).
        source = json.dumps({k: v for k, v in payloads[i].items() if k != "slide"}, ensure_ascii=False)
        screen = _screen_line(screens[i] if i < len(screens) else None, text, source)
        mark = marks[i] if i < len(marks) else None
        if not isinstance(mark, dict):
            mark = {"line": mark} if isinstance(mark, str) else {}
        stamp = clean_stamp(stamps[i] if i < len(stamps) else None, source) if max_stamps and 0 < i < last else None
        out.lines.append(text)
        out.screen.append(screen)
        out.line_marks.append(phrase_in(mark.get("line"), screen, 3) or auto_mark(screen))
        out.heading_marks.append(phrase_in(mark.get("heading"), spec.get("heading") or "", 2))
        out.stamps.append(stamp)
    kept = 0
    for i, stamp in enumerate(out.stamps):  # the model's first picks, up to the cap
        if stamp is not None:
            kept += 1
            if kept > max_stamps:
                out.stamps[i] = None
    if hook and out.lines and speakable(hook):
        out.lines[0] = hook
        out.screen[0] = hook_screen or caption_text(hook)
        out.line_marks[0] = auto_mark(out.screen[0])
    return out
