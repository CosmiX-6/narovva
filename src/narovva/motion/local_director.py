"""The local director: a picture for every story beat without a model call.

Story-first spends two model calls per reel (the writer, then the director). On a day when the good models' quota is
spent, the director's reply from a weaker model mostly fails validation, and every beat would fall back to a headline
-- the text-slide look. This director reads what the writer already wrote (each beat's lines, facts and "show") and
proposes a picture in the director's own reply format, so the same validators judge it: a quote card for a quote the
article holds, a timeline for dated facts, a before/after for a figure that changed, the story's own players as a
composed scene, a counter for a lone figure. A beat it can say nothing true about is left out (it keeps its words).

It is the backup behind the model's direction (beat by beat) and the whole direction when no model answers.
"""

from __future__ import annotations

import re

from .dataviz import parse_metric
from .storyboard import ICON_NAMES, _Source

_VALUE = re.compile(r"(?<![\w.])[$€£₹]?\d[\d,]*(?:\.\d+)?(?:%|x|[KMBT]\b)?")
_YEAR = re.compile(r"^(?:19|20)\d\d$")
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
_DATE = re.compile(r"\b(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(?:\d{1,2},?\s+)?)?"
                   r"(?:19|20)\d\d\b")
_FROM_TO = re.compile(r"\bfrom\s+(\S+)\s+(?:down\s+|up\s+)?to\s+(\S+)", re.I)
# Proper names: 1-3 capitalised words ("OpenAI", "Kevin Warsh", "White House", "GPT-6"); "'s" dropped.
_NAME = re.compile(r"\b([A-Z][\w&.\-]*[\w](?:\s+(?:of\s+)?[A-Z][\w&.\-]*[\w]){0,2})(?:'s|’s)?")
_NOT_NAMES = set("""a an and as at but by for from he her his how i if in it its my no not now of on or our she so that
the their then there these they this those to we what when where which while who why will with you your yes after
before also just only one two three four five six seven eight nine ten first last next new more most many some every
here today tomorrow yesterday wait follow meanwhile however still even because since until""".split())
_MONTH_WORDS = {"january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
                "november", "december", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}

_DOWN = re.compile(r"\b(cut|cuts|drop|drops|dropped|fall|falls|fell|lose|loses|lost|shrink|shrinks|squeez\w*|plung\w*|"
                   r"slash\w*|decline\w*|sink|sank|crash\w*|lower\w*)\b", re.I)
_UP = re.compile(r"\b(rise|rises|rose|grow|grows|grew|gain|gains|gained|jump\w*|surg\w*|soar\w*|climb\w*|boost\w*|"
                 r"win|wins|won|double\w*|triple\w*|raise\w*|expand\w*)\b", re.I)
_BLOCK = re.compile(r"\b(ban|bans|banned|block\w*|bar|bars|barred|halt\w*|stop|stops|stopped|reject\w*|fire|fired|"
                    r"dismiss\w*|sue|sues|sued|suspend\w*|forbid\w*|restrict\w*|sanction\w*|shut\w*)\b", re.I)
_MOVE = re.compile(r"\b(sell|sells|sold|send|sends|sent|pay|pays|paid|ship|ships|shipped|give|gives|gave|fund\w*|"
                   r"invest\w*|acquir\w*|buy|buys|bought|transfer\w*|export\w*|import\w*|deliver\w*|hand\w*)\b", re.I)
_LINK = re.compile(r"\b(with|deal|deals|partner\w*|meet|meets|met|talk\w*|sign\w*|agree\w*|join\w*|ally|allies|"
                   r"back|backs|backed|support\w*|merge\w*|team\w*)\b", re.I)
_VERSUS = re.compile(r"\b(vs|versus|against|rival\w*|compet\w*|fight\w*|war|clash\w*|battle\w*|dispute\w*|sue\w*)\b",
                     re.I)

