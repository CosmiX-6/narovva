"""Score a reel hook before it goes out.

Five properties, 0-100 each; the verdict is 60% their mean and 40% the weakest one,
because a hook with one dead property leaks at that property and an average hides it.
Method adapted from hookscore.py in https://github.com/Jakeschincariol/youtube-agent-skill
(MIT), with the length band retuned from a 9-24 word spoken YouTube opening to the
4-10 word line a reel puts on screen. It is a heuristic: it separates summaries and
filler from real hooks; it does not predict views.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

_FILLER = {"basically", "actually", "literally", "just", "really", "very", "so", "kind", "sort",
           "guys", "hey", "welcome", "today's", "video", "subscribe", "channel", "news", "update"}
_VAGUE = {"amazing", "incredible", "insane", "crazy", "huge", "massive", "game", "changer", "secret",
          "powerful", "ultimate", "revolutionary", "mind", "blowing", "unbelievable", "major",
          "big", "significant", "important", "new"}
_CONCRETE = re.compile(
    r"(\$\s?\d|\b\d[\d,.]*\s?(%|k|m|bn|b|x|gb|tb|ms)?\b|\b\d+\s?(second|minute|hour|day|week|month|year)s?\b)",
    re.I,
)
_YOU = re.compile(r"\b(you|your|you're|youre|yourself)\b", re.I)
_STAKE = re.compile(
    r"\b(lose|lost|losing|waste|wasting|cost|costs|pay|risk|break|breaks|broken|leak|leaks|exposed|"
    r"stop|never|unless|before|ban|banned|replace|replaces|cheaper|free|faster|slower|doubles?|shrinks?)\b",
    re.I,
)
_CURIOSITY = re.compile(
    r"\b(why|how|what|which|who|until|but|nobody|almost|except|reason|quietly|finally|still|just|now)\b", re.I,
)
_SELF_ANSWER = re.compile(r"\b(because|so that|which means|that's why)\b", re.I)
_WORD = re.compile(r"[a-z0-9'%$.]+")

PROPERTIES = ("specific", "you", "stakes", "curiosity", "length")
FIX = {
    "specific": "swap an adjective for a number, a name or a date from the story",
    "you": "talk to the viewer: 'you' or 'your' early",
    "stakes": "say what it costs them or what changes for them",
    "curiosity": "cut the half that answers itself; leave the question open",
    "length": "4 to 10 words",
}


@dataclass
class HookScore:
    text: str
    parts: dict[str, int]
    verdict: int
    formula: str
    weakest: str = field(init=False)

    def __post_init__(self):
        self.weakest = min(self.parts, key=self.parts.get)

    @property
    def band(self) -> str:
        return "STRONG" if self.verdict >= 70 else "WORKABLE" if self.verdict >= 52 else "WEAK"


@lru_cache(maxsize=1)
def library() -> dict:
    with (Path(__file__).with_name("formulas.yaml")).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    for f in data["formulas"]:
        f["_re"] = [re.compile(p, re.I) for p in f.get("match", [])]
    return data


def formulas_by_id() -> dict[str, dict]:
    return {f["id"]: f for f in library()["formulas"]}


def _words(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def _proper_nouns(text: str) -> int:
    # Capitalised words after the first are names: products, companies, people.
    return sum(1 for w in text.split()[1:] if w[:1].isupper() and not w.isupper())


def specific(text: str) -> int:
    w = _words(text)
    if not w:
        return 0
    s = 45 + 22 * len(_CONCRETE.findall(text)) + min(24, 12 * _proper_nouns(text))
    s -= 16 * sum(x in _VAGUE for x in w) + 6 * sum(x in _FILLER for x in w)
    return max(0, min(100, s))


def you(text: str) -> int:
    first = 20 if _YOU.search(" ".join(text.split()[:6])) else 0
    return max(0, min(100, 40 + 20 * len(_YOU.findall(text)) + first))


def stakes(text: str) -> int:
    s = 40 + 22 * len(_STAKE.findall(text)) + (12 if _CONCRETE.search(text) else 0)
    return max(0, min(100, s))


def curiosity(text: str) -> int:
    s = 40 + 15 * len(_CURIOSITY.findall(text)) + (20 if text.strip().endswith("?") else 0)
    if _SELF_ANSWER.search(text):
        s -= 30  # a hook that resolves itself has no gap left
    return max(0, min(100, s))


def length(text: str) -> int:
    n = len(_words(text))
    if n == 0:
        return 0
    if 4 <= n <= 10:
        return 100
    return max(10, 100 - (4 - n) * 25) if n < 4 else max(10, 100 - (n - 10) * 12)


_SCORERS = {"specific": specific, "you": you, "stakes": stakes, "curiosity": curiosity, "length": length}


def classify(text: str) -> str:
    """The formula the words match best ('unclassified' usually means a summary)."""
    best, hits = "unclassified", 0
    for f in library()["formulas"]:
        n = sum(1 for r in f["_re"] if r.search(text))
        if n > hits:
            best, hits = f["id"], n
    return best


def score(text: str, formula: str | None = None) -> HookScore:
    parts = {name: fn(text) for name, fn in _SCORERS.items()}
    vals = list(parts.values())
    verdict = 0.6 * sum(vals) / len(vals) + 0.4 * min(vals)
    matched = classify(text)
    if matched == "unclassified":
        verdict -= 12  # no hook shape in the words: usually a summary of the story
    return HookScore(text=text, parts=parts, verdict=round(max(0, verdict)), formula=formula or matched)
