"""Content language: what a channel's voice-over, on-screen text and caption are
written in. One profile per language holds everything language-specific (the
writers' rules, the TTS voices and language code, the checks), so the rest of
the code asks the profile instead of testing for a language.

English ("en") is the default and behaves as it always did. Hindi ("hi") means:

- the VOICE-OVER is spoken Hindi, written in Devanagari (English tech terms
  transliterated, so every TTS engine reads them), numbers as digits;
- the ON-SCREEN text (the burned-in transcript, scene titles, labels, stamps,
  the cover) stays English, because the fonts and the audience's reading are
  English and the viewer sees what the voice says;
- the CAPTION is Hinglish: Hindi in Roman script mixed with English terms.

Add a language by adding a profile here (and its voices in narration/voices.py)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_LATIN_TOKEN = re.compile(r"[A-Za-z][A-Za-z.]*[A-Za-z]|[A-Za-z]")
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")
_DEVANAGARI_WORD = re.compile(r"[\u0900-\u097F]{2,}")
_LATIN_WORD = re.compile(r"[A-Za-z]{2,}")

# The sentence in the writers' prompts that says how to write for the ear. The English
# one is the original text (kept word for word); Hindi swaps it.
EAR_EN = (
    "Spell numbers as words in the spoken lines (\"sixty-seven percent\") and abbreviations read letter by "
    "letter with spaces (\"A I\")."
)


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    # The voice-over is in a different language from the on-screen text.
    translated: bool = False
    kokoro_code: str = "en-us"           # espeak language for Kokoro (en: by the voice's accent)
    kokoro_speed: float = 1.12
    max_line_words: int = 16
    caption_note: str = ""               # how the Instagram caption is written
    voice_note: str = ""                 # appended to the TTS delivery direction
    ear_rules: str = EAR_EN
    writer_rules: str = ""               # appended to a writer's prompt (storyboard, script, hook)
    cta_spoken: str = "Follow {brand} for the story behind the news."
    cta_screen: str = "Follow {brand} for the story behind the news."
    glossary: dict[str, str] = field(default_factory=dict)   # Latin term (lower case) -> how it is written for the voice
    cta_lesson_spoken: str = "Save this, and follow {brand} to see how AI works."
    cta_lesson_screen: str = "Save this, and follow {brand} to see how AI works."
    generic_lines: dict[str, str] = field(default_factory=dict)

    # -- checks ---------------------------------------------------------------

    def is_native(self, text: str) -> bool:
        """`text` is written in this language's script (always true for English)."""
        if not self.translated:
            return True
        return bool(_DEVANAGARI_WORD.search(text or ""))

    def is_screen_text(self, text: str) -> bool:
        """`text` is fit to put on screen: no Devanagari (the reel's fonts are Latin)."""
        return not _DEVANAGARI.search(text or "")

    def speakable(self, text: str) -> bool:
        """The TTS engine has real words to say (not '.', '...', an emoji)."""
        if self.translated:
            return bool(_DEVANAGARI_WORD.search(text or "")) or bool(_LATIN_WORD.search(text or ""))
        return bool(re.search(r"[A-Za-z0-9]{2,}", text or ""))

    def cta(self, brand: str, lesson: bool = False, spoken_brand: str | None = None) -> tuple[str, str]:
        """(spoken, on-screen) call to follow (or to save a lesson). `spoken_brand` is how the
        voice says the channel name (Devanagari for Hindi; Latin names are read badly)."""
        said = spoken_brand or brand
        if lesson:
            return self.cta_lesson_spoken.format(brand=said), self.cta_lesson_screen.format(brand=brand)
        return self.cta_spoken.format(brand=said), self.cta_screen.format(brand=brand)

    def say(self, text: str) -> str:
        """The line as the voice should read it: well-known English terms in Latin letters are
        swapped for their Devanagari spelling (a Hindi voice garbles Latin words). Anything not in
        the glossary is left as written."""
        if not self.glossary or not text:
            return text
        return _LATIN_TOKEN.sub(lambda m: self.glossary.get(m.group(0).lower().rstrip("."), m.group(0)), text)


ENGLISH = Language(code="en", name="English")

_HI_WRITER = """\
LANGUAGE -- the voice speaks HINDI, the screen reads ENGLISH. This overrides any earlier instruction about the
language of the spoken lines or how numbers and abbreviations are spelled:
- Every spoken line ("lines") is natural, conversational Hindi in Devanagari script, the way a sharp Indian news
  host would say it to a friend: short sentences, simple words, the everyday Hindi people actually speak (not formal,
  Sanskritised Hindi). Common English words that Indians say in English stay English-sounding but are WRITTEN IN
  DEVANAGARI so every voice reads them: एआई, जीपीयू, ओपनएआई, मॉडल, डेवलपर, कंपनी, ऐप, डेटा, स्टार्टअप. Use the usual
  Devanagari spelling of names and brands (गूगल, माइक्रोसॉफ्ट, एनवीडिया).
- Write numbers as ASCII digits, exactly as the source writes them, with the unit in Devanagari ("67 प्रतिशत",
  "120 मिलियन डॉलर", "3 गुना"): never convert to lakh or crore, never use Devanagari digits. The voice reads the digits
  in Hindi. Never write a number that is not in the source.
- Each line is 5-14 words. Hindi runs longer than English, so keep one idea per line.
- "screen" holds the same line in ENGLISH, for the burned-in transcript: natural, idiomatic English (not a word-for-word
  translation, and no Devanagari), digits for numbers, AI not A I. This is what viewers read while they listen.
- Everything else on screen (scene data, titles, labels, kickers, stamps, quotes, the subject) stays in English exactly
  as the rules above say; a quote is the source's English, word for word.
- A question the viewer asks ("ask" beats): the Hindi question in "lines", its English version in "screen" and in
  the scene's "text".
"""

