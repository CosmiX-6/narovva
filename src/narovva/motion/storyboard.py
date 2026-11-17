"""The explainer storyboard: one LLM call turns the story brief (and the
article text) into 8-12 beats, each one to three spoken lines plus a
purpose-built motion-graphic scene that shows what the lines say -- a date
track, a cause-and-effect chain, a grid of players with verdict stamps, a
number that counts up, a quote with its key words highlighted, and so on.

Everything the model returns is validated here before it reaches the
template: unknown scenes and malformed data are dropped, every figure on
screen must appear in the source, a quote must be quoted word for word, and
the reel always ends on the call to follow. If too little survives, the
caller falls back to re-animating poster-core's carousel slides."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from ..narration.script import auto_mark, caption_text, clean_stamp, clean_subject, numbers_in, phrase_in, speakable
from .dataviz import comparison_viz, parse_metric, stats_viz
from .icon_names import ICON_NAMES
from .slides import SCENE_OVERLAP_SECONDS, time_parts

logger = logging.getLogger(__name__)

BEAT_TAIL = 0.35     # a beat holds this long after its last line (covers the transition)
BEAT_MIN = 2.0
_MAX_LINE_WORDS = 16
_EXCERPT_CHARS = 6000

_WORLD_PIECES = """\
  Every world beat takes "title" (what the beat means on screen, max 6 words) and "mark" (1-2 of its words). Labels
  are max 3 words and may use the metaphor's own words; any figure in them must be in the source. Items: money, goods,
  data, people, oil, chips, documents, pills, tokens. Line 1 sets the piece up, line 2 is the turn.
  {"piece": "gate", "gate": door sign, "crowd": who queues, "keeper": who decides, "allowed": label, "blocked": what the
   turned-away hear, "count": 1-6} -- a keeper lets the first few in, then a barrier drops (access, bans, approvals, limits).
  {"piece": "flow", "from": place, "to": place, "item": ..., "amount": optional figure, "change": "grows" | "stops" |
   "reverses" | "none"} -- things travel from one place to another (money, exports, data, people moving).
  {"piece": "pile", "item": ..., "label": what the pile is, "start": figure, "end": figure} -- a stock grows or drains.
  {"piece": "race", "lanes": [2-3 rivals], "leader": index} -- rivals run; the leader pulls away (competition, a lead).
  {"piece": "split", "crowd": who, "win": label, "lose": label, "share": 0.2-0.8 that win} -- one group splits into
   winners and losers.
  {"piece": "machine", "input": label, "machine": its sign, "output": label, "in_item": ..., "out_item": ...} -- inputs go
   in, something else comes out (what a product, a law or a model does, seen as a black box).
  {"piece": "wall", "left": place, "right": place, "wall": its sign, "item": ...} -- traffic crosses, then a wall goes up
   (tariffs, sanctions, a ban on trade).
  {"piece": "balance", "left": label, "right": label, "heavier": "left" | "right"} -- two sides weighed; the scale tips.
  {"piece": "steps", "steps": [2-4 labels, in order], "item": ..., "result": optional label} -- a parcel passes through
   stations that light up in turn (how something works, a process, a pipeline); one spoken line per step where you can.
  {"piece": "sort", "sorter": label, "bins": [2-3 labels], "item": ...} -- a sorter sends each arriving item into a bin
   (a filter, a classifier, triage, a router picking an expert).
  {"piece": "cluster", "groups": [2-3 labels], "query": optional label} -- scattered things gather with their own kind,
   then a newcomer lands beside the most similar (embeddings, similarity search, recommendations).
  {"piece": "hill", "start": label, "goal": label} -- a walker steps down a valley, the steps shrinking near the bottom
   (gradient descent, trial and error, homing in on the best answer).
  {"piece": "fetch", "asker": label, "shelf": label, "answer": label} -- a helper runs to the shelves for the right page
   before the answer is given (retrieval, search, looking something up first).
  {"piece": "focus", "words": [3-6 words of one short phrase, in order], "focus": index of the word that looks back,
   "strongest": index of the word it weighs most, "label": optional, "strong": optional label} -- beams from one word to
   the others, as thick as the attention it pays (attention, context, what matters most).
  {"piece": "slice", "whole": label, "parts": [2-6 short pieces, in order]} -- one thing is cut into pieces that slide
   apart (a sentence into tokens, a document into chunks, a budget into its parts).
  {"piece": "window", "window": label, "size": 2-6, "item": ..., "dropped": label} -- things pass under a frame that
   holds only a few; the oldest fall off the end (a context window, memory, a queue).
  {"piece": "target", "thrower": label, "target": label, "result": optional label} -- throws scatter at first, then land
   closer once there is feedback (training, practice, learning from mistakes).
"""

_SCENE_GUIDE = """\
SCENES -- for every beat pick the scene that best SHOWS what its lines say. Use at least 5 different
scene types, never the same type twice in a row. Data shapes:
- "headline": {"text": the statement on screen (max 9 words), "mark": 1-2 of its words to colour, "icon": optional, "sub": optional line under it (max 10 words)}. For the hook or a turn in the story.
- "number": {"value": one figure as written in the source ("6", "30,000", "$1.2B", "-20%"), "unit": optional (max 2 words, e.g. "DAYS"), "label": what it counts (max 8 words), "from": optional figure it rose or fell from}. One figure that shocks.
- "question": {"text": one word or a very short question ("WHY?", "WHO PAYS?"), "icon": ...}. When the next beats answer it.
- "dates": {"events": [{"when": "17 OCT", "what": "max 7 words"}, ...]} -- 2-5 events in order; the focus moves to the next date with each spoken line, so give the beat one line per event where you can.
- "chain": {"nodes": [{"label": "max 3 words", "sub": "max 6 words", "icon": ...}, ...], "broken": optional index of the link that fails (1 = between node 1 and node 2)} -- 2-4 nodes, top to bottom: how something works, or how one thing led to another.
- "grid": {"items": [{"label": "max 3 words", "sub": "max 4 words", "icon": ..., "stamp": optional 1-2 words like "BLOCKED"}, ...]} -- 2-8 players, products or places, and what happened to each.
- "cards": {"items": [{"tag": "a date or a short label", "text": "max 14 words", "stamp": optional {"text": ..., "tone": ...}}, ...]} -- 1-3 pieces of evidence, one card per spoken line.
- "stats": {"items": ["67% cheaper per token", ...]} -- 1-3 facts, each containing a figure.
- "compare": {"title": optional, "a": {"label": ..., "value": ...}, "b": {"label": ..., "value": ...}} -- before and after, or one side against the other.
- "split": {"left": {"title": "WINS", "items": ["max 4 words", ...]}, "right": {"title": "LOSES", "items": [...]}} -- who gains and who pays (1-3 items a side).
- "quote": {"text": a quote copied word for word from the source, "who": the speaker and role, "mark": 2-5 consecutive words of it to highlight}. Only for a real quote.
- "terminal": {"title": "max 3 words", "lines": ["max 9 words", ...]} -- 2-4 lines typed out like a log; for technology stories.
- "checklist": {"title": "max 10 words", "mark": 1-2 of its words to colour, "items": ["max 6 words", ...], "icon": optional} -- 2-3 items: the takeaway, or what to watch next.
- "ask": {"text": the question exactly as spoken} -- the VIEWER interrupts: the one question they would ask right now
  ("Wait, why would they cut their own prices?"), 4-10 words ending in "?", as the beat's only line. The next beat answers it.
