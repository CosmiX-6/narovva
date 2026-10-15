"""Turns poster_core's generated assets into the plain-dict slide specs the
motion reel composition (templates/reel/index.html) animates. One spec per
rendered image path, in the same order as `[p for a in assets for p in a.paths]`,
so per-slide durations from `narovva.video.slide_duration` line up 1:1."""

from __future__ import annotations

from poster_core import AssetType

from .dataviz import comparison_viz, stats_viz

# Must match OV in templates/reel/index.html: consecutive scenes overlap by
# the transition buffer that slide_duration() already adds to every slide.
SCENE_OVERLAP_SECONDS = 0.3

_KIND_LABELS = {
    "text": "THE DETAILS",
    "evidence": "THE EVIDENCE",
    "money_flow": "FOLLOW THE MONEY",
    "timeline": "TIMELINE",
    "stats": "BY THE NUMBERS",
    "comparison": "HEAD TO HEAD",
    "quote": "IN THEIR WORDS",
    "why": "WHY IT'S HAPPENING",
    "impact": "WHO WINS / WHO LOSES",
    "bigger_picture": "THE BIGGER PICTURE",
    "scream": "THE NUMBER",
    "conclusion": "WHY IT MATTERS",
}


# -- fast pacing -----------------------------------------------------------
# House rules for short-form motion: text lands in ~0.3 s and a slide holds
# just long enough to read once; something changes every couple of seconds.
_MIN_HOLD = 1.7
_MAX_HOLD = 3.6
_CHARS_PER_SECOND = 28.0
VOICE_LEAD = 0.15  # picture leads the voice slightly (also where captions start; passed to the template)
# After the line ends the scene still holds through the 0.3 s transition, so the next
# line (which starts VOICE_LEAD into the next scene) never talks over this one.
_VOICE_TAIL = 0.3
_MAX_FACTS = 3
# A quick update, not a documentary: at most this many scenes (hook + CTA + the
# strongest middle scenes), which with spoken lines of ~3 s is a 20-30 s reel.
MAX_SCENES = 7
_KIND_PRIORITY = {
    "scream": 7, "stats": 6, "comparison": 6, "money_flow": 5, "timeline": 5,
    "why": 5, "impact": 5, "quote": 4, "bigger_picture": 4,
    "conclusion": 3, "evidence": 2, "text": 1,
}


def motion_duration(char_count: int, kind: str = "text", voice_seconds: float | None = None) -> float:
    """Seconds a slide stays on screen. With narration the spoken line sets
    the length (plus a short lead/tail); without it, a brisk reading time."""
    if voice_seconds is not None:
        return round(max(_MIN_HOLD, voice_seconds + VOICE_LEAD + _VOICE_TAIL), 3)
    floor = {"hook": 2.2, "hero": 2.2, "cta": 2.0}.get(kind, _MIN_HOLD)
    return round(min(_MAX_HOLD, max(floor, 1.1 + char_count / _CHARS_PER_SECOND)), 3)


def _trim(text: str | None, limit: int) -> str | None:
    """Cut at a sentence boundary, else a word boundary, within `limit` chars."""
    if not text or len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in (". ", "! ", "? ", "; "):
        i = cut.rfind(sep)
        if i >= limit * 0.5:
            return cut[: i + 1].strip()
    return cut.rsplit(" ", 1)[0].rstrip(",;:-") + "\u2026"


def display_chars(spec: dict) -> int:
    """Visible text length of a spec (what the viewer actually has to read)."""
    n = len(spec.get("kicker") or "") + len(spec.get("heading") or "") + len(spec.get("body") or "")
    n += sum(len(f) for f in spec.get("facts") or [])
    n += sum(len(e["when"]) + len(e["what"]) for e in spec.get("timeline") or [])
    n += sum(len(m["actor"]) + len(m.get("amount") or "") + len(m.get("detail") or "") for m in spec.get("money") or [])
    if spec.get("comparison"):
        c = spec["comparison"]
        n += len(c["label_a"]) + len(c["value_a"]) + len(c["label_b"]) + len(c["value_b"]) + len(c.get("title") or "")
    if spec.get("quote"):
        n += len(spec["quote"]["text"]) + len(spec["quote"].get("attribution") or "")
    return n


def attach_viz(spec: dict) -> dict:
    """Chart specs for the data scenes (see narovva.motion.dataviz). Built
    from the untrimmed copy: trimming a long fact can cut off the very
    number it ends on."""
    kind = spec.get("kind")
    if kind == "stats":
        spec["viz"] = stats_viz((spec.get("facts") or [])[:_MAX_FACTS])
    elif kind == "scream":
        # Single oversized stat: parse the first fact so the template gets
        # a count-up + ring/bar rather than plain text.
        facts = spec.get("facts") or []
        spec["viz"] = stats_viz(facts[:1]) if facts else None
    elif kind == "comparison":
        spec["viz"] = comparison_viz(spec.get("comparison"))
    return spec


