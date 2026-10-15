"""Sample deck covering every slide kind, for previewing/rendering the motion
reel without running the news pipeline:  python -m narovva.motion [out.mp4]"""

from __future__ import annotations

from pathlib import Path

SAMPLE_SLIDES: list[dict] = [
    {"kind": "hook", "kicker": "AI", "heading": "What if the smartest A I just got three times cheaper?", "duration": 4.2},
    {"kind": "text", "kicker": "WHAT HAPPENED", "heading": "OpenAI slashed model prices across the board today", "body": "Inference costs drop for every model in the lineup, with the biggest cuts on the largest ones.", "duration": 4.8},
    {"kind": "why", "kicker": "WHY IT'S HAPPENING", "heading": "Compute got cheap fast, and rivals caught up — prices had nowhere left to go", "duration": 4.4},
    {"kind": "impact", "kicker": "WHO WINS / WHO LOSES", "heading": "Every developer and startup building on the A P I wins immediately", "body": "Loses: smaller closed-source labs that competed on price.\nCost: open-source momentum stalls as the gap with closed models narrows.", "duration": 5.0},
    {"kind": "scream", "kicker": "THE NUMBER", "facts": ["67% cheaper per token"], "duration": 3.6},
    {"kind": "stats", "kicker": "BY THE NUMBERS", "facts": ["3.2x faster responses", "$1.2B saved by customers this year", "14 models updated at once"], "duration": 5.0},
    {"kind": "comparison", "kicker": "HEAD TO HEAD", "comparison": {"title": "Cost per million tokens", "label_a": "Before", "value_a": "$15", "label_b": "After", "value_b": "$5"}, "duration": 4.6},
    {"kind": "quote", "kicker": "IN THEIR WORDS", "quote": {"text": "Intelligence should be too cheap to meter.", "attribution": "Company spokesperson"}, "duration": 4.4},
    {"kind": "bigger_picture", "kicker": "THE BIGGER PICTURE", "heading": "When inference is cheap, the edge moves from the model to whoever builds the best product", "duration": 4.6},
    {"kind": "cta", "heading": "Follow for daily AI breakdowns", "duration": 3.2},
]

# One spoken line per sample slide, standing in for the narration script.
SAMPLE_CAPTIONS: list[str] = [
    "What if the smartest models suddenly cost a third of what you pay today?",
    "A new pricing tier just landed, and the biggest models get the deepest cuts.",
    "Compute got cheap, and the competition caught up — prices had to follow.",
    "Every developer building on the A P I just got a raise. Smaller labs didn't.",
    "Sixty-seven percent cheaper per token.",
    "Three point two times faster, one point two billion dollars saved, fourteen models updated.",
    "A million tokens used to cost fifteen dollars. Now it's five.",
    "The company says intelligence should be too cheap to meter.",
    "When inference is free, the advantage moves to whoever builds the best product.",
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
