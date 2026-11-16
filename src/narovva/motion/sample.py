"""Sample deck covering every slide kind, for previewing/rendering the motion
reel without running the news pipeline:  python -m narovva.motion [out.mp4]"""

from __future__ import annotations

from pathlib import Path

SAMPLE_SLIDES: list[dict] = [
    {"kind": "hook", "kicker": "AI", "heading": "What if the smartest AI just got three times cheaper?", "duration": 4.2},
    {"kind": "text", "kicker": "WHAT HAPPENED", "heading": "OpenAI slashed model prices across the board today", "body": "Inference costs drop for every model in the lineup, with the biggest cuts on the largest ones.", "duration": 4.8},
    {"kind": "why", "kicker": "WHY IT'S HAPPENING", "heading": "Compute got cheap fast, and rivals caught up — prices had nowhere left to go", "duration": 4.4},
    {"kind": "timeline", "kicker": "TIMELINE", "heading": "How the price war got here", "timeline": [{"when": "Mar 2024", "what": "A rival lab undercuts flagship prices by half"}, {"when": "Jan 2025", "what": "Open models match the flagship on key benchmarks"}, {"when": "Today", "what": "Flagship prices cut by two-thirds across the lineup"}], "duration": 5.0},
    {"kind": "evidence", "kicker": "THE EVIDENCE", "heading": "What changes for customers", "facts": ["Every model in the lineup gets cheaper", "The 3 largest models get the deepest cuts", "Existing contracts move to the new prices"], "duration": 5.0},
    {"kind": "impact", "kicker": "WHO WINS / WHO LOSES", "heading": "Every developer and startup building on the API wins immediately", "body": "Loses: smaller closed-source labs that competed on price.\nCost: open-source momentum stalls as the gap with closed models narrows.", "duration": 5.0},
    {"kind": "scream", "kicker": "THE NUMBER", "facts": ["67% cheaper per token"], "duration": 3.6},
    {"kind": "stats", "kicker": "BY THE NUMBERS", "facts": ["3.2x faster responses", "$1.2B saved by customers this year", "14 models updated at once"], "duration": 5.0},
    {"kind": "comparison", "kicker": "HEAD TO HEAD", "comparison": {"title": "Cost per million tokens", "label_a": "Before", "value_a": "$15", "label_b": "After", "value_b": "$5"}, "duration": 4.6},
    {"kind": "quote", "kicker": "IN THEIR WORDS", "quote": {"text": "Intelligence should be too cheap to meter.", "attribution": "Company spokesperson"}, "duration": 4.4},
    {"kind": "bigger_picture", "kicker": "THE BIGGER PICTURE", "heading": "When inference is cheap, the edge moves from the model to whoever builds the best product", "duration": 4.6},
    {"kind": "cta", "kicker": "AI", "heading": "Follow for daily AI breakdowns", "body": "When inference is free, the advantage moves to whoever builds the best product.", "duration": 3.6},
]

# One spoken line per sample slide, standing in for the narration script.
SAMPLE_CAPTIONS: list[str] = [
    "What if the smartest models suddenly cost a third of what you pay today?",
    "A new pricing tier just landed, and the biggest models get the deepest cuts.",
    "Compute got cheap, and the competition caught up — prices had to follow.",
    "It started with a rival cutting prices in half, and it never stopped.",
    "Every model gets cheaper, and the three biggest get the deepest cuts.",
    "Every developer building on the A P I just got a raise. Smaller labs didn't.",
    "Sixty-seven percent cheaper per token.",
    "Three point two times faster, one point two billion dollars saved, fourteen models updated.",
    "A million tokens used to cost fifteen dollars. Now it's five.",
    "The company says intelligence should be too cheap to meter.",
    "When inference is free, the advantage moves to whoever builds the best product.",
    "Follow Context Unfiltered for daily breakdowns.",
]


# The same lines as the caption should read them (digits, "API"), and the rest of
# the script writer's on-screen direction, standing in for narovva.narration.script.
SAMPLE_SCREEN: dict[int, str] = {
    4: "Every model gets cheaper, and the 3 biggest get the deepest cuts.",
    5: "Every developer building on the API just got a raise. Smaller labs didn't.",
    6: "67% cheaper per token.",
    7: "3.2x faster, $1.2B saved, 14 models updated.",
    8: "A million tokens used to cost $15. Now it's $5.",
}
SAMPLE_SUBJECT = "AI PRICING"
SAMPLE_LINE_MARKS = ["a third", "deepest cuts", "had to follow", "in half", "deepest cuts", "a raise", "67%",
                     "$1.2B", "$5", "too cheap", "best product", "Context Unfiltered"]
