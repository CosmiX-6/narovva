"""Sample deck covering every slide kind, for previewing/rendering the motion
reel without running the news pipeline:  python -m narovva.motion [out.mp4]"""

from __future__ import annotations

from pathlib import Path

SAMPLE_SLIDES: list[dict] = [
    {"kind": "hook", "kicker": "AI", "heading": "OpenAI just made its models three times cheaper to run", "body": "Here is what changed, and who pays.", "duration": 4.6},
    {"kind": "text", "kicker": "THE DETAILS", "heading": "A new pricing tier lands today", "body": "Inference costs drop for every model in the lineup, with the biggest cuts on the largest ones.", "duration": 5.0},
    {"kind": "stats", "kicker": "BY THE NUMBERS", "heading": "What shifted", "facts": ["67% cheaper per token", "3.2x faster responses", "$1.2B saved by customers", "14 models updated"], "duration": 5.2},
    {"kind": "evidence", "kicker": "THE EVIDENCE", "heading": "What the filings show", "facts": ["Prices were cut on all API tiers", "Rate limits doubled for paid plans", "Batch jobs now cost half"], "duration": 5.0},
    {"kind": "timeline", "kicker": "TIMELINE", "heading": "How we got here", "timeline": [{"when": "Jan 2025", "what": "First price cut announced"}, {"when": "Jun 2025", "what": "Competitors respond"}, {"when": "Oct 2026", "what": "Three-times-cheaper tier ships"}], "duration": 5.0},
    {"kind": "money_flow", "kicker": "FOLLOW THE MONEY", "heading": "Where the savings go", "money": [{"actor": "Customers", "amount": None, "detail": "API spend"}, {"actor": "Cloud provider", "amount": "$0.4B", "detail": "Compute bill"}, {"actor": "Chipmaker", "amount": "$0.2B", "detail": "GPU purchases"}], "duration": 5.0},
    {"kind": "comparison", "kicker": "HEAD TO HEAD", "comparison": {"title": "Cost per million tokens", "label_a": "Before", "value_a": "$15", "label_b": "After", "value_b": "$5"}, "duration": 4.6},
    {"kind": "quote", "kicker": "IN THEIR WORDS", "quote": {"text": "Intelligence should be too cheap to meter.", "attribution": "Company spokesperson"}, "duration": 4.4},
    {"kind": "conclusion", "kicker": "WHY IT MATTERS", "heading": "Cheaper AI means more AI everywhere", "body": "Expect a wave of products that were too expensive to ship last year.", "duration": 4.8},
    {"kind": "cta", "heading": "Follow for daily AI breakdowns", "duration": 3.2},
]

# One spoken line per sample slide, standing in for the narration script so the
# sample exercises the caption track without calling a TTS provider.
SAMPLE_CAPTIONS: list[str] = [
    "What if the smartest models suddenly cost a third of what you pay today?",
    "A new pricing tier just landed, and the biggest models get the deepest cuts.",
    "Sixty-seven percent cheaper per token, and more than three times faster.",
    "The filings show cuts on every tier, with rate limits doubled.",
    "It took less than two years to get from the first cut to this one.",
    "Follow the money: the savings move from customers to clouds to chipmakers.",
    "A million tokens used to cost fifteen dollars. Now it's five.",
    "The company says intelligence should be too cheap to meter.",
    "Cheaper models mean products that couldn't ship last year can ship now.",
    "Follow Context Unfiltered for daily breakdowns.",
]


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


def sample_deck(captions: bool = True) -> list[dict]:
    """The sample slides prepared the way the pipeline prepares real ones.
    With `captions`, each slide gets its spoken line and lasts as long as
    that line would take to say (~160 words a minute), as narration does."""
    from .slides import attach_viz, compact_spec, display_chars, motion_duration

    slides = [compact_spec(attach_viz(dict(s))) for s in SAMPLE_SLIDES]
    for slide, line in zip(slides, SAMPLE_CAPTIONS):
        if captions:
            slide["caption"] = line
            slide["voice"] = round(len(line.split()) / 2.7, 3)
            slide["duration"] = motion_duration(0, slide["kind"], slide["voice"])
        else:
            slide["duration"] = motion_duration(display_chars(slide), slide["kind"])
    return slides
