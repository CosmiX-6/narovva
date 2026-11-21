"""Story first, pictures second: the explainer is written as a complete story before anything is drawn.

The other modes ask one model call for beats AND their scenes, so the story is written to fit the scene catalogue:
a news event gets squeezed into the nearest of a fixed set of 3D set pieces, and different stories come out looking
the same. Here it is the other way round:

  1. the WRITER tells the whole story (`write_story`), knowing nothing about scenes. Each beat states its facts and
     what a viewer should SEE while it is said, in the story's own words. The story is complete before it is drawn:
     every point the source makes that the viewer needs (who, what, when, why, the numbers, the impact, what next)
     must be covered, and the length follows the story rather than a beat budget;
  2. the DIRECTOR then designs a picture for each beat (`direct_story`): an information scene from the library when
     one fits what the beat says (a number counting up, a timeline, a quote...), otherwise a `compose` scene built
     for this beat -- the beat's own actors and objects, laid out and animated by what the beat says happens to them
     (connect, move, grow, block, highlight, count). Every label must come from the beat or the source.

A beat whose picture does not validate keeps its words and gets a plain headline: the story is never cut to fit a
picture. Everything downstream (narration, captions, timing, render) uses the result like any other Storyboard.
"""
from __future__ import annotations

import logging
import re

from ..language import ENGLISH, Language
from ..narration.script import numbers_in, phrase_in
from .local_director import local_direction
from .storyboard import (
    _SCENE_GUIDE,
    _SCENES,
    _TITLED,
    Storyboard,
    _beat_data,
    _cap_stamps,
    _cta_beat,
    _grim,
    _hook_line,
    _icon,
    _lines,
    _localise,
    _place_asks,
    _Source,
    _stamp,
    _text,
    _with_title,
    _words,
    estimate_seconds,
)

logger = logging.getLogger(__name__)

# How much of the article the writer reads. The other modes read the first 6,000 characters, so the end of a long
# story never reached the video; a story cannot be complete from half the article.
FULL_CHARS = 16000
# What a complete news explainer covers (when the source has it): checked after the writer, sent back once if missing.
COVERAGE = ("who", "what", "when", "why", "numbers", "impact", "next")
STORY_PARTS = ("hook", "context", "event", "evidence", "impact", "reaction", "next", "verdict", "ask", "cta")
# A soft ceiling only for runaway replies: Instagram takes Reels up to 3 minutes.
HARD_SECONDS = 170.0
LAYOUTS = ("row", "versus", "flow", "hub", "stack")
ACTIONS = ("appear", "connect", "move", "grow", "shrink", "block", "highlight", "count")
DIRECTED_SCENES = tuple(k for k in _SCENES if k not in ("world",)) + ("compose",)
_STOP = set("a an and are as at be but by for from has have in into is it its of on or that the their them they this "
            "to was were what when who why will with you your our we he she his her not no now new more than then".split())


# -- sources ---------------------------------------------------------------------------------------------------------

class FullSource(_Source):
    """`_Source` over (most of) the whole article: figures, quotes and receipts may come from anywhere in it."""

    def __init__(self, brief, article):
        super().__init__(brief, article)
        full = (getattr(article, "text", "") or "")[:FULL_CHARS]
        self.text = " ".join([brief.model_dump_json(), getattr(article, "title", "") or "", full])
        self.numbers = numbers_in(self.text)
        self.flat = " ".join(self.text.lower().split())
        from .storyboard import _plain
        self.article = " ".join(_plain(full).lower().split())


