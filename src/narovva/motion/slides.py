"""Turns poster_core's generated assets into the plain-dict slide specs the
motion reel composition (templates/reel/index.html) animates. One spec per
rendered image path, in the same order as `[p for a in assets for p in a.paths]`,
so per-slide durations from `narovva.video.slide_duration` line up 1:1."""

from __future__ import annotations

from poster_core import AssetType

# Must match OV in templates/reel/index.html: consecutive scenes overlap by
# the transition buffer that slide_duration() already adds to every slide.
SCENE_OVERLAP_SECONDS = 0.4

_KIND_LABELS = {
    "text": "THE DETAILS",
    "evidence": "THE EVIDENCE",
    "money_flow": "FOLLOW THE MONEY",
    "timeline": "TIMELINE",
    "stats": "BY THE NUMBERS",
    "comparison": "HEAD TO HEAD",
    "quote": "IN THEIR WORDS",
    "conclusion": "WHY IT MATTERS",
}


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


def slide_specs_from_assets(assets: list, durations: list[float]) -> list[dict]:
    """Build one spec per image path. Raises ValueError if `durations`
    doesn't match the number of rendered images."""
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
    if len(specs) != len(durations):
        raise ValueError(f"{len(specs)} slide specs but {len(durations)} durations")
    for spec, dur in zip(specs, durations):
        spec["duration"] = round(float(dur), 3)
    return specs
