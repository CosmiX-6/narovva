"""Map a ContentBrief's motion_theme to a config dict the reel template can
consume as DECK.theme. The template uses these hints to select graphic overlays
and accent tones; absent or unrecognised values fall back to generic treatment."""

from __future__ import annotations


def theme_config(brief) -> dict:
    """Return a theme dict from the brief's motion_theme, or {} if absent."""
    mt = getattr(brief, "motion_theme", None)
    if mt is None:
        return {}
    category = str(getattr(mt, "category", "") or "").lower().replace(" ", "_")
    interface = str(getattr(mt, "interface_type", "") or "").lower().replace(" ", "_")
    entity = getattr(mt, "primary_entity", None) or ""
    accent = getattr(mt, "accent_color_hint", None) or ""
    return {
        "category": category or "generic",
        "interface": interface or "none",
        "entity": entity,
        **({"accentHint": accent} if accent else {}),
    }


# Friendly display label → graphic overlay CSS class the template applies.
# Overlays are layered on top of the ambient background; the template only
# activates them when it recognises the key.
OVERLAY_CLASS = {
    "ai_product": "overlay-ai",
    "code_tool": "overlay-code",
    "design_tool": "overlay-design",
    "policy": "overlay-policy",
    "science": "overlay-science",
    "finance": "overlay-finance",
    "geopolitical": "overlay-geo",
    "social": "overlay-social",
    "generic": "",
}
