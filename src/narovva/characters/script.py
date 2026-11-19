"""One LLM call writes the character reel: the cast's lines AND how each one is staged (shot, emotion, gesture, reaction,
animated b-roll). Everything the model returns is checked in code before use (same rules as the storyboard writer):
every figure must appear in the brief or the article, no banned words, the host opens on the hook, b-roll pieces exist."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from ..narration.script import grounded, numbers_in

logger = logging.getLogger(__name__)

EMOTIONS = ["neutral", "explain", "curious", "laugh", "wow", "deadpan", "shrug", "proud", "shock", "happy", "confused"]
BROLL_PIECES = ("switch_split", "timeline", "flow", "compare", "machine", "steps", "counter", "filter", "split", "stack")
ICONS = ["laptop", "laptop_pro", "chip", "gpu", "desktop_pc", "cloud", "server", "terminal", "code", "chat", "brain", "tokens", "network",
         "attention", "doc", "search", "agent", "gear", "check", "cross", "question", "money", "python", "cluster", "rocket", "lightbulb",
         "hourglass", "person", "layers"]

BROLL_GUIDE = """b-roll pieces (full-frame animated cutaways that SHOW how it works; the speaker appears in a small bubble):
  switch_split {title, before, items:[a,b], after}                 one control becomes two independent ones
  timeline     {subject, icon, from:{value,label}, to:{value,label}}  a span stretches; value AND label, e.g. {"value": "72", "label": "72 hours"}
  flow         {title, from:{icon,label}, to:{icon,label}, item, turn: none|block|reverse|grow, turn_label}
  compare      {title, left:{label,value(number),display}, right:{...}}  two bars, the bigger wins
  machine      {label, input:{icon,label}, output:{icon,label}}    inputs go in, something else comes out
  steps        {title, steps:[{icon,label}] x2-4}                   how something works, step by step
  counter      {label, from, to, prefix, suffix}                    one big number counts up
  filter       {title, item, gate_label, pass_label, block_label}   some pass, some are rejected
  split        {title, left:{label}, right:{label}}                 who wins / who pays
  stack        {title, layers:[a,b,c]}                              parts that add up to a whole
