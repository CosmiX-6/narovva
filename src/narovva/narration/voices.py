"""Voice pools and delivery style. A different voice is chosen for each video
(avoiding recently used ones) so the channel doesn't sound the same every post."""

from __future__ import annotations

import hashlib

from ..language import ENGLISH, Language

# gpt-4o-mini-tts built-in voices; Gemini prebuilt voices. ElevenLabs voice ids
# are account-specific, so they must be listed in the channel config.
_DEFAULT_VOICES = {
    "openai": ["coral", "nova", "shimmer", "sage", "ash", "onyx", "verse", "ballad"],
    "gemini": ["Kore", "Puck", "Aoede", "Charon", "Fenrir", "Leda", "Orus", "Zephyr"],
    "elevenlabs": [],
    # Kokoro: US + UK voices; af_heart/af_bella/am_michael were auditioned.
    "kokoro": ["af_heart", "af_bella", "am_michael", "af_nicole", "am_adam", "bf_emma", "bm_george", "af_sky"],
}

# Hindi. Kokoro ships four Hindi voices (two women, two men). OpenAI's and Gemini's voices are
# multilingual, so the English pools speak Hindi too; ElevenLabs voice ids are the account's own.
_HINDI_VOICES = {
    "kokoro": ["hf_alpha", "hf_beta", "hm_omega", "hm_psi"],
}
_VOICES_BY_LANGUAGE = {"hi": _HINDI_VOICES}

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


# The viewer's questions ("Wait, who pays for that?") in a motion reel's storyboard.
VIEWER_STYLE = ("Curious and a little sceptical, like a friend cutting in with a quick question. Natural, brisk.", "[curious]")


def default_voices(provider: str, language: Language = ENGLISH) -> list[str]:
    """The provider's voices for `language` (English voices where it has no separate pool)."""
    pool = _VOICES_BY_LANGUAGE.get(language.code, {}).get(provider)
    return list(pool if pool is not None else _DEFAULT_VOICES.get(provider, []))


def style_for_tone(tone: str, language: Language = ENGLISH) -> tuple[str, str]:
    """(natural-language direction, ElevenLabs audio tag). The direction also says which
    language to speak, for the engines that take it as text (OpenAI, Gemini)."""
    return with_language(_STYLE_BY_TONE.get(tone, _STYLE_BY_TONE["neutral"]), language)


def with_language(style: tuple[str, str], language: Language) -> tuple[str, str]:
    if not language.voice_note:
        return style
    return (f"{style[0]} {language.voice_note}", style[1])


def choose_voice(pool: list[str], recent: set[str] | frozenset[str] = frozenset(), seed: str = "") -> str:
    """Pick a voice not used recently; deterministic per `seed` (e.g. the article id).
    If every voice was used recently, pick the least-recently-relevant by seed anyway."""
    if not pool:
        raise ValueError("no voices configured")
    fresh = [v for v in pool if v not in recent] or list(pool)
    h = int(hashlib.sha256(seed.encode()).hexdigest(), 16)
    return fresh[h % len(fresh)]