_HEADING_LIMIT: dict[str, int] = {
    # Narrative-arc kinds carry a full sentence as heading; let fit() scale the
    # font down rather than truncating mid-thought.
    "why": 110, "bigger_picture": 110, "impact": 95, "scream": 95,
}


def compact_spec(spec: dict) -> dict:
    """Trim on-screen copy for a fast reel: the voice/caption carry the detail."""
    heading_limit = _HEADING_LIMIT.get(spec.get("kind", ""), 78)
    spec["heading"] = _trim(spec.get("heading"), heading_limit)
    spec["body"] = _trim(spec.get("body"), 105)
    spec["facts"] = [_trim(f, 64) for f in (spec.get("facts") or [])[:_MAX_FACTS]]
    spec["timeline"] = [{"when": e["when"], "what": _trim(e["what"], 60)} for e in (spec.get("timeline") or [])[:3]]
    spec["money"] = [dict(m, detail=_trim(m.get("detail"), 40)) for m in (spec.get("money") or [])[:3]]
    if spec.get("quote"):
        spec["quote"] = dict(spec["quote"], text=_trim(spec["quote"]["text"], 110))
    return spec


def select_scenes(specs: list[dict], max_scenes: int = MAX_SCENES) -> list[dict]:
    """Keep the opening scene, the closing scene and the strongest middle
    scenes (data beats prose), in their original order."""
    if len(specs) <= max_scenes or max_scenes < 3:
        return specs
    middle = list(range(1, len(specs) - 1))
    # Highest priority first; earlier scenes win ties (the story builds in order).
    keep = sorted(middle, key=lambda i: (-_KIND_PRIORITY.get(specs[i].get("kind"), 1), i))[: max_scenes - 2]
    chosen = sorted({0, len(specs) - 1, *keep})
    return [specs[i] for i in chosen]


def total_duration(durations: list[float]) -> float:
    """Reel length: scene durations minus the overlap between neighbours."""
    if not durations:
        return 0.0
    return sum(durations) - SCENE_OVERLAP_SECONDS * (len(durations) - 1)


def _category_label(category) -> str:
    return str(getattr(category, "value", category) or "news").replace("_", " ").upper()


def _deck_spec(slide, category_label: str) -> dict:
    kind = slide.kind.value
    spec: dict = {
        "kind": kind,
        "kicker": slide.kicker or (category_label if kind in ("hook", "hero") else _KIND_LABELS.get(kind)),
        "heading": slide.heading,
        "body": slide.body,
        "facts": list(slide.facts),
        "timeline": [{"when": e.when, "what": e.what} for e in slide.timeline],
        "money": [{"actor": s.actor, "amount": s.amount, "detail": s.detail} for s in slide.money_trail],
        "comparison": slide.comparison.model_dump() if slide.comparison else None,
        "quote": slide.quote.model_dump() if slide.quote else None,
    }
    return spec


def slide_specs_from_assets(assets: list, durations: list[float] | None = None) -> list[dict]:
    """Build one compacted spec per image path. `durations=None` uses the
    brisk reading-time formula; pass voice-driven durations to override (one
    per kept scene). Long decks are cut to MAX_SCENES. Raises ValueError if
    the counts don't match."""
    specs: list[dict] = []
    for asset in assets:
        plan = asset.plan
        label = _category_label(plan.category)
        if asset.asset_type is AssetType.CAROUSEL:
            for slide, _ in zip(plan.slides, asset.paths):
                specs.append(_deck_spec(slide, label))
        elif asset.asset_type is AssetType.INFOGRAPHIC:
            for _ in asset.paths:
                specs.append({"kind": "stats", "kicker": "BY THE NUMBERS", "heading": plan.headline, "facts": list(plan.facts)})
        else:  # COVER / THUMBNAIL
            for _ in asset.paths:
                specs.append({"kind": "hook", "kicker": label, "heading": plan.headline, "body": plan.subheadline})
    specs = select_scenes([compact_spec(attach_viz(sp)) for sp in specs])
    if durations is None:
        durations = [motion_duration(display_chars(sp), sp["kind"]) for sp in specs]
    if len(specs) != len(durations):
        raise ValueError(f"{len(specs)} slide specs but {len(durations)} durations")
    for spec, dur in zip(specs, durations):
        spec["duration"] = round(float(dur), 3)
    return specs