def content_words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9$%][a-z0-9$%.'-]*", str(text or "").lower()) if len(w) > 2 and w not in _STOP}


# -- pass 1: the writer ----------------------------------------------------------------------------------------------

def _story_system_en(brand: str, target_seconds: int, max_asks: int) -> str:
    asks = (f"VIEWER QUESTIONS: up to {max_asks} beats may be part \"ask\": the doubt the viewer would have right then, "
            "4-10 words ending in \"?\", as the beat's only line; the next beat answers it. Never in the first two "
            "beats or the last two, never two in a row.\n\n" if max_asks else "")
    return (
        f"You are the head writer of {brand}, an Instagram channel that explains the news in short vertical videos. "
        "Write the voice-over of ONE video as a sequence of beats. You are not choosing visuals -- an animation "
        "director designs a picture for every beat AFTER you, from what you write. So write the story the way the "
        "story deserves to be told, and for every beat describe what the viewer should SEE while it is said.\n\n"
        "COMPLETE, NOT SHORT: the viewer must finish with no open question the article answers. Cover everything "
        "the article gives them that they need: WHO is involved, WHAT happened, WHEN, WHY it happened or matters, "
        "the NUMBERS that make it real, the IMPACT (who wins, who pays, what changes for the viewer) and WHAT NEXT "
        f"(what happens now, what to watch). Aim for about {target_seconds} seconds but run longer rather than leave "
        "a point out -- never end on a cliffhanger the article resolves. Never pad: one point per beat, no repeats.\n\n"
        "ARC, each beat tagged with its \"part\":\n"
        "- \"hook\" (first beat; first line at most 9 words): open a loop the viewer needs closed -- a contradiction, "
        "the stakes, or a startling number. Never the headline restated, never \"did you know\".\n"
        "- \"context\": what the viewer must know to follow it.\n"
        "- \"event\" (one or more): what happened, step by step, with its actors.\n"
        "- \"evidence\": the proof -- figures, a quote, the article's own words.\n"
        "- \"impact\": who wins, who pays, what changes.\n"
        "- \"reaction\" (if the article has one): what the players said or did.\n"
        "- \"next\": what happens now or what to watch.\n"
        "- \"verdict\": the second-to-last beat lands the takeaway.\n"
        f"- \"cta\": the last beat, one line of at most 8 words naming {brand}.\n\n"
        + asks +
        "EACH BEAT: 1-3 spoken lines of 5-14 words, written for the ear (short, present tense, the way a sharp friend "
        "explains it; numbers spelled as words, abbreviations letter by letter with spaces: \"A I\"). Plus:\n"
        "- \"screen\": each line as the caption reads it (digits for numbers, AI not A I).\n"
        "- \"mark\": 1-3 words of each caption to highlight.\n"
        "- \"facts\": the facts from the source this beat states, each a short phrase with its figure as written.\n"
        "- \"show\": what the viewer should SEE, in this story's own nouns and verbs: who or what is on screen and "
        "what happens to them as the lines are said (\"OpenAI's price tag drops from $15 to $5 while three rival "
        "labs watch\"; \"a judge's gavel blocks the merger between X and Y\"). Concrete and specific to THIS beat -- "
        "never generic (\"an animation of AI\").\n"
        "- \"kicker\": optional chapter label, 1-3 words in capitals, on the first beat of a chapter.\n\n"
        "TRUTH: use only facts in the brief and the article. Never invent a number, date, name, quote or claim.\n\n"
        "COVERAGE: also return \"coverage\": for each of who, what, when, why, numbers, impact, next, the index of "
        "the beat that covers it (0-based), or \"n/a\" when the article has nothing for it.\n\n"
        'Respond as JSON: {"subject": "what the video is about in 1-3 words", "coverage": {"who": 0, ...}, '
        '"beats": [{"part": "...", "lines": ["spoken line", ...], "screen": [...], "mark": [...], "facts": [...], '
        '"show": "...", "kicker": "..."}, ...]}'
    )


def _story_user(brief, article, when: str, hook: str | None, audience: str, said: str | None, language: Language) -> str:
    title = getattr(article, "title", "") or brief.headline
    source = getattr(article, "source_name", "") or ""
    text = (getattr(article, "text", "") or "")[:FULL_CHARS]
    return (
        (f"Audience: {audience}. Speak to them: what this changes for them.\n" if audience else "")
        + _hook_line(hook, said, language)
        + f"Article: {title}\nSource: {source}\nDate: {when}\n\n"
        f"Brief:\n{brief.model_dump_json(exclude={'image_generation_prompt', 'image_search_query', 'visual_concepts'})}\n\n"
        f"Article:\n{text}"
    )


def parse_story(raw, src: FullSource, *, brand: str, language: Language = ENGLISH, cta=None,
                spoken_brand: str | None = None) -> tuple[list[dict], list[str]]:
    """Validated story beats (no scenes yet) and what the story still misses (`COVERAGE` items, parts)."""
    if not isinstance(raw, dict) or not isinstance(raw.get("beats"), list):
        return [], ["a story"]
    beats: list[dict] = []
    for b in raw["beats"]:
        if not isinstance(b, dict):
            continue
        part = str(b.get("part") or "").strip().lower()
        part = part if part in STORY_PARTS else "event"
        lines, screens, cmarks = _lines(b, src, language)
        if not lines:
            continue
        if part == "ask":
            lines, screens, cmarks = lines[:1], screens[:1], cmarks[:1]
            if not screens[0].rstrip().endswith("?"):
                continue
        facts = [f for f in (" ".join(str(x).split()) for x in (b.get("facts") or []) if x)
                 if f and len(f.split()) <= 20 and src.grounded(f)][:4]
        show = _text(b.get("show"), 45, 320) or ""
        if show and not src.grounded(show):
            show = ""
        kicker = _words(b.get("kicker"), 3)
        beats.append({"part": part, "lines": lines, "screens": screens, "cmarks": cmarks, "facts": facts,
                      "show": show, "kicker": kicker.upper() if kicker and src.grounded(kicker) else None})
    beats = [b for i, b in enumerate(beats) if b["part"] != "cta" or i == len(beats) - 1]
    if language.translated:
        cta = cta if isinstance(cta, tuple) else language.cta(brand.title(), spoken_brand=spoken_brand)
    if not beats or beats[-1]["part"] != "cta":
        said, caption = cta if isinstance(cta, tuple) else (cta, None)
        end = _cta_beat(brand, said, language, caption)
        beats.append({"part": "cta", "lines": end["lines"], "screens": end["screens"], "cmarks": end["cmarks"],
                      "facts": [], "show": "", "kicker": None})
    return beats, story_gaps(raw, beats)


def story_gaps(raw, beats: list[dict]) -> list[str]:
    """What a complete explainer of this article still lacks: coverage items the writer marked missing or pointed at a
    beat that did not survive validation, and the parts every news story needs."""
    gaps = []
    cov = raw.get("coverage") if isinstance(raw, dict) and isinstance(raw.get("coverage"), dict) else {}
    n_raw = len(raw.get("beats") or []) if isinstance(raw, dict) else 0
    kept_parts = {b["part"] for b in beats}
    for item in COVERAGE:
        v = cov.get(item)
        if isinstance(v, str) and v.strip().lower() in ("n/a", "na", "none"):
            continue
        if not isinstance(v, int) or not 0 <= v < n_raw:
            gaps.append(item)
    if len([b for b in beats if b["part"] not in ("cta", "ask")]) < 4:
        gaps.append("enough beats to tell it")
    for need in ("hook", "event", "impact"):
        if need not in kept_parts:
            gaps.append(f"a {need} beat")
    return gaps


def story_seconds(beats: list[dict]) -> float:
    return sum(max(2.0, sum(estimate_seconds(x) for x in b["lines"]) + 0.35) for b in beats)


# -- pass 2: the director --------------------------------------------------------------------------------------------

_COMPOSE_GUIDE = """\
- "compose": a picture BUILT FOR THIS BEAT when no scene above shows what it says -- the beat's own actors and objects,
  arranged and animated by what the lines say happens to them. Data:
  {"title": optional heading (max 6 words), "mark": 1-2 of its words,
   "layout": "row" (2-4 side by side) | "versus" (two sides facing off) | "flow" (things passing from one to the next,
     top to bottom) | "hub" (one centre, 2-5 around it) | "stack" (2-5 in a column, a ranking or a list of players),
   "actors": [{"id": "a", "label": max 3 words naming a real person, company, product, place, law or object of THIS
     story, "icon": a Lucide icon name that depicts it, "value": optional figure exactly as the source writes it,
     "note": optional max 5 words}, ...] (1-5),
   "steps": [{"line": index of the spoken line it happens on (0-based), "do": "appear" | "connect" (a link drawn from
     who to to, a pulse running down it) | "move" (a token travels from who to to; "label" names what moves, e.g.
     "$1.2B", "users", "data") | "grow" | "shrink" (who swells or shrinks; "value" = its new figure) | "block" (a red
     strike across who, or across the link who->to) | "highlight" (who lights up, the rest dim) | "count" (who's
     value counts up), "who": actor id, "to": actor id, "label": max 3 words, "value": figure}, ...] (1-8)}
  The actors and labels come from the beat's own words, facts and "show" -- never stock filler (\"AI\", \"tech\",
  \"people\") unless the beat is literally about that. The steps follow the order things happen in the lines."""


def _director_system_en(max_stamps: int) -> str:
    guide = _SCENE_GUIDE.replace("{world_pieces}", "").replace("{max_stamps}", str(max_stamps))
    guide = re.sub(r'- "world": .*?(?=- "cta")', "", guide, flags=re.S)
    return (
        "You are the animation director of a news explainer. The story is written: below are its beats, each with "
        "its spoken lines, the facts it states and what the writer wants the viewer to SEE. Design the picture for "
        "every beat. The picture serves the story -- never change, shorten or drop what is said.\n\n"
        "HOW TO CHOOSE: for each beat, ask what single image makes its lines clear with the sound off, then pick the "
        "scene that shows exactly that. A beat about one figure is a \"number\"; dates in order are \"dates\"; a real "
        "quote is \"quote\"; cause and effect is \"chain\"; the players and what happened to each is \"grid\"; who "
        "wins and who pays is \"split\"; before against after is \"compare\". When none of them shows THIS beat's "
        "actors doing THIS beat's action, build a \"compose\" scene for it. A \"headline\" only for a statement "
        "with nothing to show. Keep the beat's \"ask\" part as scene \"ask\" and its \"cta\" part as \"cta\".\n\n"
        "VARIETY COMES FROM THE STORY: two beats only look alike when they say alike things. Never the same scene "
        "twice in a row; two compose scenes in a row need different layouts.\n\n"
        "TRUTH: every label, title, figure and name must come from the beat's lines, facts or the source; every "
        "figure exactly as the source writes it. Quotes and source cards word for word.\n\n"
        + guide + "\n" + _COMPOSE_GUIDE + "\n\n"
        'Respond as JSON: {"beats": [{"i": beat index, "scene": "...", "kicker": optional, "stamp": optional, '
        '"data": {...}}, ...]} -- one entry per beat, in order.'
    )


def _director_user(beats: list[dict], brief, article) -> str:
    rows = []
    for i, b in enumerate(beats):
        rows.append({"i": i, "part": b["part"], "lines": b["screens"], "facts": b["facts"], "show": b["show"]})
    import json
    title = getattr(article, "title", "") or brief.headline
    return (f"Story: {title}\n\nBrief:\n{brief.model_dump_json(exclude={'image_generation_prompt', 'image_search_query', 'visual_concepts'})}\n\n"
            f"Beats:\n{json.dumps(rows, ensure_ascii=False, indent=1)}")


def _compose(d: dict, src: _Source, beat_words: set[str], n_lines: int) -> dict | None:
    """Clean compose data, or None. Every actor must be named from this beat (or the story's source), so the picture
    shows the story's own players rather than stock filler."""
    layout = str(d.get("layout") or "").strip().lower()
    layout = layout if layout in LAYOUTS else None
    actors, ids = [], {}
    for k, a in enumerate((d.get("actors") or [])[:5]):
        if not isinstance(a, dict):
            continue
        label = _words(a.get("label"), 3)
        value = _words(a.get("value"), 2)
        note = _text(a.get("note"), 5, 40)
        if not label or len(label) > 26 or not src.grounded(label, value or "", note or ""):
            continue
        if value and not numbers_in(value):
            value = None
        words = content_words(label)
        if words and not (words & beat_words or any(w in src.flat for w in words)):
            continue                                           # not this story's actor
        aid = str(a.get("id") or "abcde"[k]).strip()[:8] or "abcde"[k]
        ids[aid] = len(actors)
        actors.append({"id": aid, "label": label, "icon": _icon(a.get("icon")) or "sparkles", "value": value,
                       "note": note})
    if not actors:
        return None
    if layout is None:
        layout = "versus" if len(actors) == 2 else "row" if len(actors) <= 4 else "stack"
    if layout == "versus" and len(actors) != 2:
        layout = "row" if len(actors) <= 4 else "stack"
    if layout == "hub" and len(actors) < 3:
        layout = "row"
    steps = []
    for st in (d.get("steps") or [])[:8]:
        if not isinstance(st, dict):
            continue
        do = str(st.get("do") or "").strip().lower()
        who = str(st.get("who") or "").strip()
        if do not in ACTIONS or who not in ids:
            continue
        to = str(st.get("to") or "").strip()
        if do in ("connect", "move") and (to not in ids or to == who):
            continue
        label, value = _words(st.get("label"), 3), _words(st.get("value"), 2)
        if not src.grounded(label or "", value or ""):
            continue
        if do in ("grow", "shrink", "count") and value and not numbers_in(value):
            value = None
        line = st.get("line")
        line = line if isinstance(line, int) and 0 <= line < max(1, n_lines) else None
        steps.append({"do": do, "who": ids[who], "to": ids.get(to) if to in ids else None, "label": label,
                      "value": value, "line": line})
    # nothing told to happen: the actors arrive with the lines, in order
    if not steps:
        steps = [{"do": "appear", "who": k, "to": None, "label": None, "value": None,
                  "line": min(n_lines - 1, (k * n_lines) // len(actors)) if n_lines else 0}
                 for k in range(len(actors))]
    out = {"layout": layout, "actors": actors, "steps": steps}
    title = _text(d.get("title"), 6, 50)
    if title and src.grounded(title):
        out["title"], out["mark"] = title, phrase_in(d.get("mark"), title, 2)
    return out


def _plain_beat(b: dict) -> tuple[str, dict]:
    """A beat whose picture did not validate keeps its words, on a headline."""
    text = " ".join(b["screens"][0].split()[:10]) if b["screens"] else ""
    return "headline", {"text": text, "mark": b["cmarks"][0] if b["cmarks"] else None, "icon": None, "sub": None}


def _picks(raw) -> dict[int, dict]:
    picks = {}
    for e in (raw.get("beats") if isinstance(raw, dict) and isinstance(raw.get("beats"), list) else []):
        if isinstance(e, dict) and isinstance(e.get("i"), int):
            picks.setdefault(e["i"], e)
    return picks


def _picture(e: dict, b: dict, src: _Source, prev: str | None, prev_layout: str | None) -> tuple[str, dict] | None:
    """The validated picture `e` asks for on beat `b`, or None (invalid, or the same picture as the beat before)."""
    scene = str(e.get("scene") or "").strip().lower()
    data = _beat_data(e) if e else {}
    words = content_words(" ".join(b["lines"] + b["screens"] + b["facts"] + [b["show"]]))
    if scene == "compose":
        data = _compose(data, src, words, len(b["lines"]))
    elif scene in DIRECTED_SCENES and scene not in ("ask", "cta"):
        data = _SCENES[scene](data, src)
        if data is not None and scene in _TITLED:
            data = _with_title(data, _beat_data(e), src)
    else:
        data = None
    if data is None or (scene == "compose" and _grim(b["lines"], {})):
        return None
    if scene == prev and not (scene == "compose" and data["layout"] != prev_layout):
        return None                                             # the same picture twice in a row
    return scene, data


def direct_story(raw, beats: list[dict], src: _Source, backup=None) -> tuple[list[dict], dict]:
    """Attach a validated scene to every story beat. Returns (board beats, stats). `backup` is a second direction in
    the same shape (the local director's): a beat whose picture from `raw` fails takes the backup's before falling
    back to its words on a headline."""
    picks, spare = _picks(raw), _picks(backup)
    out, fallbacks, rescued, prev, prev_layout = [], 0, 0, None, None
    for i, b in enumerate(beats):
        e = picks.get(i, {})
        if b["part"] == "ask":
            scene, data = "ask", {"text": b["screens"][0]}
        elif b["part"] == "cta":
            scene, data = "cta", {}
        else:
            got = _picture(e, b, src, prev, prev_layout) if e else None
            if got is None and i in spare:
                got = _picture(spare[i], b, src, prev, prev_layout)
                rescued += got is not None
                e = e or spare[i]
            if got is None:
                got = _plain_beat(b)
                fallbacks += 1
            scene, data = got
        out.append({"scene": scene, "kicker": b["kicker"] or (_words(e.get("kicker"), 3) or "").upper() or None,
                    "data": data, "stamp": _stamp(e.get("stamp"), src) if e.get("stamp") else None,
                    "lines": b["lines"], "screens": b["screens"], "cmarks": b["cmarks"], "part": None,
                    "story_part": b["part"]})
        prev, prev_layout = scene, (data or {}).get("layout")
    stats = {"beats": len(out), "fallbacks": fallbacks, "rescued": rescued,
             "scenes": [b["scene"] + (":" + b["data"]["layout"] if b["scene"] == "compose" else "") for b in out]}
    return out, stats


def _ask(llm, system: str, user: str, accept):
    """One model call; a chain that can move past an unusable reply (FallbackLLM) is told how to judge one."""
    if getattr(llm, "takes_accept", False):
        return llm.complete_json(system, user, accept=accept)
    return llm.complete_json(system, user)


# -- the whole thing -------------------------------------------------------------------------------------------------

def write_story_first(llm, brief, article, *, brand: str, target_seconds: int = 60, max_stamps: int = 3,
                      when: str = "", hook: str | None = None, audience: str = "", max_asks: int = 2,
                      said: str | None = None, language: Language = ENGLISH,
                      spoken_brand: str | None = None) -> Storyboard | None:
    """Write the complete story, then direct a picture for each beat. None (after logging why) if the story could not
    be written; a beat whose picture fails keeps its words on a headline."""
    src = FullSource(brief, article)
    system = _localise(_story_system_en(brand, target_seconds, max_asks), language)
    user = _story_user(brief, article, when, hook, audience, said, language)
    best, best_gaps = None, None
    def usable(raw):                                   # a weak model's reply that is no story: ask the next model
        beats, gaps = parse_story(raw, src, brand=brand, language=language, spoken_brand=spoken_brand)
        core = [g for g in gaps if g in ("a story", "enough beats to tell it", "a hook beat", "a event beat")]
        return ", ".join(core) or None

    for attempt in range(2):
        try:
            raw = _ask(llm, system, user, usable)
        except Exception as exc:
            logger.warning("story writer LLM call failed (%s)", exc)
            break
        beats, gaps = parse_story(raw, src, brand=brand, language=language, spoken_brand=spoken_brand)
        subject = raw.get("subject") if isinstance(raw, dict) else None
        if beats and (best is None or len(gaps) < len(best_gaps)):
            best, best_gaps, best_subject = beats, gaps, subject
        if not gaps:
            break
        logger.warning("story is incomplete: missing %s (attempt %d)", ", ".join(gaps), attempt + 1)
        user = (user.split("\n\nYOUR LAST STORY")[0] + "\n\nYOUR LAST STORY LEFT OUT: " + ", ".join(gaps)
                + ". Beats are dropped when a figure is not in the article, a line is longer than 14 words or a beat "
                "has no spoken lines. Write the whole story again, complete.")
    if not best or len([b for b in best if b["part"] not in ("cta", "ask")]) < 3:
        logger.warning("story writer gave no usable story; using the slide-based reel")
        return None
    if best_gaps:
        logger.warning("story still lacks %s after a retry; telling it anyway", ", ".join(best_gaps))
    while story_seconds(best) > HARD_SECONDS and any(b["part"] == "ask" for b in best):
        best.pop(max(i for i, b in enumerate(best) if b["part"] == "ask"))
    content = len([b for b in best if b["part"] not in ("ask", "cta")])

    def directed(raw):                                 # most pictures failing: ask the next model
        failed = direct_story(raw, best, src)[1]["fallbacks"]
        return f"{failed} of {content} pictures failed" if failed * 2 > content else None

    try:
        raw_dir = _ask(llm, _director_system_en(max_stamps), _director_user(best, brief, article), directed)
    except Exception as exc:
        logger.warning("director LLM call failed (%s); the local director pictures the story", exc)
        raw_dir = {}
    # a beat whose picture fails takes the local director's (no model call), and only then its words on a headline
    beats, stats = direct_story(raw_dir, best, src, backup=local_direction(best, src, brief))
    beats = _place_asks(beats, max_asks)
    _cap_stamps(beats, max_stamps)
    logger.info("story-first: %d beats (~%.0fs), %d pictured locally, %d without a picture, scenes %s", len(beats),
                story_seconds(best), stats["rescued"], stats["fallbacks"], " ".join(stats["scenes"]))
    from .storyboard import clean_subject
    board = Storyboard(subject=clean_subject(best_subject), beats=beats, translated=language.translated)
    board.coverage_gaps = best_gaps or []
    board.signature = stats["scenes"]
    return board