- "source": {"text": one or two sentences copied WORD FOR WORD from the article excerpt (8-40 words), "mark": 2-6
  consecutive words of it to highlight} -- the receipt: the article's own words on screen, proving the key claim.
- "recap": {"title": "max 6 words", "rows": [{"label": "max 4 words", "note": "max 7 words"}, ...]} -- 2-4 rows: the
  short version (one row per option, player or takeaway), one spoken line per row where you can.
- "world": a 3D scene where characters and objects ACT OUT the story -- the most memorable scene in a reel, so use
  one or two whenever the story has one of these shapes.
{world_pieces}- "cta": {} -- the last beat only: the call to follow (or to save the video, when it is a how-to worth keeping).
Scenes that build up (dates, chain, grid, cards, split, stats, recap) may also carry "title": a section heading of at most 6
words that stays on screen while the scene builds ("Check the facts", "His track record"), and "mark": 1-2 of its words
to colour.
Any beat may also have "kicker" (a chapter label, 1-3 words in capitals: "THE BACKSTORY", "WHAT HAPPENED", "THE FALLOUT") and
"stamp" ({"text": 1-3 words in capitals, "tone": "negative" | "positive" | "neutral"}): a verdict the beat's own facts support,
slammed onto the scene. At most {max_stamps} beats may carry stamps (a grid's or cards' item stamps count as one), never the
first or the last beat."""


def _system(brand: str, max_beats: int, target_seconds: int, max_stamps: int, max_asks: int = 2) -> str:
    asks = (
        f"VIEWER QUESTIONS: up to {max_asks} beats use scene \"ask\": the viewer interrupts with the doubt they would "
        "have at that moment (\"Wait, so who pays for it?\"), and the next beat answers it. Never in the first two "
        "beats or the last two, never two in a row. They make the video feel like a conversation, not a "
        "lecture: put them where the story turns.\n\n"
        if max_asks else ""
    )
    guide = _SCENE_GUIDE.replace("{max_stamps}", str(max_stamps)).replace("{world_pieces}", _WORLD_PIECES)
    return (
        f"You are the head writer and motion-graphics director of {brand}, an Instagram channel that explains "
        "the news in short vertical videos. Turn the story below into a storyboard: a sequence of beats, each "
        "one or two spoken lines plus one animated scene that SHOWS what those lines say, so the story is "
        "clear even with the sound off. The viewer should finish understanding ONE idea they could explain to "
        "a friend.\n\n"
        f"STORY ARC ({min(8, max_beats)}-{max_beats} beats, about {target_seconds} seconds):\n"
        "1. Hook (first line, at most 9 words): open a loop the viewer needs closed -- a contradiction with the "
        "named players in it (\"The two biggest labs just did the opposite thing\"), what is at stake for the "
        "viewer, or a startling number. Never the headline restated, never \"did you know\", never a greeting.\n"
        "2. Context: what the viewer must know to follow it. When the story rests on a mechanism (how pricing, a "
        "law, a chip, a market works), explain it with ONE everyday analogy (\"your API is a nightclub; every "
        "request is a guest\"), introduced once and then reused in later lines with the same words. No analogy "
        "is better than a strained one.\n"
        "3. What happened: the event step by step, with its dates and actors -- one concrete example worked "
        "through beats a list of facts.\n"
        "4. Fallout: the consequences in numbers, who wins and who pays, how others reacted. Prove the key claim "
        "once with the article's own words (scene \"source\") when it states it plainly.\n"
        "5. Verdict: the second-to-last beat lands the takeaway in one line, the principle or what to watch next "
        "(a \"recap\" table when the story compares options).\n"
        f"6. Call to follow: the last beat, scene \"cta\", one line of at most 8 words naming {brand}.\n"
        "PACE: a new beat every 2-4 seconds. One or two spoken lines a beat (three only for dates and cards), "
        "5-12 words a line, each line making the next one necessary. Write for the ear: short conversational "
        "sentences, present tense, the way a sharp friend would tell it. Spell numbers as words in the spoken "
        "lines (\"sixty-seven percent\") and abbreviations read letter by letter with spaces (\"A I\"). No "
        "emojis, hashtags or stage directions.\n\n"
        + asks
        + "TRUTH: use only facts in the brief and the article excerpt. Never invent a number, date, name, quote "
        "or claim; every figure on screen must appear in the source. If the story has few numbers, explain it "
        "with diagrams (chain, grid, dates) instead of inventing data.\n\n"
        + guide
        + "\nIcons (use only these names): " + ", ".join(sorted(ICON_NAMES)) + "\n\n"
        'Respond as JSON: {"subject": "what the story is about in 1-3 words, for a case-file header", '
        '"beats": [{"scene": "...", "lines": ["spoken line", ...], "screen": ["each line as the caption reads '
        'it: digits for numbers, AI not A I", ...], "mark": ["1-3 words of each caption to highlight", ...], '
        '"kicker": "...", "data": {...}, "stamp": ...}, ...]}'
    )


def _user(brief, article, when: str, hook: str | None = None, audience: str = "") -> str:
    title = getattr(article, "title", "") or brief.headline
    source = getattr(article, "source_name", "") or ""
    text = (getattr(article, "text", "") or "")[:_EXCERPT_CHARS]
    return (
        (f"Audience: {audience}. Speak to them: what this changes in how they build or work.\n" if audience else "")
        + (f"Opening hook, already written -- the first beat's first line, word for word: {hook}\n" if hook else "")
        + f"Article: {title}\nSource: {source}\nDate: {when}\n\n"
        f"Brief:\n{brief.model_dump_json(exclude={'image_generation_prompt', 'image_search_query', 'visual_concepts'})}\n\n"
        f"Article excerpt:\n{text}"
    )


# -- the animated story ("animated" mode): every beat is a moment in one 3D world -----

ANIMATED_SCENES = {"world", "ask", "source", "recap", "cta"}
MIN_WORLD_BEATS = 3

_ANIMATED_EXTRAS = """\
Besides world beats, a video may use only these:
- "ask": {"text": the question exactly as spoken} -- the VIEWER interrupts with the one question they would ask right
  now ("Wait, so does it actually read words?"), 4-10 words ending in "?", as the beat's only line. The next beat answers it.
- "source": {"text": one or two sentences copied WORD FOR WORD from the source text (8-40 words), "mark": 2-6
  consecutive words of it to highlight} -- the receipt, shown over the blurred world. At most one, for the key claim.
- "recap": {"title": "max 6 words", "rows": [{"label": "max 4 words", "note": "max 7 words"}, ...]} -- 2-4 rows: the
  short version, one spoken line per row where you can. Only as the second-to-last beat.