SAMPLE_HEADING_MARKS = [None, "slashed", "rivals", "price war", "customers", "wins", None, None, None,
                        None, "product", None]
SAMPLE_STAMPS = {3: {"text": "PRICE WAR", "tone": "neutral"}, 5: {"text": "SMALL LABS LOSE", "tone": "negative"},
                 8: {"text": "PRICE CUT", "tone": "positive"}}


def write_sample_photo(path: str | Path, size: tuple[int, int] = (1200, 630)) -> str:
    """A synthetic stand-in for an article photo (a typical 1200x630 share
    image), drawn here so the sample needs no licensed picture: a dusk sky,
    a skyline with lit windows, and a soft sun."""
    import random

    from PIL import Image, ImageDraw, ImageFilter

    w, h = size
    rnd = random.Random(26)
    img = Image.new("RGB", size)
    draw = ImageDraw.Draw(img)
    top, mid, low = (18, 24, 66), (176, 74, 112), (250, 164, 92)
    for y in range(h):
        t = y / (h - 1)
        a, b, u = (top, mid, t / 0.6) if t < 0.6 else (mid, low, (t - 0.6) / 0.4)
        draw.line([(0, y), (w, y)], fill=tuple(round(a[i] + (b[i] - a[i]) * u) for i in range(3)))
    sun = Image.new("RGB", size, (0, 0, 0))
    ImageDraw.Draw(sun).ellipse((w * 0.56, h * 0.36, w * 0.8, h * 0.36 + w * 0.24), fill=(255, 214, 150))
    img = Image.composite(Image.new("RGB", size, (255, 226, 170)), img, sun.filter(ImageFilter.GaussianBlur(26)).convert("L"))
    draw = ImageDraw.Draw(img)
    x = -10
    while x < w:
        bw, bh = rnd.randint(46, 120), rnd.randint(round(h * 0.22), round(h * 0.68))
        draw.rectangle((x, h - bh, x + bw, h), fill=(14, 16, 34))
        for wy in range(h - bh + 12, h - 8, 20):
            for wx in range(x + 8, x + bw - 10, 16):
                if rnd.random() < 0.42:
                    draw.rectangle((wx, wy, wx + 7, wy + 10), fill=(255, 205, 120) if rnd.random() < 0.8 else (150, 200, 255))
        x += bw + rnd.randint(2, 14)
    img.save(path, format="JPEG", quality=90)
    return str(path)


def sample_script():
    """The narration script the sample stands in for (voice lines plus direction)."""
    from ..narration.script import Script, caption_text

    return Script(
        lines=list(SAMPLE_CAPTIONS),
        screen=[SAMPLE_SCREEN.get(i, caption_text(line)) for i, line in enumerate(SAMPLE_CAPTIONS)],
        subject=SAMPLE_SUBJECT,
        stamps=[SAMPLE_STAMPS.get(i) for i in range(len(SAMPLE_SLIDES))],
        line_marks=list(SAMPLE_LINE_MARKS),
        heading_marks=list(SAMPLE_HEADING_MARKS),
    )


def sample_deck(captions: bool = True, look=None) -> list[dict]:
    """The sample slides prepared the way the pipeline prepares real ones.
    With `captions`, each slide gets its spoken line and lasts as long as
    that line would take to say (~160 words a minute), as narration does.
    `look` (a MotionStyleConfig) applies the script's stamps and emphasis
    the way the pipeline does; None leaves them off."""
    from .slides import attach_viz, compact_spec, display_chars, motion_duration
    from .style import direct_scenes

    script = sample_script()
    slides = [compact_spec(attach_viz(dict(s))) for s in SAMPLE_SLIDES]
    for slide, line, screen in zip(slides, script.lines, script.screen):
        if captions:
            slide["caption"] = screen  # on screen: "API" and "67%", not the spoken "A P I"
            slide["voice"] = round(len(line.split()) / 2.7, 3)
            slide["duration"] = motion_duration(0, slide["kind"], slide["voice"])
        else:
            slide["duration"] = motion_duration(display_chars(slide), slide["kind"])
    if look is not None:
        direct_scenes(slides, script, look)
    return slides


# -- the explainer storyboard sample --------------------------------------------
# A model reply as narovva.motion.storyboard asks for it, with the brief and the
# article it is checked against, so the sample takes the pipeline's own path.

