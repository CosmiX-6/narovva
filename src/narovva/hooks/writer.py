"""Write the hook and its package in one model call: five options, each a hook from
a named formula plus the cover text and the caption's first line that go with it.
Code then rejects options that break the rules, scores the hooks, and keeps the best."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from ..language import ENGLISH, Language
from ..llm import LLMUnavailable
from ..viral.detect import tokens
from .score import formulas_by_id, library, score
from .voice import find_banned

logger = logging.getLogger(__name__)

_BANNED_ALWAYS = ("you won't believe", "won't believe", "shocking", "this one trick", "mind-blowing",
                  "jaw-dropping")
_SELF_ANSWER = re.compile(r"\b(because|so that|which means|that's why)\b", re.I)
_NUM = re.compile(r"\d[\d,.]*")


@dataclass
class HookPackage:
    hook: str
    formula: str
    score: int
    cover: str | None = None   # 2-4 words on the reel's cover
    opener: str | None = None  # the caption's first line (Hinglish with a Hindi voice)
    spoken: str | None = None  # the hook as the Hindi voice says it (Devanagari); None for English


_HI_PACKAGE = (
    "LANGUAGE: this Reel is narrated in HINDI and its on-screen text is English. 'hook' and 'cover' stay English "
    "(they are shown on screen). Each option also has hook_spoken: the same hook as the Hindi voice says it -- "
    "natural, conversational Hindi in Devanagari, 4-14 words, English terms written in Devanagari (एआई, मॉडल, "
    "डेवलपर), any number as ASCII digits exactly as in the facts, the same idea and the same open question or "
    "stake, not a literal word-for-word translation. The 'opener' (the Instagram caption's first line) is written "
    "in HINGLISH: Hindi in Roman letters mixed with English terms, the way young Indian professionals post "
    "('Ye update aapke daily workflow ko badal sakta hai'), never in Devanagari. "
)


def _system(n: int, formulas: list[dict], style: str, language: Language = ENGLISH) -> str:
    shapes = "\n".join(f"- {f['id']}: {f['shape']} e.g. \"{f['example']}\" (fails when: {f['fails_when']})"
                       for f in formulas)
    rules = " ".join(library()["rules"])
    want = {"curiosity": "Prefer formulas that open a question.",
            "stakes": "Prefer formulas that name what is at stake for the viewer."}.get(style, "")
    return (
        "You package a 30-second vertical news Reel. The HOOK is the first line on screen and the first "
        "line spoken; it decides whether the viewer keeps watching. A plain description of the event is "
        f"NOT a hook. {rules} {want}\n"
        f"Write {n} options, each from a DIFFERENT formula below:\n{shapes}\n"
        "Each option has: hook (4-10 words, no emojis, no hashtags, no ALL CAPS, at most one question "
        "mark); formula (its id); cover (2-4 words for the cover image -- what the story is about, NOT "
        "the hook's words); opener (the caption's first line, max 120 characters: what the viewer gets "
        "from this post, not a repeat of the hook or the cover). Use only facts given. "
        + (_HI_PACKAGE if language.translated else "")
        + 'Respond as JSON: {"options": [{"hook": "...", "formula": "...", "cover": "...", "opener": "..."'
        + (', "hook_spoken": "..."' if language.translated else "")
        + "}]}"
    )


def _user(brief, audience: str, extra: str = "") -> str:
    facts = "; ".join(list(getattr(brief, "key_facts", []) or [])[:5])
    return "\n".join(filter(None, [
        f"Audience and house rules: {audience}" if audience else "",
        f"Headline: {brief.headline}",
        f"Summary: {brief.summary}",
        f"Why it matters: {brief.why_it_matters}" if getattr(brief, "why_it_matters", None) else "",
        f"Key facts: {facts}" if facts else "",
        f"Tone: {brief.tone}",
        extra,
    ]))


def _story_text(brief) -> str:
    return " ".join(str(x) for x in [
        brief.headline, brief.summary, getattr(brief, "why_it_matters", "") or "",
        " ".join(getattr(brief, "key_facts", []) or []), getattr(brief, "hook", "") or "",
    ])


def restates(hook: str, headline: str) -> bool:
    """A statement made mostly of the headline's own words is a summary, not a hook.
    (A question may reuse the subject: 'Why are diplomats under attack?')"""
    h, head = tokens(hook), tokens(headline)
    if not h or not head:
        return False
    share = len(h & head) / len(h)
    return share >= 0.75 or (share >= 0.5 and "?" not in hook)


def clean_hook(text, headline: str = "", *, story: str = "", banned: list[str] = ()) -> str | None:
    """A usable hook, or None. Rules: 3-11 words, real words, no clickbait or banned
    phrase, not the headline, no shouting, does not answer itself, and every number
    in it appears in the story."""
    if not text or not isinstance(text, str):
        return None
    hook = " ".join(text.strip().strip('"“”\'').split())
    hook = re.sub(r"[!]{2,}|[?]{2,}", lambda m: m.group(0)[0], hook)
    words = hook.split()
    if not 3 <= len(words) <= 11 or not re.search(r"[A-Za-z]{2,}", hook):
        return None
    low = hook.lower()
    if any(b in low for b in _BANNED_ALWAYS) or find_banned(hook, list(banned)):
        return None
    if low.rstrip(".?!") == headline.lower().rstrip(".?!") or restates(hook, headline):
        return None
    if sum(w.isupper() and len(w) > 4 for w in words) >= 2:  # shouting
        return None
    if _SELF_ANSWER.search(hook):
        return None
    if story and any(n.strip(".,") not in story for n in _NUM.findall(hook)):
        return None  # a number the story does not contain
    if hook[-1] not in ".?!":
        hook += "."
    return hook


def clean_cover(text, hook: str, *, banned: list[str] = ()) -> str | None:
    """2-4 words, at most 28 characters, no main word shared with the hook."""
    if not text or not isinstance(text, str):
        return None
    cover = " ".join(text.strip().strip('"“”\'').rstrip(".").split())
    words = cover.split()
    if not 2 <= len(words) <= 4 or len(cover) > 28 or find_banned(cover, list(banned)):
        return None
    if tokens(cover) & tokens(hook):
        return None
    return cover.upper()


def clean_spoken(text, language: Language, *, story: str = "", banned: list[str] = ()) -> str | None:
    """The hook as the voice says it, or None: real Hindi (Devanagari), 3-18 words, no clickbait
    or banned phrase, and every number in it appears in the story."""
    if not text or not isinstance(text, str):
        return None
    spoken = language.say(" ".join(text.strip().strip('"“”\'').split()))
    spoken = re.sub(r"[!]{2,}|[?]{2,}", lambda m: m.group(0)[0], spoken)
    if not 3 <= len(spoken.split()) <= 18 or not language.is_native(spoken):
        return None
    low = spoken.lower()
    if any(b in low for b in _BANNED_ALWAYS) or find_banned(spoken, list(banned)):
        return None
    if story and any(n.strip(".,") not in story for n in _NUM.findall(spoken)):
        return None
    if spoken[-1] not in ".?!।":
        spoken += "।"
    return spoken


def clean_opener(text, hook: str, cover: str | None, headline: str, *, banned: list[str] = (),
                 language: Language = ENGLISH) -> str | None:
    """One line, at most 125 characters (what Instagram shows before 'more'), not a
    repeat of the hook, the cover or the headline. With a Hindi voice it is Hinglish:
    Roman letters, no Devanagari."""
    if not text or not isinstance(text, str):
        return None
    opener = " ".join(text.strip().strip('"“”\'').split())
    if not 15 <= len(opener) <= 125 or find_banned(opener, list(banned)):
        return None
    if language.translated and not language.is_screen_text(opener):
        return None
    o = tokens(opener)
    for other in (hook, headline):
        t = tokens(other)
        if o and t and len(o & t) / len(o) >= 0.6:
            return None
    if cover and tokens(cover) and tokens(cover) <= o:
        return None
    if sum(w.isupper() and len(w) > 3 for w in opener.split()) > 2:
        return None
    return opener


def _options(raw) -> list[dict]:
    """Accept {"options": [...]}, or the older {"hooks": [...]} / {"hook": "..."} shapes."""
    if not isinstance(raw, dict):
        return []
    out = []
    for o in raw.get("options") or []:
        if isinstance(o, dict):
            out.append(o)
    for h in (raw.get("hooks") if isinstance(raw.get("hooks"), list) else []) + [raw.get("hook")]:
        if isinstance(h, str):
            out.append({"hook": h})
    return out


def pick(raw, brief, *, banned: list[str] = (), min_score: int = 45,
         allowed: set[str] | None = None, language: Language = ENGLISH) -> tuple[HookPackage | None, list[str]]:
    """Best option that passes the rules and the score; plus why the others failed. With a
    Hindi voice an option also needs a valid Hindi spoken version of its hook."""
    story = _story_text(brief)
    known = formulas_by_id()
    best, why = None, []
    for o in _options(raw):
        hook = clean_hook(o.get("hook"), brief.headline, story=story, banned=banned)
        if hook is None:
            why.append(f"{o.get('hook')!r}: breaks a rule")
            continue
        formula = o.get("formula") if o.get("formula") in known else None
        if allowed and formula and formula not in allowed:
            formula = None
        s = score(hook, formula)
        if s.verdict < min_score:
            why.append(f"{hook!r}: scored {s.verdict} ({s.weakest} weak)")
            continue
        spoken = None
        if language.translated:
            spoken = clean_spoken(o.get("hook_spoken"), language, story=story, banned=banned)
            if spoken is None:
                why.append(f"{hook!r}: no valid Hindi hook_spoken (Devanagari, 3-18 words, digits from the facts)")
                continue
        cover = clean_cover(o.get("cover"), hook, banned=banned)
        opener = clean_opener(o.get("opener"), hook, cover, brief.headline, banned=banned, language=language)
        cand = HookPackage(hook=hook, formula=s.formula, score=s.verdict, cover=cover, opener=opener,
                           spoken=spoken)
        # A complete package beats a slightly higher-scoring bare hook.
        key = (cand.score + (6 if cover else 0) + (4 if opener else 0))
        if best is None or key > best[0]:
            best = (key, cand)
    return (best[1] if best else None), why


def write_package(llm, brief, *, formulas: list[str] | None = None, style: str = "auto",
                  audience: str = "", banned: list[str] = (), min_score: int = 45,
                  candidates: int = 5, language: Language = ENGLISH) -> HookPackage | None:
    """Hook + cover + caption opener from the analysed story (so only real facts).
    Asks once more with the reasons if every option fails; then poster-core's own
    hook, if it passes the rules, as a bare hook."""
    lib = formulas_by_id()
    chosen = [lib[f] for f in (formulas or []) if f in lib] or list(lib.values())
    system = _system(min(candidates, len(chosen)), chosen, style, language)
    extra = ""
    for attempt in range(2):
        try:
            raw = llm.complete_json(system, _user(brief, audience, extra))
        except LLMUnavailable:
            raise
        except Exception as exc:
            logger.warning("hook: call failed (%s)", exc)
            break
        pkg, why = pick(raw, brief, banned=banned, min_score=min_score, allowed={f["id"] for f in chosen},
                        language=language)
        if pkg:
            logger.info("hook: %r formula=%s score=%d cover=%r opener=%r spoken=%r",
                        pkg.hook, pkg.formula, pkg.score, pkg.cover, pkg.opener, pkg.spoken)
            return pkg
        logger.info("hook: every option failed (%s); asking again", "; ".join(why)[:400])
        extra = ("Your last options failed: " + "; ".join(why)[:600] +
                 ". Do not describe the event; open a question or name the stakes.")
    fallback = clean_hook(getattr(brief, "hook", None), brief.headline, story=_story_text(brief), banned=banned)
    if fallback:
        s = score(fallback)
        logger.info("hook: using the brief's own hook %r (score %d)", fallback, s.verdict)
        return HookPackage(hook=fallback, formula=s.formula, score=s.verdict)
    logger.info("hook: none")
    return None