- "cta": {} -- the last beat only.
Any beat may have "kicker": a chapter label, 1-3 words in capitals, shown in the chip at the top ("THE IDEA", "HOW IT
WORKS", "THE CATCH"); give it on the first beat of each chapter."""


def _system_animated(brand: str, max_beats: int, target_seconds: int, max_asks: int = 2, lesson: bool = False) -> str:
    asks = (
        f"VIEWER QUESTIONS: up to {max_asks} beats are \"ask\" beats: the viewer cuts in with the doubt they would have "
        "right then, and the next beat answers it. Never in the first two beats or the last two, never two in a row.\n\n"
        if max_asks else ""
    )
    if lesson:
        what = "teaches how AI works, one small idea at a time,"
        arc = (
            f"LESSON ARC (about {max(10, max_beats - 4)}-{max_beats} beats, about {target_seconds} seconds -- it may "
            "run longer rather than skip a part; NEVER stop before the takeaway). Tag every beat with its \"part\":\n"
            "1. \"hook\": the everyday puzzle this idea explains (already written: the first line, word for word); "
            "the second line promises the answer is simple.\n"
            "2. \"answer\": the whole idea in ONE plain sentence a ten-year-old would get -- no jargon at all.\n"
            "3. \"metaphor\" (1-2 beats): ONE everyday picture of the idea (\"Think of the model as a reader who "
            "only sees Lego bricks\"), then its MAP, one pair per line: each everyday part and the real thing it "
            "stands for (\"Each brick is a token. The box of every brick is the vocabulary.\"). The world IS this "
            "metaphor for the rest of the video.\n"
            "4. \"how\" (2-4 beats): how it works, one step per beat, in order, acted out in the world, in the "
            "metaphor's words with the real term alongside (\"the tokenizer -- the brick cutter\").\n"
            "5. \"example\": follow ONE concrete case the viewer knows all the way through (a real sentence, a "
            "real photo, a real question).\n"
            "6. \"catch\": where the metaphor breaks, or the real limit -- so nobody leaves with a wrong picture.\n"
            "7. \"takeaway\": scene \"recap\" as the metaphor's key: one row per pair, the everyday word as the "
            "label and what it really is as the note -- or one line they could repeat to a friend.\n"
            f"8. \"cta\": the last beat, scene \"cta\": one line of at most 10 words asking them to save it and "
            f"follow {brand}.\n"
            "An \"ask\" beat (part \"ask\") voices the confusion a learner would have right then, and the next "
            "beat clears it up.\n"
            "TEACHING (ELI5): talk to a curious twelve-year-old. Everyday words, short sentences, one new idea per "
            "line. Show it first, then name it: a technical word only after its everyday picture (\"this is called "
            "a token\"), and an abbreviation only after its full name. Keep the metaphor's words the same in every "
            "line, label and recap row. Every step follows from the one before. NO maths, formulas or notation "
            "(no \"O of n squared\", no \"dot product\", no matrices, vectors, queries and keys): say what it "
            "DOES in everyday words (\"it gets slow fast as the text grows\"). At most one new technical word per "
            "beat, and only the ones the viewer needs.\n"
        )
        truth = (
            "TRUTH: the metaphor and the examples are yours; the FACTS are not. Every claim about how the technology "
            "works must agree with the reference text, and every figure on screen must appear in it. Explain, never "
            "exaggerate: no claims that AI \"thinks\", \"knows\" or \"understands\" unless the reference says so.\n\n"
        )
    else:
        what = "explains the news"
        arc = (
            f"STORY ARC ({min(8, max_beats)}-{max_beats} beats, about {target_seconds} seconds):\n"
            "1. Hook (first line, at most 9 words): open a loop the viewer needs closed -- a contradiction with the "
            "named players in it, what is at stake for the viewer, or a startling number. Never the headline "
            "restated, never \"did you know\", never a greeting.\n"
            "2. Context: the one thing the viewer must know to follow it, through ONE everyday metaphor that the "
            "world acts out (\"your API is a nightclub; every request is a guest\"), kept for the whole video.\n"
            "3. What happened: the event step by step, with its actors, as the world changes.\n"
            "4. Fallout: who wins and who pays, in numbers where the article has them.\n"
            "5. Verdict: the second-to-last beat lands the takeaway or what to watch next.\n"
            f"6. The last beat, scene \"cta\": one line of at most 8 words naming {brand}.\n"
        )
        truth = (
            "TRUTH: use only facts in the brief and the article excerpt. Never invent a number, date, name, quote or "
            "claim; every figure on screen must appear in the source.\n\n"
        )
    return (
        f"You are the head writer and animation director of {brand}, an Instagram channel that {what} in short "
        "vertical videos made as ONE continuous animation: a small 3D world of characters and objects, where the "
        "camera flies from one scene of the world to the next as the voice tells the story. Turn the material "
        "below into that animation: a sequence of beats, each one or two spoken lines plus the moment of the "
        "world that SHOWS what those lines say, so the video is clear with the sound off. The viewer should "
        "finish understanding ONE idea they could explain to a friend.\n\n"
        + arc
        + f"WORLD: at least {MIN_WORLD_BEATS} beats, and most of them, are scene \"world\" -- the first beat too (its "
        "\"title\" is the hook, at most 9 words). Pick the set piece whose action IS what the lines say, use at least "
        "3 different pieces, and name the characters and objects with the metaphor's words so the world tells one "
        "story. Every world beat has a \"title\".\n"
        "PACE: a new beat every 3-5 seconds. One or two spoken lines a beat (more only for steps), 5-12 words a "
        "line, each line making the next one necessary. Write for the ear: short conversational sentences, present "
        "tense, the way a sharp friend would explain it. Spell numbers as words in the spoken lines (\"sixty-seven "
        "percent\") and abbreviations read letter by letter with spaces (\"A I\"). No emojis, hashtags or stage "
        "directions.\n\n"
        + asks + truth
        + 'SCENES -- "world": {"piece": ..., "title": ..., the piece\'s fields}. The pieces:\n' + _WORLD_PIECES
        + _ANIMATED_EXTRAS + "\n\n"
        "RESPECT: never act out deaths, injuries, victims or other harm to people in the world -- no piles, "
        "counts, races or crowds of people who were hurt, nothing anyone could read as celebrating. Say those "
        "facts in the spoken lines over a calm world beat about the system, the cause or the response, or with "
        "the \"source\" receipt.\n"
        "FIELDS: every scene's fields go INSIDE \"data\". Write figures as strings, exactly as the source writes "
        "them (\"2.6 million\", \"$5\", \"67%\"), never as bare numbers. An item is one of the listed items.\n\n"
        'Respond as JSON: {"subject": "what the video is about in 1-3 words", '
        + ('"metaphor": {"picture": "the everyday picture in one line", "map": [{"everyday": "brick", '
           '"real": "token"}, ...]}, ' if lesson else "")
        + '"beats": [{"scene": "...", ' + ('"part": "...", ' if lesson else "")
        + '"lines": ["spoken line", ...], "screen": ["each line as the caption reads '
        'it: digits for numbers, AI not A I", ...], "mark": ["1-3 words of each caption to highlight", ...], '
        '"kicker": "...", "data": {...}}, ...]}\n'
        'For example: {"scene": "world", "kicker": "THE IDEA", "lines": ["Think of the model as a reader of '
        'Lego bricks.", "It never sees the letters."], "screen": [...], "mark": ["Lego bricks", "letters"], '
        '"data": {"piece": "slice", "title": "It reads in bricks", "mark": "bricks", "whole": "strawberry", '
        '"parts": ["str", "aw", "berry"]}} and {"scene": "ask", "lines": ["Wait, so it never sees letters?"], '
        '"screen": ["Wait, so it never sees letters?"], "data": {"text": "Wait, so it never sees letters?"}}'
    )


def _user_lesson(brief, article, lesson, audience: str = "") -> str:
    text = (getattr(article, "text", "") or "")[:_EXCERPT_CHARS]
    return (
        (f"Audience: {audience}. Speak to them.\n" if audience else "")
        + f"Lesson: {lesson.title}\nSeries: {lesson.series}\n"
        + (f"Opening hook, already written -- the first beat's first line, word for word: {lesson.hook}\n" if lesson.hook else "")
        + (f"A metaphor that works (use it, or a clearly better one): {lesson.metaphor}\n" if lesson.metaphor else "")
        + f"Reference: {getattr(article, 'source_name', '') or 'reference'}\n\n"
        f"Brief:\n{brief.model_dump_json(exclude={'image_generation_prompt', 'image_search_query', 'visual_concepts'})}\n\n"
        f"Reference text:\n{text}"
    )


@dataclass
class Storyboard:
    subject: str | None
    beats: list[dict] = field(default_factory=list)   # validated: scene, kicker, data, stamp, lines, screens, cmarks, part
    metaphor: dict | None = None                       # lessons: {"picture": ..., "map": [{"everyday", "real"}, ...]}


# -- field cleaning ------------------------------------------------------------

def _words(text, limit: int) -> str | None:
    """A short label: whitespace collapsed, at most `limit` words (else None)."""
    t = " ".join(str(text or "").split()).strip()
    if not t or len(t.split()) > limit:
        return None
    return t


def _text(text, limit: int, max_chars: int = 140) -> str | None:
    t = " ".join(str(text or "").split()).strip()
    if not t or len(t.split()) > limit or len(t) > max_chars:
        return None
    return t


def _icon(name) -> str | None:
    n = str(name or "").strip().lower().replace("_", "-").replace(" ", "-")
    return n if n in ICON_NAMES else None


class _Source:
    """What the storyboard may draw on: the brief and the article excerpt."""

    def __init__(self, brief, article):
        self.text = " ".join([
            brief.model_dump_json(), getattr(article, "title", "") or "",
            (getattr(article, "text", "") or "")[:_EXCERPT_CHARS],
        ])
        self.numbers = numbers_in(self.text)
        self.flat = " ".join(self.text.lower().split())
        self.article = " ".join(_plain((getattr(article, "text", "") or "")[:_EXCERPT_CHARS]).lower().split())
        self.publisher = " ".join(str(getattr(article, "source_name", "") or "").split())[:40] or None
        quote = getattr(brief, "notable_quote", None)
        self.quotes = [" ".join(quote.text.lower().split())] if quote and quote.text else []

    def grounded(self, *texts) -> bool:
        return all(numbers_in(t or "") <= self.numbers for t in texts)

    def verbatim(self, quote: str) -> bool:
        q = " ".join(quote.lower().strip(" \"'“”‘’").split())
        return len(q) >= 12 and (q in self.flat or any(q in s for s in self.quotes))

    def in_article(self, passage: str) -> bool:
        """The passage appears in the article excerpt itself, word for word (quote marks and
        apostrophes normalised), so a "source" card only ever shows what the article said."""
        p = " ".join(_plain(passage).lower().strip(" \"'").split())
        return len(p) >= 30 and p in self.article


def _plain(text: str) -> str:
    """Curly quotes and dashes as their plain forms, for word-for-word comparison."""
    return str(text).translate(str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-"}))


def _stamp(raw, src: _Source) -> dict | None:
    if isinstance(raw, str):
        raw = {"text": raw, "tone": "negative"}
    return clean_stamp(raw, src.text)


# -- scenes ------------------------------------------------------------------
# Each takes the model's `data` and returns clean template data, or None.

def _headline(d, src):
    text = _text(d.get("text"), 10, 80)
    if not text or not src.grounded(text):
        return None
    sub = _text(d.get("sub"), 12, 90)
    return {"text": text, "mark": phrase_in(d.get("mark"), text, 2), "icon": _icon(d.get("icon")),
            "sub": sub if sub and src.grounded(sub) else None}


def _number(d, src):
    value = _words(d.get("value"), 1)
    metric = parse_metric(value) if value else None
    label = _text(d.get("label"), 9, 70)
    if not metric or not label or not src.grounded(value, label):
        return None
    out = {"value": value, "metric": metric, "label": label, "unit": _words(d.get("unit"), 2),
           "down": value.lstrip().startswith(("-", "−")), "from": None}
    start = _words(d.get("from"), 1)
    start_metric = parse_metric(start) if start else None
    if start_metric and src.grounded(start) and start_metric["unit"] == metric["unit"]:
        out["from"] = start_metric
        out["down"] = out["down"] or start_metric["base"] > metric["base"]
    return out


def _question(d, src):
    text = _words(d.get("text"), 4)
    if not text or len(text) > 22 or not src.grounded(text):
        return None
    return {"text": text, "icon": _icon(d.get("icon")) or "circle-help"}


def _dates(d, src):
    events = []
    for e in (d.get("events") or [])[:5]:
        if not isinstance(e, dict):
            continue
        when, what = _words(e.get("when"), 4), _text(e.get("what"), 9, 70)
        if when and src.grounded(when, what or ""):
            events.append({"when": when, "what": what or ""})
    return {"events": events} if len(events) >= 2 else None


def _chain(d, src):
    nodes = []
    for n in (d.get("nodes") or [])[:4]:
        if not isinstance(n, dict):
            continue
        label, sub = _words(n.get("label"), 4), _text(n.get("sub"), 8, 60)
        if label and src.grounded(label, sub or ""):
            nodes.append({"label": label, "sub": sub, "icon": _icon(n.get("icon"))})
    if len(nodes) < 2:
        return None
    broken = d.get("broken")
    broken = broken if isinstance(broken, int) and 1 <= broken < len(nodes) else None
    return {"nodes": nodes, "broken": broken}


def _grid(d, src):
    items = []
    for it in (d.get("items") or [])[:8]:
        if not isinstance(it, dict):
            continue
        label, sub = _words(it.get("label"), 4), _words(it.get("sub"), 5)
        if label and src.grounded(label, sub or ""):
            items.append({"label": label, "sub": sub, "icon": _icon(it.get("icon")), "stamp": _stamp(it.get("stamp"), src)})
    return {"items": items} if len(items) >= 2 else None


def _cards(d, src):
    items = []
    for it in (d.get("items") or [])[:3]:
        if not isinstance(it, dict):
            continue
        tag, text = _words(it.get("tag"), 5), _text(it.get("text"), 18, 120)
        if text and src.grounded(tag or "", text):
            items.append({"tag": tag, "text": text, "stamp": _stamp(it.get("stamp"), src)})
    return {"items": items} if items else None


def _stats(d, src):
    facts = [f for f in (_text(x, 10, 70) for x in (d.get("items") or [])[:3]) if f and src.grounded(f)]
    facts = [f for f in facts if parse_metric(f)]
    return {"items": facts} if facts else None


def _compare(d, src):
    a, b = d.get("a") or {}, d.get("b") or {}
    if not isinstance(a, dict) or not isinstance(b, dict):
        return None
    la, lb = _words(a.get("label"), 4), _words(b.get("label"), 4)
    va, vb = _words(a.get("value"), 3), _words(b.get("value"), 3)
    title = _text(d.get("title"), 8, 60)
    if not (la and lb and va and vb) or not src.grounded(va, vb, la, lb, title or ""):
        return None
    return {"title": title, "label_a": la, "value_a": va, "label_b": lb, "value_b": vb}


def _split(d, src):
    sides = {}
    for key in ("left", "right"):
        side = d.get(key) or {}
        if not isinstance(side, dict):
            return None
        title = _words(side.get("title"), 3)
        items = [x for x in (_words(i, 6) for i in (side.get("items") or [])[:3]) if x and src.grounded(x)]
        if not title or not items:
            return None
        sides[key] = {"title": title, "items": items}
    return sides


def _quote(d, src):
    text = _text(d.get("text"), 40, 240)
    who = _text(d.get("who"), 8, 60)
    if not text or not who or not src.verbatim(text):
        return None
    return {"text": text.strip("\"'“”‘’ "), "who": who, "mark": phrase_in(d.get("mark"), text, 6)}


def _terminal(d, src):
    lines = [x for x in (_text(i, 10, 60) for i in (d.get("lines") or [])[:4]) if x and src.grounded(x)]
    title = _words(d.get("title"), 4)
    title = title if title and src.grounded(title) else "log"
    return {"title": title, "lines": lines} if len(lines) >= 2 else None


def _checklist(d, src):
    title = _text(d.get("title"), 11, 80)
    items = [x for x in (_words(i, 7) for i in (d.get("items") or [])[:3]) if x and src.grounded(x)]
    if not title or not src.grounded(title) or not items:
        return None
    return {"title": title, "mark": phrase_in(d.get("mark"), title, 2), "items": items, "icon": _icon(d.get("icon"))}


def _ask(d, src):
    text = _text(d.get("text"), 12, 90)
    if not text or not text.endswith("?") or len(text.split()) < 3 or not src.grounded(text):
        return None
    return {"text": text}


def _source(d, src):
    text = _text(d.get("text"), 45, 320)
    if not text or len(text.split()) < 8 or not src.in_article(text):
        return None
    return {"text": text.strip(" \"'“”"), "mark": phrase_in(d.get("mark"), text, 6), "publisher": src.publisher}


def _recap(d, src):
    rows = []
    for r in (d.get("rows") or [])[:4]:
        if not isinstance(r, dict):
            continue
        label, note = _words(r.get("label"), 4), _text(r.get("note"), 8, 60)
        if label and src.grounded(label, note or ""):
            rows.append({"label": label, "note": note})
    return {"rows": rows} if len(rows) >= 2 else None


_ITEMS = {"money", "goods", "data", "people", "oil", "chips", "documents", "pills", "tokens"}
_PIECES = {"gate", "flow", "pile", "race", "split", "machine", "wall", "balance",
           "steps", "sort", "cluster", "hill", "fetch", "focus", "slice", "window", "target"}


def _index(value, n: int, default: int | None) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < n else default


def _labels(values, lo: int, hi: int, words: int, chars: int = 24) -> list[str] | None:
    """`lo`-`hi` short labels (each at most `words` words and `chars` characters), or None."""
    if not isinstance(values, list):
        return None
    out = [x for x in (_words(v, words) for v in values[:hi]) if x and len(x) <= chars]
    return out if len(out) >= lo else None


def _world(d, src):
    """A 3D set piece (templates/reel/world.js). Its labels may be the metaphor's own
    words, but any figure in them must come from the source."""
    piece = str(d.get("piece") or "").strip().lower()
    if piece not in _PIECES:
        return None
    label = lambda k, n=3: _words(d.get(k), n)
    kind = lambda k, default: (str(d.get(k) or "").strip().lower() if str(d.get(k) or "").strip().lower() in _ITEMS else default)
    out: dict = {"piece": piece}
    lists: list[str] = []
    if piece == "gate":
        out.update(gate=label("gate"), crowd=label("crowd"), keeper=label("keeper"), allowed=label("allowed", 2),
                   blocked=label("blocked"))
        count = d.get("count")
        out["count"] = count if isinstance(count, int) and 1 <= count <= 6 else 3
        need = ("gate", "crowd")
    elif piece == "flow":
        change = str(d.get("change") or "none").lower()
        out.update(**{"from": label("from"), "to": label("to")}, item=kind("item", "money"), amount=label("amount"),
                   change=change if change in ("grows", "stops", "reverses", "none") else "none")
        need = ("from", "to")
    elif piece == "pile":
        start, end = label("start"), label("end")
        out.update(item=kind("item", "money"), label=label("label", 4), start=start, end=end)
        a_, b_ = (parse_metric(start) if start else None), (parse_metric(end) if end else None)
        trend = str(d.get("trend") or "").lower()
        if a_ and b_ and a_["unit"] == b_["unit"] and a_["base"]:
            out["ratio"] = round(max(0.05, min(5.0, b_["base"] / a_["base"])), 3)
            trend = "up" if b_["base"] >= a_["base"] else "down"
        out["trend"] = trend if trend in ("up", "down") else "up"
        need = ("label",)
    elif piece == "race":
        lanes = _labels(d.get("lanes"), 2, 3, 3)
        if not lanes:
            return None
        out.update(lanes=lanes, leader=_index(d.get("leader"), len(lanes), 0))
        lists, need = lanes, ()
    elif piece == "split":
        share = d.get("share")
        out.update(crowd=label("crowd"), win=label("win"), lose=label("lose"),
                   share=share if isinstance(share, (int, float)) and 0.2 <= share <= 0.8 else 0.5)
        need = ("win", "lose")
    elif piece == "machine":
        out.update(input=label("input"), machine=label("machine"), output=label("output"),
                   in_item=kind("in_item", "goods"), out_item=kind("out_item", "money"))
        need = ("machine", "output")
    elif piece == "wall":
        out.update(left=label("left"), right=label("right"), wall=label("wall"), item=kind("item", "goods"))
        need = ("wall",)
    elif piece == "balance":
        heavier = str(d.get("heavier") or "").lower()
        out.update(left=label("left"), right=label("right"), heavier=heavier if heavier in ("left", "right") else "left")
        need = ("left", "right")
    elif piece == "steps":
        steps = _labels(d.get("steps"), 2, 4, 3)
        if not steps:
            return None
        out.update(steps=steps, item=kind("item", "data"), result=label("result"))
        lists, need = steps, ()
    elif piece == "sort":
        bins = _labels(d.get("bins"), 2, 3, 3)
        if not bins:
            return None
        out.update(sorter=label("sorter"), bins=bins, item=kind("item", "documents"))
        lists, need = bins, ()
    elif piece == "cluster":
        groups = _labels(d.get("groups"), 2, 3, 3)
        if not groups:
            return None
        out.update(groups=groups, query=label("query"))
        lists, need = groups, ()
    elif piece == "hill":
        out.update(start=label("start"), goal=label("goal"))
        need = ("goal",)
    elif piece == "fetch":
        out.update(asker=label("asker"), shelf=label("shelf"), answer=label("answer"))
        need = ("shelf", "answer")
    elif piece == "focus":
        words = _labels(d.get("words"), 3, 6, 2, 12)
        if not words:
            return None
        n = len(words)
        focus = _index(d.get("focus"), n, n - 1)
        strongest = _index(d.get("strongest"), n, 0)
        if strongest == focus:
            strongest = 0 if focus else 1
        out.update(words=words, focus=focus, strongest=strongest, label=label("label"), strong=label("strong"))
        lists, need = words, ()
    elif piece == "slice":
        parts = _labels(d.get("parts"), 2, 6, 2, 14)
        if not parts:
            return None
        out.update(whole=label("whole", 4), parts=parts)
        lists, need = parts, ()
    elif piece == "window":
        size = d.get("size")
        out.update(window=label("window"), size=size if isinstance(size, int) and 2 <= size <= 6 else 4,
                   item=kind("item", "documents"), dropped=label("dropped"))
        need = ("window",)
    else:  # target
        out.update(thrower=label("thrower"), target=label("target"), result=label("result"))
        need = ("target",)
    if any(not out.get(k) for k in need):
        return None
    texts = [v for v in out.values() if isinstance(v, str)] + lists
    if not src.grounded(*texts):
        return None
    title = _text(d.get("title"), 9, 70)
    if title and src.grounded(title):
        out["title"], out["mark"] = title, phrase_in(d.get("mark"), title, 2)
    return out


_TITLED = {"dates", "chain", "grid", "cards", "split", "stats", "recap"}


def _with_title(clean: dict, d: dict, src: _Source) -> dict:
    title = _text(d.get("title"), 6, 50)
    if title and src.grounded(title):
        clean["title"] = title
        clean["mark"] = phrase_in(d.get("mark"), title, 2)
    return clean


_SCENES = {
    "headline": _headline, "number": _number, "question": _question, "dates": _dates, "chain": _chain,
    "grid": _grid, "cards": _cards, "stats": _stats, "compare": _compare, "split": _split, "quote": _quote,
    "terminal": _terminal, "checklist": _checklist, "ask": _ask, "source": _source, "recap": _recap, "world": _world,
    "cta": lambda d, src: {},
}


def _lines(beat: dict, src: _Source) -> tuple[list[str], list[str], list[str | None]]:
    raw_lines = beat.get("lines")
    if isinstance(raw_lines, str):
        raw_lines = [raw_lines]
    screens = beat.get("screen") if isinstance(beat.get("screen"), list) else []
    marks = beat.get("mark") if isinstance(beat.get("mark"), list) else []
    lines, shown, cmarks = [], [], []
    for i, raw in enumerate((raw_lines or [])[:3]):
        line = " ".join(str(raw or "").split())
        if not speakable(line) or len(line.split()) > _MAX_LINE_WORDS:
            continue
        spoken = caption_text(line)
        screen = " ".join(str(screens[i] if i < len(screens) else "").split())
        n, m = len(spoken.split()), len(screen.split())
        if not screen or not speakable(screen) or not (0.5 * n <= m <= 1.25 * n + 1) or not src.grounded(screen):
            screen = spoken
        lines.append(line)
        shown.append(screen)
        cmarks.append(phrase_in(marks[i] if i < len(marks) else None, screen, 3) or auto_mark(screen))
    return lines, shown, cmarks


def _cta_beat(brand: str, line: str | None = None) -> dict:
    line = line or f"Follow {brand.title()} for the story behind the news."
    return {"scene": "cta", "kicker": None, "data": {}, "stamp": None,
            "lines": [line], "screens": [line], "cmarks": [brand.title()]}


# The fields every beat has; anything else at the top level of a beat belongs to its scene.
_BEAT_KEYS = {"scene", "lines", "screen", "mark", "kicker", "data", "stamp", "voice", "part"}
LESSON_PARTS = ("hook", "answer", "metaphor", "how", "example", "catch", "takeaway", "ask", "cta")
# What a lesson must still show after validation, or it is incomplete (part: how many beats).
_LESSON_NEEDS = {"answer": 1, "metaphor": 1, "how": 2, "example": 1, "catch": 1, "takeaway": 1}


def _rows_said(rows) -> list[str]:
    """A recap's rows as spoken lines ("Brick cutter: the tokenizer.")."""
    out = []
    for r in (rows if isinstance(rows, list) else [])[:3]:
        if isinstance(r, dict) and r.get("label") and r.get("note"):
            out.append(f"{' '.join(str(r['label']).split())}: {' '.join(str(r['note']).split())}.")
    return out


def _beat_data(beat: dict) -> dict:
    """The scene's data: the beat's "data" object, or -- as models often write it -- the
    scene's fields placed beside lines/screen at the top level of the beat."""
    data = beat.get("data")
    if isinstance(data, dict) and data:
        return data
    return {k: v for k, v in beat.items() if k not in _BEAT_KEYS}


_GRIM = re.compile(
    r"\b(deaths?|dead|died|dies|dying|kill(s|ed|ing)?|fatal(ity|ities)?|victims?|casualt(y|ies)|murder\w*|"
    r"suicides?|wounded|injur(y|ies|ed)|massacre|shooting|overdoses?)\b", re.I)


def _grim(lines: list[str], data: dict) -> bool:
    """The beat is about people harmed or killed. The world's figures cheer, slump, race and
    pile up, so such a beat is never a world beat (the story tells it with words instead)."""
    texts = list(lines) + [str(v) for v in data.values() if isinstance(v, str)]
    texts += [str(x) for v in data.values() if isinstance(v, list) for x in v]
    return any(_GRIM.search(t) for t in texts)


def parse_storyboard(raw, brief, article, *, brand: str, max_beats: int, max_stamps: int,
                     max_asks: int = 2, animated: bool = False, cta: str | None = None) -> Storyboard | None:
    """Validate a model reply into a Storyboard, or None if too little survives.
    `animated`: only world beats plus the few scenes allowed between them, and at
    least MIN_WORLD_BEATS world beats. `cta`: the closing line if the model's is unusable."""
    if not isinstance(raw, dict) or not isinstance(raw.get("beats"), list):
        return None
    src = _Source(brief, article)
    beats: list[dict] = []
    for b in raw["beats"]:
        if not isinstance(b, dict):
            continue
        scene = str(b.get("scene") or "").strip().lower()
        builder = _SCENES.get(scene)
        data = _beat_data(b)
        if scene == "ask" and not b.get("lines") and isinstance(data.get("text"), str):
            b = dict(b, lines=[data["text"]], screen=[data["text"]])  # the question given only as its text
        if scene == "recap" and not b.get("lines"):
            said = _rows_said(data.get("rows"))
            b = dict(b, lines=said, screen=said)  # a table with nothing said: read its rows
        lines, screens, cmarks = _lines(b, src)
        if builder is None or not lines or (animated and scene not in ANIMATED_SCENES):
            continue
        if scene == "world" and _grim(lines, data):
            continue  # harm is never acted out by figures and objects
        if scene == "ask":  # the viewer's question is the beat's one line, on screen as said
            lines, screens, cmarks = lines[:1], screens[:1], cmarks[:1]
            data = {"text": screens[0]}
        clean = builder(data, src)
        if clean is None:
            continue
        if scene in _TITLED:
            clean = _with_title(clean, data, src)
        kicker = _words(b.get("kicker"), 3)
        kicker = kicker if kicker and src.grounded(kicker) else None
        part = str(b.get("part") or "").strip().lower()
        beats.append({
            "scene": scene, "kicker": kicker.upper() if kicker else None, "data": clean,
            "stamp": _stamp(b.get("stamp"), src), "lines": lines, "screens": screens, "cmarks": cmarks,
            "part": part if part in LESSON_PARTS else None,
        })
    beats = [b for i, b in enumerate(beats) if b["scene"] != "cta" or i == len(beats) - 1]
    if not beats or beats[-1]["scene"] != "cta":
        beats.append(_cta_beat(brand, cta))
    beats = _fit(beats, max_beats)
    beats = _place_asks(beats, max_asks)
    if beats[0]["scene"] == "cta" or len(beats) < 5:
        return None
    if animated and sum(b["scene"] == "world" for b in beats) < MIN_WORLD_BEATS:
        return None
    _cap_stamps(beats, max_stamps)
    return Storyboard(subject=clean_subject(raw.get("subject")), beats=beats, metaphor=_metaphor(raw.get("metaphor")))


def _fit(beats: list[dict], max_beats: int) -> list[dict]:
    """Bring an over-long storyboard down to `max_beats` without losing its ending (the
    verdict, the takeaway, the call to follow) or its opening: first the viewer questions
    go, then the receipts, then beats of a part the board has more of than it needs, then
    beats from the middle."""
    beats = list(beats)
    for scene in ("ask", "source"):
        while len(beats) > max_beats and any(b["scene"] == scene for b in beats[1:-1]):
            beats.pop(max(i for i, b in enumerate(beats[:-1]) if i and b["scene"] == scene))
    while len(beats) > max_beats:
        counts: dict = {}
        for b in beats:
            counts[b.get("part")] = counts.get(b.get("part"), 0) + 1
        spare = [i for i, b in enumerate(beats[1:-2], 1)
                 if b.get("part") and counts[b["part"]] > _LESSON_NEEDS.get(b["part"], 1)]
        beats.pop(spare[len(spare) // 2] if spare else len(beats) // 2)
    return beats


def _metaphor(raw) -> dict | None:
    if not isinstance(raw, dict):
        return None
    pairs = [{"everyday": e, "real": r} for e, r in (
        (_words(m.get("everyday"), 4), _words(m.get("real"), 4)) for m in (raw.get("map") or []) if isinstance(m, dict))
        if e and r]
    picture = _text(raw.get("picture"), 25, 200)
    return {"picture": picture, "map": pairs[:6]} if picture or pairs else None


# Words that mean the writer slipped from ELI5 into a lecture (unless the lesson is about them).
_HEAVY = re.compile(
    r"\b(matri(x|ces)|vectors?|dot products?|tensors?|logits?|softmax|quadratic|squared|logarithm\w*|"
    r"o of [a-z]\b|big o|computational\w*|parameters?|architecture|sequential(ly)?|serial|quer(y|ies)|"
    r"keys? and values?|derivatives?|coefficients?|probability distributions?|stochastic|heuristics?)\b", re.I)


def heavy_lines(board: Storyboard | None, topic: str = "") -> list[str]:
    """Spoken lines a twelve-year-old would trip on (heavy jargon or notation not in the topic)."""
    if board is None:
        return []
    topic = topic.lower()
    out = []
    for b in board.beats:
        for line in b["lines"]:
            hits = [m.group(0) for m in _HEAVY.finditer(line) if m.group(0).lower() not in topic]
            if hits:
                out.append(line)
    return out


def _key_from_metaphor(board: Storyboard) -> bool:
    """Give a lesson without a takeaway its metaphor's key -- each everyday part and what it
    really is -- as the recap before the call to follow. False if there is no map to use."""
    pairs = (board.metaphor or {}).get("map") or []
    if len(pairs) < 2:
        return False
    rows = [{"label": p["everyday"].capitalize(), "note": p["real"]} for p in pairs[:4]]
    said = _rows_said(rows)
    recap = {"scene": "recap", "kicker": "THE KEY", "data": {"title": "The key", "mark": "key", "rows": rows},
             "stamp": None, "lines": said, "screens": said, "cmarks": [auto_mark(x) for x in said], "part": "takeaway"}
    at = len(board.beats) - 1 if board.beats and board.beats[-1]["scene"] == "cta" else len(board.beats)
    board.beats.insert(at, recap)
    return True


def lesson_gaps(board: Storyboard | None) -> list[str]:
    """The parts of the lesson arc the validated board does not cover (empty when complete)."""
    if board is None:
        return list(_LESSON_NEEDS)
    have: dict = {}
    for b in board.beats:
        part = b.get("part") or ("takeaway" if b["scene"] == "recap" else None)
        have[part] = have.get(part, 0) + 1
    return [p for p, n in _LESSON_NEEDS.items() if have.get(p, 0) < n]


def _place_asks(beats: list[dict], max_asks: int) -> list[dict]:
    """Keep a viewer question only where it works: not in the first two beats or the last
    two, never right after another one, and at most `max_asks` of them (the first ones)."""
    kept, out = 0, []
    for i, beat in enumerate(beats):
        if beat["scene"] == "ask":
            ok = 2 <= i < len(beats) - 2 and kept < max_asks and (not out or out[-1]["scene"] != "ask")
            if not ok:
                continue
            kept += 1
            beat["voice"] = "viewer"
            beat["stamp"] = None
        out.append(beat)
    return out


def _has_stamps(beat: dict) -> bool:
    items = beat["data"].get("items") if isinstance(beat["data"].get("items"), list) else []
    return bool(beat.get("stamp")) or any(isinstance(i, dict) and i.get("stamp") for i in items)


def _cap_stamps(beats: list[dict], max_stamps: int) -> None:
    """The first and last beats never carry stamps; after that, the model's first picks up to the cap."""
    kept = 0
    for i, beat in enumerate(beats):
        if _has_stamps(beat) and 0 < i < len(beats) - 1 and kept < max_stamps:
            kept += 1
            continue
        beat["stamp"] = None
        for item in beat["data"].get("items") or []:
            if isinstance(item, dict):
                item["stamp"] = None


def write_storyboard(llm, brief, article, *, brand: str, max_beats: int = 10, target_seconds: int = 45,
                     max_stamps: int = 3, when: str = "", hook: str | None = None, audience: str = "",
                     max_asks: int = 2, mode: str = "storyboard", lesson=None) -> Storyboard | None:
    """Ask the model for the storyboard: the explainer of motion-graphic scenes
    (mode "storyboard") or one continuous 3D animation (mode "animated"). A
    `lesson` (narovva.lessons.Lesson) makes it a teaching video grounded in the
    lesson's reference text. None (after logging why) if the call fails or the
    reply does not validate."""
    animated = mode == "animated" or lesson is not None
    cta = f"Save this, and follow {brand} to see how AI works." if lesson is not None else None
    if animated:
        system = _system_animated(brand, max_beats, target_seconds, max_asks, lesson=lesson is not None)
        max_stamps = 0
    else:
        system = _system(brand, max_beats, target_seconds, max_stamps, max_asks)
    user = _user_lesson(brief, article, lesson, audience) if lesson is not None else _user(brief, article, when, hook, audience)
    best, best_gaps = None, None
    for attempt in range(2 if lesson is not None else 1):
        try:
            raw = llm.complete_json(system, user)
        except Exception as exc:
            logger.warning("storyboard LLM call failed (%s)", exc)
            break
        board = parse_storyboard(raw, brief, article, brand=brand, max_beats=max_beats, max_stamps=max_stamps,
                                 max_asks=max_asks, animated=animated, cta=cta)
        if lesson is None:
            best = board
            break
        gaps = lesson_gaps(board)
        if board is not None and "takeaway" in gaps and _key_from_metaphor(board):
            gaps = lesson_gaps(board)
        heavy = heavy_lines(board, f"{lesson.title} {lesson.reference}")
        if len(heavy) >= 2:
            gaps = gaps + ["plain words"]
        if board is not None and (best is None or len(gaps) < len(best_gaps)):
            best, best_gaps = board, gaps
        if not gaps:
            break
        # An incomplete or lecture-like lesson teaches a wrong picture: ask once more, saying why.
        logger.warning("lesson storyboard is missing %s (attempt %d)", ", ".join(gaps), attempt + 1)
        missing = [g for g in gaps if g != "plain words"]
        notes = []
        if missing:
            notes.append(f"after the checks it had no {', '.join(missing)} part. Beats are dropped when a figure is "
                         "not in the reference text, a label is longer than 3 words, a line is longer than 16 words, "
                         "a beat has no spoken lines, or a scene's fields are not inside \"data\"")
        if "plain words" in gaps:
            notes.append("these lines are a lecture, not ELI5 -- say what happens in everyday words instead: "
                         + " | ".join(heavy[:4]))
        user = (user.split("\n\nYOUR LAST STORYBOARD")[0]
                + "\n\nYOUR LAST STORYBOARD NEEDS WORK: " + "; ".join(notes)
                + ". Write the whole storyboard again, covering every part of the arc.")
    if lesson is not None and best is not None and best_gaps:
        if any(p in best_gaps for p in ("metaphor", "how", "takeaway")):  # the core of the explanation
            logger.warning("lesson storyboard still lacks %s; using the slide-based reel", ", ".join(best_gaps))
            return None
        logger.warning("lesson storyboard lacks %s; posting it anyway", ", ".join(best_gaps))
    if best is None:
        logger.warning("storyboard reply did not validate; using the slide-based reel")
    return best


def hook_board(board: Storyboard, written: str | None, said: str | None, headline: str,
               trending: bool = True) -> Storyboard:
    """Open on a pre-written hook: it becomes the first line, as spoken (`said`)
    and on screen (`written`) -- under a TRENDING NOW label for viral posts
    (`trending`); a headline opener shows it with the story's own headline underneath."""
    if not written or not board.beats or not speakable(said or written):
        return board
    first = board.beats[0]
    first["lines"][0], first["screens"][0], first["cmarks"][0] = said or written, written, auto_mark(written)
    if trending:
        first["kicker"] = "TRENDING NOW"
    if first["scene"] == "headline":
        first["data"].update(text=written, mark=None, sub=" ".join(str(headline or "").split()[:12]) or None)
    elif first["scene"] == "world":  # an animated video opens on the world, the hook as its title
        first["data"].update(title=written, mark=None)
    return board


# -- specs for the template ----------------------------------------------------

_KIND = {"quote": "excerpt", "cta": "endcard", "compare": "comparison"}


def estimate_seconds(line: str) -> float:
    """Reading/speaking time for a line with no voice (~156 words a minute)."""
    return max(1.1, len(line.split()) / 2.6)


def beat_specs(board: Storyboard, *, stamp_colors: dict[str, str], heading_marks: bool = True,
               seconds: list[list[float]] | None = None) -> list[dict]:
    """Template specs for the beats. `seconds[i][j]` is how long line j of
    beat i takes to say (from the voice-over); without it, an estimate.
    Each spec's `parts` say when each line starts within its scene."""
    specs = []
    for i, beat in enumerate(board.beats):
        durs = seconds[i] if seconds else [estimate_seconds(line) for line in beat["lines"]]
        spec = {"kind": _KIND.get(beat["scene"], beat["scene"]), "kicker": beat["kicker"], "data": json.loads(json.dumps(beat["data"])),
                "lines": list(beat["lines"]), "screens": list(beat["screens"]), "cmarks": list(beat["cmarks"])}
        if beat.get("voice") == "viewer":
            spec["speaker"] = "viewer"  # read in the second voice; the captions show it as the viewer's
        _colour_stamps(spec, beat.get("stamp"), stamp_colors)
        if not heading_marks:
            spec["data"].pop("mark", None)
        if spec["kind"] == "stats":
            spec["facts"] = spec["data"]["items"]
            spec["viz"] = stats_viz(spec["facts"])
            spec["heading"], spec["hmark"] = spec["data"].get("title"), spec["data"].get("mark")
        elif spec["kind"] == "comparison":
            spec["comparison"] = spec["data"]
            spec["viz"] = comparison_viz(spec["data"])
        specs.append(time_parts(spec, durs, min_hold=BEAT_MIN, tail=BEAT_TAIL))
    return specs


def _colour_stamps(spec: dict, stamp: dict | None, colors: dict[str, str]) -> None:
    paint = lambda s: {"text": s["text"], "color": colors.get(s["tone"], colors["negative"])} if s else None
    if stamp:
        spec["stamp"] = paint(stamp)
    for item in spec["data"].get("items") or []:
        if isinstance(item, dict) and "stamp" in item:
            item["stamp"] = paint(item["stamp"])


def total_seconds(specs: list[dict]) -> float:
    return sum(s["duration"] for s in specs) - SCENE_OVERLAP_SECONDS * (len(specs) - 1)