# A word in an actor's name or its beat -> the icon that depicts it. Checked in order; the first hit wins.
_ICON_WORDS = [
    (("court", "judge", "lawsuit", "verdict", "patent", "law"), "gavel"),
    (("bank", "fed", "reserve", "treasury", "government", "ministry", "congress", "senate", "parliament",
      "white house", "regulator", "commission", "agency", "department"), "landmark"),
    (("police", "fbi", "investigat"), "siren"),
    (("army", "military", "nato", "defence", "defense", "missile", "jets", "troops"), "shield"),
    (("hacker", "breach", "attack", "malware"), "bug"),
    (("chip", "chips", "nvidia", "semiconductor", "gpu", "processor"), "cpu"),
    (("model", "models", "ai", "gpt", "chatbot", "claude", "gemini", "llama"), "bot"),
    (("iphone", "phone", "smartphone", "android"), "smartphone"),
    (("server", "cloud", "data centre", "data center"), "server"),
    (("market", "markets", "stock", "shares", "investors", "wall street"), "chart-line"),
    (("price", "prices", "cost", "dollar", "revenue", "sales", "profit", "settlement", "fine"), "banknote"),
    (("oil", "fuel", "gas"), "fuel"),
    (("hospital", "patients", "health", "doctor", "doctors"), "hospital"),
    (("drug", "vaccine", "pill", "treatment"), "pill"),
    (("study", "researchers", "scientists", "lab", "labs", "test"), "flask-conical"),
    (("school", "students", "university"), "graduation-cap"),
    (("users", "people", "customers", "players", "fans", "workers", "staff", "employees", "voters"), "users"),
    (("factory", "factories", "plant", "manufactur"), "factory"),
    (("city", "country", "nation", "border", "state"), "map-pin"),
    (("election", "vote", "votes"), "vote"),
    (("game", "games", "gaming"), "gamepad-2"),
    (("ship", "shipping", "trade", "export", "exports", "imports"), "ship"),
    (("car", "cars", "tesla", "ev"), "car"),
    (("startup", "startups", "launch"), "rocket"),
    (("developer", "developers", "code", "software", "app"), "code"),
]
_CORP = re.compile(r"\b(inc|corp|ltd|llc|group|company|technologies|labs|ai|bank|motors|systems)\b", re.I)


def _icon_for(label: str) -> str:
    """From the actor's own name only: a company in a court story is still a company, not a gavel."""
    lab = label.lower()
    for words, icon in _ICON_WORDS:
        if icon in ICON_NAMES and any(re.search(r"\b" + re.escape(w), lab) for w in words):
            return icon
    parts = label.split()
    # "Kevin Warsh": two capitalised words that are not a company read as a person
    if len(parts) == 2 and all(p[:1].isupper() and p[1:].islower() for p in parts) and not _CORP.search(lab):
        return "user"
    return "building-2"


def _values(text: str) -> list[str]:
    """Figures in `text` that read as a number on screen (years left out)."""
    out = []
    for m in _VALUE.finditer(text or ""):
        v = m.group(0).rstrip(",")
        if _YEAR.match(v) or not parse_metric(v):
            continue
        out.append(v)
    return out


def _without(text: str, value: str) -> str:
    rest = " ".join(text.replace(value, " ").split()).strip(" :,-–—.")
    return re.sub(r"\b(?:is|are|was|were|of|at|to|by)$", "", rest).strip(" :,-")