SAMPLE_ARTICLE_TEXT = (
    "OpenAI cut prices across its model lineup on Thursday, with the flagship now costing $5 per million tokens, "
    "down from $15. The company said 14 models were updated at once and that prices fall 67% per token. Responses "
    "are also 3.2x faster, and the company estimates customers will save $1.2B this year. The move follows a price "
    "war that began in Mar 2024, when a rival lab halved its prices, and accelerated in Jan 2025, when open models "
    "matched the flagship on key benchmarks. Anthropic, Google, Meta and Mistral sell competing models. Developers "
    "and startups building on the API stand to benefit most, while smaller labs that competed on price face "
    "pressure. \"Intelligence should be too cheap to meter,\" a company spokesperson said."
)

SAMPLE_STORYBOARD: dict = {
    "subject": "AI pricing",
    "beats": [
        {"scene": "headline", "kicker": "AI", "lines": ["What if the smartest AI cost a third tomorrow?"],
         "screen": ["What if the smartest AI cost a third tomorrow?"], "mark": ["a third"],
         "data": {"text": "The smartest AI just got 67% cheaper", "mark": "cheaper"}},
        {"scene": "question", "kicker": "THE QUESTION", "lines": ["So why would a leader slash its own prices?"],
         "screen": ["So why would a leader slash its own prices?"], "mark": ["slash"],
         "data": {"text": "WHY?", "icon": "coins"}},
        {"scene": "world", "kicker": "HOW IT WORKS",
         "lines": ["Think of the flagship model as a club with a pricey door.",
                   "At fifteen dollars a million tokens, most developers got turned away."],
         "screen": ["Think of the flagship model as a club with a pricey door.",
                    "At $15 a million tokens, most developers got turned away."],
         "mark": ["pricey door", "turned away"],
         "data": {"piece": "gate", "title": "Who could afford it", "mark": "afford", "gate": "Flagship AI",
                  "crowd": "Developers", "keeper": "The price", "allowed": "In", "blocked": "Too pricey", "count": 3}},
        {"scene": "dates", "kicker": "WHAT HAPPENED",
         "lines": ["First, a rival halved its prices.", "Then open models caught the leader.", "Now the leader has answered."],
         "screen": ["First, a rival halved its prices.", "Then open models caught the leader.", "Now the leader has answered."],
         "mark": ["halved", "open models", "answered"],
         "stamp": {"text": "PRICE WAR", "tone": "neutral"},
         "data": {"title": "How the price war got here", "mark": "price war", "events": [
             {"when": "Mar 2024", "what": "A rival lab halves its prices"},
             {"when": "Jan 2025", "what": "Open models match the flagship"},
             {"when": "Today", "what": "Flagship prices cut by two-thirds"}]}},
        {"scene": "number", "kicker": "THE NUMBER", "lines": ["Sixty-seven percent cheaper, across fourteen models at once."],
         "screen": ["67% cheaper, across 14 models at once."], "mark": ["67%"],
         "data": {"value": "67%", "label": "cheaper per token, across 14 models"}},
        {"scene": "compare", "kicker": "HEAD TO HEAD", "lines": ["A million tokens cost fifteen dollars. Now it costs five."],
         "screen": ["A million tokens cost $15. Now it costs $5."], "mark": ["$5"],
         "stamp": {"text": "PRICE CUT", "tone": "positive"},
         "data": {"title": "Cost per million tokens", "a": {"label": "Before", "value": "$15"}, "b": {"label": "After", "value": "$5"}}},
        {"scene": "ask", "lines": ["Wait, so who actually pays for this?"],
         "screen": ["Wait, so who actually pays for this?"], "mark": ["who actually pays"], "data": {}},
        {"scene": "grid", "kicker": "THE FALLOUT",
         "lines": ["Every rival now faces the same choice.", "Match the price, or lose the customers."],
         "screen": ["Every rival now faces the same choice.", "Match the price, or lose the customers."],
         "mark": ["same choice", "lose the customers"],
         "data": {"title": "Who feels it", "items": [
             {"label": "Anthropic", "sub": "rival lab", "icon": "building-2", "stamp": "PRESSURE"},
             {"label": "Google", "sub": "rival lab", "icon": "globe", "stamp": "PRESSURE"},
             {"label": "Meta", "sub": "open models", "icon": "users"},
             {"label": "Mistral", "sub": "rival lab", "icon": "wind", "stamp": "PRESSURE"}]}},
        {"scene": "split", "kicker": "WHO WINS / WHO LOSES",
         "lines": ["Developers and startups win right away.", "Smaller labs that sold on price lose."],
         "screen": ["Developers and startups win right away.", "Smaller labs that sold on price lose."],
         "mark": ["win", "lose"],
         "data": {"left": {"title": "Wins", "items": ["Developers", "Startups", "Every app user"]},
                  "right": {"title": "Loses", "items": ["Smaller labs", "Price-only rivals"]}}},
        {"scene": "quote", "kicker": "IN THEIR WORDS", "lines": ["The official line: intelligence should be too cheap to meter."],
         "screen": ["The official line: intelligence should be too cheap to meter."], "mark": ["too cheap to meter"],
         "data": {"text": "Intelligence should be too cheap to meter.", "who": "Company spokesperson", "mark": "too cheap to meter"}},
        {"scene": "source", "kicker": "THE RECEIPTS", "lines": ["It's in black and white: five dollars, down from fifteen."],
         "screen": ["It's in black and white: $5, down from $15."], "mark": ["down from $15"],
         "data": {"text": "OpenAI cut prices across its model lineup on Thursday, with the flagship now costing $5 per "
                          "million tokens, down from $15.", "mark": "down from $15"}},
        {"scene": "recap", "kicker": "THE SHORT VERSION",
         "lines": ["Developers pay a third of what they did.", "Rivals match the price, or lose customers."],
         "screen": ["Developers pay a third of what they did.", "Rivals match the price, or lose customers."],
         "mark": ["a third", "lose customers"],
         "data": {"title": "Who gets what", "mark": "what", "rows": [
             {"label": "Developers", "note": "pay $5, not $15"},
             {"label": "Rivals", "note": "match the price or lose"},
             {"label": "Smaller labs", "note": "lose on price"}]}},
        {"scene": "checklist", "kicker": "THE VERDICT",
         "lines": ["When intelligence is cheap, the product is the edge.", "So watch who matches the price first."],
         "screen": ["When intelligence is cheap, the product is the edge.", "So watch who matches the price first."],
         "mark": ["the product", "matches the price"],
         "data": {"title": "When intelligence is cheap, the product wins", "mark": "product wins", "icon": "lightbulb",
                  "items": ["Who matches the price first", "How fast open models follow", "What your bill does"]}},
        {"scene": "cta", "lines": ["Follow Context Unfiltered for the story behind the news."],
         "screen": ["Follow Context Unfiltered for the story behind the news."], "mark": ["Context Unfiltered"], "data": {}},
    ],
}


