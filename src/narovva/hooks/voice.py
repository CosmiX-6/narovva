"""The channel's voice as one block of rules every writer gets, plus the checks
code enforces (a prompt can be ignored; a filter cannot)."""

from __future__ import annotations

import re


def _norm(text: str) -> str:
    return f" {re.sub(r'[^a-z0-9]+', ' ', (text or '').lower())} "


def find_banned(text: str, banned: list[str]) -> list[str]:
    """Banned words/phrases present in `text` (whole words, case-insensitive)."""
    hay = _norm(text)
    return [b for b in banned if b.strip() and _norm(b) in hay]


def drop_banned_sentences(text: str, banned: list[str]) -> str:
    """Remove sentences that use a banned word; hashtag lines are kept as they are."""
    if not banned or not find_banned(text, banned):
        return text
    out_lines = []
    for line in text.split("\n"):
        if line.lstrip().startswith("#") or not find_banned(line, banned):
            out_lines.append(line)
            continue
        sentences = re.split(r"(?<=[.!?])\s+", line)
        kept = [s for s in sentences if not find_banned(s, banned)]
        out_lines.append(" ".join(kept))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out_lines)).strip()


def voice_brief(audience: str, voice) -> str:
    """Who we talk to plus the house rules, as one block for any prompt."""
    who = (audience or "").strip()
    parts = [who] if who else []
    if voice is not None:
        if voice.banned_words:
            parts.append("Never use these words or phrases: " + ", ".join(voice.banned_words) + ".")
        if voice.never_claim:
            parts.append("Never claim: " + "; ".join(voice.never_claim) + ".")
        if voice.house_phrases:
            parts.append("House phrases you may use sparingly: " + "; ".join(voice.house_phrases) + ".")
        if voice.format:
            parts.append("Format: " + voice.format.strip())
    if len(parts) > 1 and parts[0] == who and who[-1:] not in ".!?":
        parts[0] = who + "."
    return " ".join(parts)
