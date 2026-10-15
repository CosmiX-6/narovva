"""Turns the numbers an article actually states into chart specs the motion
template can draw (rings, proportional bars, count-ups). Parsing lives here,
in Python, so it is unit-tested offline and the template stays dumb.

House rule: only draw what the story says. A chart never gets a data point
the article didn't give, and two numbers are only drawn to the same scale
when they share a unit."""

from __future__ import annotations

import re

_SIMPLE_WORD_NUMS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}
_WORD_STARTS = re.compile(r"^\s*[-–—]?\s*([A-Za-z]+)\b")

_NUMBER = re.compile(
    r"(?P<prefix>[£$€₹])?\s?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s?(?P<suffix>%|percent\b|x\b|×|k\b|m\b|bn\b|b\b|tn\b|million\b|billion\b|trillion\b))?",
    re.IGNORECASE,
)

# suffix as written -> (suffix as displayed, multiplier used only to compare magnitudes)
_SUFFIXES: dict[str, tuple[str, float]] = {
    "%": ("%", 1.0), "percent": ("%", 1.0),
    "x": ("x", 1.0), "×": ("x", 1.0),
    "k": ("K", 1e3),
    "m": ("M", 1e6), "million": ("M", 1e6),
    "b": ("B", 1e9), "bn": ("B", 1e9), "billion": ("B", 1e9),
    "tn": ("T", 1e12), "trillion": ("T", 1e12),
}
_LABEL_CHARS = 64
_MINUS = "−"
_NAME_BEFORE = re.compile(r"[A-Za-z][-/]?$")


def _not_a_statistic(match: re.Match, fact: str) -> bool:
    """Digits that are part of a name ("GPT-4", "Q3") or a bare year."""
    if match["prefix"]:
        return False
    if _NAME_BEFORE.search(fact[: match.start("num")]):  # "num", not the match: it may open with a space
        return True
    num = match["num"]
    return not match["suffix"] and num.isdigit() and len(num) == 4 and 1900 <= int(num) <= 2100


def _clip(text: str, limit: int = _LABEL_CHARS) -> str:
    text = text.strip(" ,;:-–—")
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:-") + "…"


def parse_metric(fact: str) -> dict | None:
    """The headline number in `fact`, ready to count up to and to label.

    Returns None when the sentence has no real statistic (no digits, or only
    a year). `unit` says what the number can be compared with: "%" for
    percentages, "x" for multipliers, a currency symbol for money, "" for a
    plain count (which is only comparable inside an explicit comparison).
    `base` is the value with its magnitude applied, for scaling bars."""
    fact = (fact or "").strip()
    matches = list(_NUMBER.finditer(fact))
    match = next((m for m in matches if not _not_a_statistic(m, fact)), None)
    if match is None:
        return None
    raw = match["num"]
    value = float(raw.replace(",", ""))
    decimals = len(raw.split(".")[1]) if "." in raw else 0
    prefix = match["prefix"] or ""
    suffix, multiplier = _SUFFIXES.get((match["suffix"] or "").lower(), ("", 1.0))
    unit = "%" if suffix == "%" else "x" if suffix == "x" else prefix
    # A number that opens the sentence reads as "<number> <what it counts>";
    # anywhere else the whole sentence is the caption, as on the PNG slides.
    label = fact[match.end():] if match.start() == 0 else fact
    # Guard against a leading digit that contradicts the copy ("6 — Ten crew
    # members…"): if the label opens with a simple word-number that disagrees
    # with the extracted digit, the fact is malformed — show it as plain text.
    if match.start() == 0 and not match["suffix"]:
        m2 = _WORD_STARTS.match(label)
        if m2:
            word_num = _SIMPLE_WORD_NUMS.get(m2.group(1).lower())
            if word_num is not None and word_num != round(value):
                return None
    return {
        "prefix": prefix,
        "value": value,
        "decimals": decimals,
        "suffix": suffix,
        "grouped": "," in raw or (not decimals and value >= 10000),
        "unit": unit,
        "base": value * multiplier,
        "label": _clip(label),
    }


def format_metric(metric: dict) -> str:
    """The number as it should read at rest, e.g. "$1.2B", "67%", "1,200"."""
    value, decimals = metric["value"], metric["decimals"]
    number = f"{value:,.{decimals}f}" if metric["grouped"] else f"{value:.{decimals}f}"
    return f"{metric['prefix']}{number}{metric['suffix']}"


def stats_viz(facts: list[str]) -> dict:
    """One chart item per fact, in order:

    - ``ring``   a percentage between 0 and 100: an arc that fills to it
    - ``bar``    a number that shares a real unit (same currency, or both
                 multipliers) with another fact: bars drawn to one scale
    - ``number`` any other statistic: a count-up
    - ``text``   no statistic in the sentence: shown as a plain line"""
    items: list[dict] = []
    for fact in facts:
        metric = parse_metric(fact)
        if metric is None:
            items.append({"type": "text", "label": _clip(fact, 90)})
        elif metric["unit"] == "%" and 0 <= metric["value"] <= 100:
            items.append({"type": "ring", "frac": round(metric["value"] / 100, 4), **metric})
        else:
            items.append({"type": "number", **metric})

    # Proportional bars only where the scale is honest: 2+ facts in one unit.
    for unit in {i["unit"] for i in items if i["type"] == "number" and i["unit"]}:
        group = [i for i in items if i["type"] == "number" and i["unit"] == unit]
        top = max(i["base"] for i in group)
        if len(group) >= 2 and top > 0:
            for item in group:
                item["type"] = "bar"
                item["frac"] = round(max(item["base"] / top, 0.04), 4)
    for item in items:
        if item["type"] != "text":
            item["text"] = format_metric(item)
    return {"items": items}


def comparison_viz(comparison: dict | None) -> dict | None:
    """Two values drawn as bars on a shared baseline, plus the change between
    them. Returns None unless both sides are real numbers in the same unit
    (the template then falls back to showing the two values as text)."""
    if not comparison:
        return None
    a, b = parse_metric(str(comparison.get("value_a", ""))), parse_metric(str(comparison.get("value_b", "")))
    if a is None or b is None or a["unit"] != b["unit"]:
        return None
    top = max(a["base"], b["base"])
    if top <= 0:
        return None
    return {
        "a": {**a, "text": format_metric(a), "frac": round(max(a["base"] / top, 0.04), 4)},
        "b": {**b, "text": format_metric(b), "frac": round(max(b["base"] / top, 0.04), 4)},
        "delta": _delta(a["base"], b["base"]),
    }


def _delta(before: float, after: float) -> str | None:
    """Change from the first value to the second, as the badge reads."""
    if before <= 0 or before == after:
        return None
    ratio = after / before
    if ratio >= 3:
        return f"{ratio:.1f}".rstrip("0").rstrip(".") + "x"
    pct = round((ratio - 1) * 100)
    if pct == 0:
        return None
    return f"{'+' if pct > 0 else _MINUS}{abs(pct)}%"
