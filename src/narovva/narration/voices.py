"""Voice pools and delivery style. A different voice is chosen for each video
(avoiding recently used ones) so the channel doesn't sound the same every post."""

from __future__ import annotations

import hashlib

# gpt-4o-mini-tts built-in voices; Gemini prebuilt voices. ElevenLabs voice ids
# are account-specific, so they must be listed in the channel config.
_DEFAULT_VOICES = {
    "openai": ["coral", "nova", "shimmer", "sage", "ash", "onyx", "verse", "ballad"],
    "gemini": ["Kore", "Puck", "Aoede", "Charon", "Fenrir", "Leda", "Orus", "Zephyr"],
    "elevenlabs": [],
    # Kokoro: US + UK voices; af_heart/af_bella/am_michael were auditioned.
    "kokoro": ["af_heart", "af_bella", "am_michael", "af_nicole", "am_adam", "bf_emma", "bm_george", "af_sky"],
}

# Delivery direction per ContentBrief.tone. OpenAI takes it as natural-language
# `instructions`; ElevenLabs v3 takes the matching audio tag; Gemini takes it as a prefix.
_STYLE_BY_TONE = {
    "urgent": ("Fast, punchy news-anchor delivery with urgency. Crisp and confident.", "[serious]"),
    "celebratory": ("Upbeat, bright and excited, smiling while you speak.", "[excited]"),
    "sombre": ("Calm, measured and serious. Warm but grave. Steady, never slow.", "[serious]"),
    "analytical": ("Clear, confident and curious. Briskly paced explainer, like a sharp tech podcast host.", "[confident]"),
    "inspiring": ("Warm, energetic and optimistic.", "[warmly]"),
    "neutral": ("Energetic, conversational and confident, like a sharp tech news host. Brisk pace, natural emphasis.", "[confident]"),
}


def default_voices(provider: str) -> list[str]:
    return list(_DEFAULT_VOICES.get(provider, []))


def style_for_tone(tone: str) -> tuple[str, str]:
    """(natural-language direction, ElevenLabs audio tag)."""
    return _STYLE_BY_TONE.get(tone, _STYLE_BY_TONE["neutral"])


def choose_voice(pool: list[str], recent: set[str] | frozenset[str] = frozenset(), seed: str = "") -> str:
    """Pick a voice not used recently; deterministic per `seed` (e.g. the article id).
    If every voice was used recently, pick the least-recently-relevant by seed anyway."""
    if not pool:
        raise ValueError("no voices configured")
    fresh = [v for v in pool if v not in recent] or list(pool)
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return fresh[h % len(fresh)]