def sample_brief_and_article():
    """The brief and article SAMPLE_STORYBOARD is checked against."""
    from poster_core.models import Article, ComparisonPair, ContentBrief, Entity, Quote, TimelineEvent

    brief = ContentBrief(
        key_event="OpenAI cuts prices across its model lineup", headline="OpenAI cuts model prices by two-thirds",
        summary="Prices fall 67% per token across 14 models; a million tokens drops from $15 to $5.",
        category="ai", tone="analytical",
        entities=[Entity(name=n, kind="org") for n in ("OpenAI", "Anthropic", "Google", "Meta", "Mistral")],
        key_facts=["Prices fall 67% per token", "Responses are 3.2x faster", "Customers save $1.2B this year",
                   "14 models updated at once"],
        timeline=[TimelineEvent(when="Mar 2024", what="A rival lab halves its prices"),
                  TimelineEvent(when="Jan 2025", what="Open models match the flagship on key benchmarks")],
        comparison=ComparisonPair(title="Cost per million tokens", label_a="Before", value_a="$15", label_b="After", value_b="$5"),
        notable_quote=Quote(text="Intelligence should be too cheap to meter.", attribution="Company spokesperson"),
    )
    article = Article(title="OpenAI cuts model prices by two-thirds", text=SAMPLE_ARTICLE_TEXT, source_name="Sample Wire")
    return brief, article


def sample_story(captions: bool = True, look=None) -> tuple[list[dict], str]:
    """The sample storyboard prepared the way the pipeline prepares a real one
    (validated, then timed with estimated speech). Returns (specs, subject)."""
    from ..config.schema import MotionStyleConfig
    from .storyboard import beat_specs, parse_storyboard
    from .style import stamp_colors

    look = look or MotionStyleConfig()
    brief, article = sample_brief_and_article()
    board = parse_storyboard(SAMPLE_STORYBOARD, brief, article, brand="Context Unfiltered", max_beats=14,
                             max_stamps=look.stamps.max_per_reel if look.stamps.enabled else 0)
    if board is None:
        raise RuntimeError("the sample storyboard no longer validates")
    specs = beat_specs(board, stamp_colors=stamp_colors(look), heading_marks=look.heading_marks)
    if not captions:
        for spec in specs:
            for part in spec["parts"]:
                part.pop("caption", None)
    return specs, board.subject or SAMPLE_SUBJECT