def _names(text: str, src: _Source) -> list[str]:
    """Proper names in `text` that the source also uses (so they are this story's players), in order, no repeats."""
    out, seen = [], set()
    for m in _NAME.finditer(text or ""):
        name = m.group(1).strip(" .-")
        words = name.split()
        while words and words[0].lower() in _NOT_NAMES:
            words = words[1:]
        while words and words[-1].lower() in _NOT_NAMES:
            words = words[:-1]
        if not words or len(" ".join(words)) > 26:
            continue
        name = " ".join(words)
        low = name.lower()
        if low in seen or low in _MONTH_WORDS or _DATE.fullmatch(name) or len(name) < 2:
            continue
        if low not in src.flat:
            continue
        # a lone word is a name only if the source never writes it in lower case ("Anthropic" yes, "Responses" no)
        if len(words) == 1 and re.search(r"\b" + re.escape(low) + r"\b", src.text):
            continue
        seen.add(low)
        out.append(name)
    return out


# -- one candidate per kind ------------------------------------------------------------------------------------------

def _quote(b: dict, src: _Source, brief) -> dict | None:
    q = getattr(brief, "notable_quote", None)
    if not q or not getattr(q, "text", None) or not getattr(q, "attribution", None):
        return None
    said = set(re.findall(r"[a-z']{4,}", q.text.lower()))
    beat = set(re.findall(r"[a-z']{4,}", " ".join(b["screens"] + b["facts"]).lower()))
    if not said or len(said & beat) < max(2, len(said) // 2):
        return None
    marks = [m for m in b["cmarks"] if m and m.lower() in q.text.lower()]
    return {"scene": "quote", "data": {"text": q.text, "who": q.attribution, "mark": marks[0] if marks else None}}


def _dates(b: dict) -> dict | None:
    events = []
    for f in b["facts"] or b["screens"]:
        m = _DATE.search(f)
        if not m:
            continue
        when = m.group(0).strip()
        when = re.sub(r"^(\w{3})\w*\.?", lambda x: x.group(1).title(), when) if when[:3].lower() in _MONTHS else when
        what = " ".join(_without(f, m.group(0)).split()[:9])
        if when not in [e["when"] for e in events]:
            events.append({"when": when, "what": what})
    return {"scene": "dates", "data": {"events": events}} if len(events) >= 2 else None


def _compare(b: dict) -> dict | None:
    for text in b["facts"] + b["screens"]:
        m = _FROM_TO.search(text)
        if m:
            a, z = _values(m.group(1)), _values(m.group(2))
            if a and z:
                return {"scene": "compare", "data": {"a": {"label": "Before", "value": a[0]},
                                                     "b": {"label": "After", "value": z[0]}}}
    # two facts, one figure each, in the same unit: "$15 per million tokens before" / "$5 after"
    single = [(f, v[0]) for f in b["facts"] for v in [_values(f)] if len(v) == 1]
    for (fa, va), (fb, vb) in zip(single, single[1:]):
        ma, mb = parse_metric(va), parse_metric(vb)
        la, lb = _without(fa, va), _without(fb, vb)
        if ma["unit"] == mb["unit"] and va != vb and la and lb:
            la, lb = " ".join(la.split()[-4:]).capitalize(), " ".join(lb.split()[-4:]).capitalize()
            return {"scene": "compare", "data": {"a": {"label": la, "value": va}, "b": {"label": lb, "value": vb}}}
    return None


def _number(b: dict) -> dict | None:
    for text in b["facts"] + b["screens"]:
        vals = _values(text)
        if len(vals) != 1:
            continue
        label = _without(text, vals[0])
        if label and len(label.split()) <= 9:
            return {"scene": "number", "data": {"value": vals[0], "label": label}}
    return None


def _compose(b: dict, src: _Source) -> dict | None:
    text = " ".join(b["screens"])
    names = _names(" . ".join(b["screens"] + b["facts"] + [b["show"]]), src)[:5]
    if not names:
        return None
    lines = b["screens"]
    actors, steps = [], []
    for k, name in enumerate(names):
        aid = "abcde"[k]
        value = None
        for line in lines:
            if name.lower() in line.lower():
                vals = _values(line)
                value = vals[0] if len(vals) == 1 else None
                break
        actors.append({"id": aid, "label": name, "icon": _icon_for(name), "value": value})
    if len(actors) == 1 and not actors[0]["value"]:
        return None                                              # one name and nothing happening to it: no picture
    ids = {a["label"].lower(): a["id"] for a in actors}
    shown = set()
    for i, line in enumerate(lines):
        low = line.lower()
        here = [ids[n.lower()] for n in names if n.lower() in low]
        for a in here:
            if a not in shown:
                steps.append({"line": i, "do": "appear", "who": a})
                shown.add(a)
        vals = _values(line)
        if len(here) >= 2 and _MOVE.search(line):
            steps.append({"line": i, "do": "move", "who": here[0], "to": here[1], "label": vals[0] if vals else None})
        elif len(here) >= 2 and _BLOCK.search(line):
            steps.append({"line": i, "do": "block", "who": here[0], "to": here[1]})
        elif len(here) >= 2 and _LINK.search(line):
            steps.append({"line": i, "do": "connect", "who": here[0], "to": here[1]})
        elif here and _BLOCK.search(line):
            steps.append({"line": i, "do": "block", "who": here[-1]})
        elif here and _DOWN.search(line):
            steps.append({"line": i, "do": "shrink", "who": here[-1], "value": vals[0] if len(vals) == 1 else None})
        elif here and _UP.search(line):
            steps.append({"line": i, "do": "grow", "who": here[-1], "value": vals[0] if len(vals) == 1 else None})
        elif here and vals and any(a["value"] for a in actors if a["id"] == here[-1]):
            steps.append({"line": i, "do": "count", "who": here[-1]})
    for a in actors:                                             # named only in the facts: arrive with the first line
        if a["id"] not in shown:
            steps.insert(0, {"line": 0, "do": "appear", "who": a["id"]})
    n = len(actors)
    if n == 2:
        layout = "versus" if _VERSUS.search(text) or any(s["do"] in ("shrink", "grow") for s in steps) else "row"
    elif any(s["do"] in ("move", "connect") for s in steps):
        layout = "flow" if n <= 4 else "hub"
    else:
        layout = "row" if n <= 4 else "stack"
    return {"scene": "compose", "data": {"layout": layout, "actors": actors, "steps": steps[:8]}}


def _alt_layout(d: dict) -> dict:
    """The same composed picture in another arrangement (so two composed beats in a row still differ)."""
    n = len(d["data"]["actors"])
    order = {"row": "stack", "versus": "row", "flow": "row", "hub": "stack", "stack": "row"}
    other = order[d["data"]["layout"]]
    if other == "stack" and n < 2:
        return d
    return {"scene": "compose", "data": {**d["data"], "layout": other}}


def local_direction(beats: list[dict], src: _Source, brief=None) -> dict:
    """A direction in the director's reply format ({"beats": [{"i", "scene", "data"}]}) for every beat it can picture.
    Ask and CTA beats are left to `direct_story`; consecutive beats get different pictures where there is a choice."""
    out, prev, prev_layout = [], None, None
    for i, b in enumerate(beats):
        if b["part"] in ("ask", "cta"):
            prev, prev_layout = b["part"], None
            continue
        comp = _compose(b, src)
        multi = comp if comp and len(comp["data"]["actors"]) >= 2 else None
        single = comp if comp and len(comp["data"]["actors"]) == 1 else None
        candidates = [c for c in (_quote(b, src, brief) if brief else None, _dates(b), _compare(b), multi,
                                  _number(b), single) if c]
        pick = None
        for c in candidates:
            if c["scene"] != prev:
                pick = c
                break
            if c["scene"] == "compose":
                alt = c if c["data"]["layout"] != prev_layout else _alt_layout(c)
                if alt["data"]["layout"] != prev_layout:
                    pick = alt
                    break
        if pick:
            out.append({"i": i, **pick})
            prev, prev_layout = pick["scene"], pick["data"].get("layout")
        else:
            prev, prev_layout = "headline", None
    return {"beats": out}