_HI_SCRIPT = """\
LANGUAGE -- the voice speaks HINDI, the screen reads ENGLISH. This overrides the earlier instructions about the
language of the lines and about spelling numbers and abbreviations: every line in "lines" is natural,
conversational Hindi in Devanagari script (the way a sharp Indian news host would say it to a friend; simple everyday
words), with common English terms written in Devanagari so every voice reads them (एआई, जीपीयू, मॉडल, डेवलपर,
कंपनी). Write numbers as ASCII digits exactly as the slide writes them, with the unit in Devanagari ("67 प्रतिशत",
"120 मिलियन डॉलर"; never lakh or crore). Lines stay 6-14 words. "screen" holds the same
line in natural ENGLISH (no Devanagari, digits for numbers, AI not A I): it is the on-screen transcript.
"""

HINDI = Language(
    code="hi", name="Hindi", translated=True,
    kokoro_code="hi", kokoro_speed=1.0, max_line_words=20,
    ear_rules=(
        "Write numbers as digits in the spoken lines (\"67 प्रतिशत\") and English terms in Devanagari "
        "(\"एआई\", \"जीपीयू\")."
    ),
    voice_note=(
        "Speak natural, conversational Hindi, as an Indian news host would. English terms written in Devanagari "
        "are said the way Indians say them. Brisk, clear, never sing-song."
    ),
    writer_rules=_HI_WRITER,
    caption_note=(
        "Write the caption in HINGLISH: Hindi in Roman (English) letters, mixed naturally with English tech and "
        "business terms, the way young Indian professionals text and post ('Ye naya AI model developers ke liye "
        "kaam asaan kar deta hai. Kya aap try karoge?'). Conversational and warm, never formal or Sanskritised, "
        "never Devanagari script. Hashtags stay English."
    ),
    cta_spoken="{brand} को फॉलो करें, खबर के पीछे की पूरी कहानी जानने के लिए।",
    cta_screen="Follow {brand} for the story behind the news.",
    cta_lesson_spoken="इसे सेव करें, और एआई कैसे काम करता है, ये जानने के लिए {brand} को फॉलो करें।",
    cta_lesson_screen="Save this, and follow {brand} to see how AI works.",
    generic_lines={
        "stats": "ये हैं वो आंकड़े जो मायने रखते हैं।",
        "comparison": "देखिए दोनों की तुलना कैसी है।",
        "timeline": "देखिए ये सब कैसे हुआ।",
        "money_flow": "अब पैसे का रास्ता देखिए।",
        "quote": "और उन्होंने ये कहा।",
        "evidence": "सबूत क्या कहते हैं, देखिए।",
        "why": "असली वजह ये है।",
        "impact": "किसे फायदा होगा और किसे नुकसान।",
        "bigger_picture": "अब बड़ी तस्वीर देखिए।",
        "scream": "ये आंकड़ा सब कुछ कह देता है।",
        "conclusion": "यही बात मायने रखती है।",
        "default": "अगली बात ये है।",
    },
)

HINDI_SCRIPT_RULES = _HI_SCRIPT

# English terms an Indian news host says in English, as they are written for the Hindi voice.
_HI_GLOSSARY = {
    "ai": "एआई", "a.i": "एआई", "gpu": "जीपीयू", "gpus": "जीपीयू", "cpu": "सीपीयू", "llm": "एलएलएम",
    "llms": "एलएलएम", "api": "एपीआई", "apis": "एपीआई", "sdk": "एसडीके", "ui": "यूआई", "ceo": "सीईओ",
    "cto": "सीटीओ", "ipo": "आईपीओ", "aws": "एडब्ल्यूएस", "gpt": "जीपीटी", "chatgpt": "चैटजीपीटी",
    "openai": "ओपनएआई", "anthropic": "एंथ्रोपिक", "claude": "क्लॉड", "gemini": "जेमिनी", "google": "गूगल",
    "microsoft": "माइक्रोसॉफ्ट", "meta": "मेटा", "nvidia": "एनवीडिया", "apple": "एप्पल", "amazon": "अमेज़न",
    "tesla": "टेस्ला", "mistral": "मिस्ट्रल", "deepseek": "डीपसीक", "copilot": "कोपायलट", "cursor": "कर्सर",
    "github": "गिटहब", "iphone": "आईफोन", "android": "एंड्रॉयड", "windows": "विंडोज़", "linux": "लिनक्स",
    "python": "पाइथन", "model": "मॉडल", "models": "मॉडल", "app": "ऐप", "apps": "ऐप", "data": "डेटा",
    "startup": "स्टार्टअप", "startups": "स्टार्टअप", "developer": "डेवलपर", "developers": "डेवलपर्स",
    "open-source": "ओपन-सोर्स", "ok": "ओके", "online": "ऑनलाइन", "update": "अपडेट",
}
HINDI.glossary.update(_HI_GLOSSARY)

LANGUAGES: dict[str, Language] = {"en": ENGLISH, "hi": HINDI}


def get_language(code: str | None) -> Language:
    """The profile for `code` (None = English). Unknown codes are an error, not a silent English."""
    key = (code or "en").lower()
    try:
        return LANGUAGES[key]
    except KeyError:
        raise ValueError(f"unknown language {code!r}; available: {sorted(LANGUAGES)}") from None
