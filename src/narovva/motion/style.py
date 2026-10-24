"""The configurable look of a motion reel (ChannelConfig.motion), resolved
into the plain `ui` dict the template reads, plus the script writer's
on-screen direction (stamps, emphasis) attached to the slide specs. The
template stays dumb: every label, colour and choice arrives ready-made."""

from __future__ import annotations

from datetime import datetime, timezone

_LABELS = {"case_file": "CASE FILE: {subject}", "breakdown": "{subject} BREAKDOWN", "brand": "{brand}", "none": ""}
_META = {"case_file": "timecode", "breakdown": "date", "brand": "none", "none": "none"}
_PROGRESS = {"case_file": "top", "breakdown": "hud"}


class _Fill(dict):
    def __missing__(self, key: str) -> str:  # unknown placeholders stay as written
        return "{" + key + "}"


def category_label(category) -> str:
    return str(getattr(category, "value", category) or "news").replace("_", " ").upper()


def story_subject(scripted: str | None, brief) -> str:
    """What the header calls the story: the script writer's pick, else the
    brief's first named entity (up to three words), else its category."""
    if scripted:
        return scripted
    for entity in getattr(brief, "entities", None) or []:
        name = " ".join(str(getattr(entity, "name", "") or "").upper().split()[:3])
        if name and len(name) <= 24:
            return name
    return category_label(getattr(brief, "category", None))


def deck_ui(cfg, *, subject: str, category: str, brand: str, when: datetime | None = None) -> dict:
    """`cfg` is a config.schema.MotionStyleConfig."""
    hud = cfg.hud
    day = (when or datetime.now(timezone.utc)).strftime("%d %b %Y").upper()
    values = _Fill(subject=subject, category=category, brand=brand, date=day)
    template = hud.label if hud.label is not None else _LABELS[hud.style]
    try:
        label = template.format_map(values)
    except (ValueError, IndexError):  # stray braces: show the label as written
        label = template
    progress = cfg.progress if cfg.progress != "auto" else _PROGRESS.get(hud.style, "bottom")
    if progress == "hud" and hud.style not in ("case_file", "breakdown"):
        progress = "bottom"  # there is no header line to run under
    return {
        "hud": {
            "style": hud.style,
            "label": " ".join(label.upper().split()),
            "meta": hud.meta or _META[hud.style],
            "date": day,
            "rec": hud.rec_dot,
        },
        "progress": progress,
        "captions": {
            "style": cfg.captions.style,
            "highlight": cfg.captions.highlight,
            "chunk": cfg.captions.chunk_words,
        },
        "timeline": cfg.timeline,
        "grid": cfg.grid,
        "handle": cfg.show_handle,
        "flood": cfg.story.flood,
    }


def stamp_colors(cfg) -> dict[str, str]:
    """Stamp colour per tone, from a MotionStyleConfig."""
    return {
        "negative": cfg.stamps.negative_color,
        "positive": cfg.stamps.positive_color,
        "neutral": cfg.stamps.neutral_color,
    }


def direct_scenes(specs: list[dict], script, cfg) -> list[dict]:
    """Attach the script to the slide specs (in place): each spec's spoken
    line (`lines`/`screens`/`cmarks`, timed later by narration) plus its
    stamp and headline emphasis, as far as `cfg` (a MotionStyleConfig) allows."""
    colors = stamp_colors(cfg)
    stamps_on = cfg.stamps.enabled and cfg.stamps.max_per_reel > 0
    pick = lambda seq, i: seq[i] if i < len(seq) else None
    for i, spec in enumerate(specs):
        if i < len(script.lines):
            spec["lines"] = [script.lines[i]]
            spec["screens"] = [pick(script.screen, i) or script.lines[i]]
            spec["cmarks"] = [pick(script.line_marks, i)]
        stamp = pick(script.stamps, i)
        if stamps_on and stamp:
            spec["stamp"] = {"text": stamp["text"], "color": colors.get(stamp["tone"], colors["negative"])}
        else:
            spec.pop("stamp", None)
        hmark = pick(script.heading_marks, i)
        if cfg.heading_marks and hmark:
            spec["hmark"] = hmark
        else:
            spec.pop("hmark", None)
    return specs