icons: """ + ", ".join(ICONS)


@dataclass
class CharacterScript:
    lines: list[dict] = field(default_factory=list)   # {speaker, text, emotion, shot, gesture, react, broll?}
    hook_screen: str = ""
    highlight: str = ""
    question: str = ""
    subject: str = ""


def _system(cast: dict, seconds: int, voice_rules: str, broll_share: float) -> str:
    host, side = list(cast)[:2]
    words = int(seconds * 2.3)
    return (
        "You write and direct a short animated news explainer performed by a recurring cast on a studio couch.\n"
        f"CAST: {json.dumps(cast)} (use these exact names as speakers).\n"
        f"ARC: {host} opens on the hook (given) in the first line; {side} reacts with the viewer's question; what happened; "
        "why it is happening (the structural driver); the number that matters; who wins / who pays; the catch or limit; "
        f"{side} asks the audience a yes/no or A/B question to answer in the comments; {host} closes with one bigger-picture line "
        "and the follow ask. Skip beats the source cannot support.\n"
        f"LENGTH: about {words} spoken words ({seconds} s). Lines of 4-16 words. {side} speaks every 2-3 lines. Spoken language: "
        "short sentences, contractions, one everyday analogy introduced once and reused. Spell numbers as words in lines.\n"
        f"{voice_rules}\n"
        "Every figure must appear in the source. Never invent a product detail.\n"
        "STAGING per line: shot = <castid>, <castid>_close, two or wide (vary; never the same twice in a row; open on the host close-up); "
        f"emotion of the speaker from {EMOTIONS}; react = emotion of the listener; gesture none|shrug|point|wave (host only, sparingly).\n"
        f"B-ROLL: on about {int(broll_share * 100)}% of lines (never the first, never two in a row) that explain HOW something works, a "
        "change, a comparison or a key number, add broll {piece, data} instead of only talking. Labels are 1-4 words; numbers only from the source.\n"
        + BROLL_GUIDE + "\n"
        'Return JSON {"lines": [{"speaker", "text", "emotion", "shot", "gesture", "react", "broll": optional}], '
        '"hook_screen": "2-6 words shown big over the opening", "highlight": "one word of hook_screen", '
        '"question": "the audience question", "subject": "1-3 words, the story subject"}'
    )


def _user(brief, article, hook: str | None, said: str | None, audience: str) -> str:
    title = getattr(article, "title", "") or brief.headline
    text = (getattr(article, "text", "") or "")[:6000]
    return (
        (f"Audience: {audience}\n" if audience else "")
        + (f"HOOK (the first line, said by the host; keep its meaning, you may tighten it): {said or hook}\n" if hook else "")
        + f"Article: {title}\n\nBrief:\n"
        + brief.model_dump_json(exclude={"image_generation_prompt", "image_search_query", "visual_concepts"})
        + f"\n\nArticle excerpt:\n{text}"
    )


_MAG = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(k|m|b|bn|thousand|million|billion|trillion)?(?![a-z])", re.I)
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9, "trillion": 1e12}


def _values(text: str) -> set[float]:
    """Every figure in `text` at full scale ("10 million", "10M" and 10000000 are the same value)."""
    out = set()
    for num, unit in _MAG.findall(text or ""):
        try:
            v = float(num.replace(",", ""))
        except ValueError:
            continue
        out.add(round(v * _SCALE.get(unit.lower(), 1) if unit else v, 6))
    return out


def broll_grounded(data: dict, source: str) -> bool:
    """A chart may show a source figure in any magnitude form, but never a figure the source lacks."""
    src = _values(source) | {float(n) for n in numbers_in(source) if n.replace(".", "", 1).isdigit()}
    return _values(json.dumps(data, ensure_ascii=False)) <= src


def _clean_broll(b, source: str):
    if not isinstance(b, dict) or b.get("piece") not in BROLL_PIECES or not isinstance(b.get("data"), dict):
        return None
    if not broll_grounded(b["data"], source):
        logger.info("character script: dropped an ungrounded %s b-roll", b.get("piece"))
        return None
    return {"piece": b["piece"], "data": b["data"]}


def parse(raw: dict, *, cast: dict, source: str, banned: list[str]) -> CharacterScript | None:
    names = list(cast)
    ids = {n: cast[n]["id"] for n in names}
    lines, prev_shot = [], None
    for i, ln in enumerate(raw.get("lines") or []):
        sp, text = ln.get("speaker"), " ".join(str(ln.get("text") or "").split())
        if sp not in ids or not text:
            continue
        if not grounded(text, source):
            logger.info("character script: dropped an ungrounded line (%s)", text[:60])
            continue
        if any(w.lower() in text.lower() for w in banned):
            continue
        cid = ids[sp]
        shot = ln.get("shot") if ln.get("shot") in {*ids.values(), *(f"{v}_close" for v in ids.values()), "two", "wide"} else cid
        if shot == prev_shot:
            shot = f"{cid}_close" if not shot.endswith("_close") else "two"
        broll = _clean_broll(ln.get("broll"), source) if lines else None
        if broll and lines and lines[-1].get("broll"):
            broll = None
        item = {"id": len(lines) + 1, "speaker": cid, "speaker_name": sp, "text": text,
                "emotion": ln.get("emotion") if ln.get("emotion") in EMOTIONS else "explain",
                "react": ln.get("react") if ln.get("react") in EMOTIONS else "neutral",
                "gesture": ln.get("gesture") if (ln.get("gesture") in ("shrug", "point", "wave") and cast[sp].get("kind") == "human") else "none",
                "shot": shot, "move": "pull" if not lines else "push"}
        if broll:
            item["broll"] = broll
            item["shot"] = prev_shot or shot
        lines.append(item)
        prev_shot = item["shot"]
    if len(lines) < 6 or lines[0]["speaker"] != ids[names[0]]:
        logger.warning("character script rejected: %d usable lines, opener by %s", len(lines), lines[0]["speaker"] if lines else None)
        return None
    hs = " ".join(str(raw.get("hook_screen") or "").split())[:48]
    return CharacterScript(lines=lines, hook_screen=hs if grounded(hs, source) else "", highlight=str(raw.get("highlight") or ""),
                           question=str(raw.get("question") or ""), subject=str(raw.get("subject") or ""))


def write(llm, brief, article, *, cast: dict, seconds: int = 40, hook: str | None = None, said: str | None = None,
          audience: str = "", banned: list[str] | None = None, never_claim: list[str] | None = None, broll_share: float = 0.4):
    """-> CharacterScript or None (logged). `cast` = {NAME: {"id", "kind", "role"}} in speaking order (host first)."""
    rules = (f"NEVER use: {', '.join(banned or [])}. " if banned else "") + (f"NEVER claim: {'; '.join(never_claim or [])}." if never_claim else "")
    source = brief.model_dump_json() + " " + (getattr(article, "text", "") or "")
    try:
        raw = llm.complete_json(_system({k: v.get("role", "") for k, v in cast.items()}, seconds, rules, broll_share),
                                _user(brief, article, hook, said, audience))
    except Exception as exc:
        logger.warning("character script LLM call failed (%s)", exc)
        return None
    return parse(raw, cast=cast, source=source, banned=banned or [])


__all__ = ["CharacterScript", "write", "parse", "BROLL_PIECES", "numbers_in"]
