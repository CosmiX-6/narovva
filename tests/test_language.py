"""Content language: a Hindi voice-over with English on-screen text and a Hinglish caption."""

from __future__ import annotations

import copy
import io
import math
import struct
import sys
import wave

import pytest
from poster_core import AssetPlan, AssetType, ContentBrief, DeckSlide, GeneratedAsset, Platform, SlideKind

import narovva.orchestration.run_channel  # noqa: F401
from narovva.captions import generate_caption
from narovva.config import load_channel
from narovva.config.schema import (
    BrandKitConfig,
    CaptionTone,
    ChannelConfig,
    GenreSetting,
    MotionStyleConfig,
    NarrationConfig,
)
from narovva.hooks import writer
from narovva.language import ENGLISH, HINDI, LANGUAGES, get_language
from narovva.motion.sample import sample_brief_and_article
from narovva.motion.storyboard import (
    _system,
    _system_en,
    beat_specs,
    heavy_lines,
    hook_board,
    parse_storyboard,
    write_storyboard,
)
from narovva.motion.style import stamp_colors
from narovva.narration import default_voices, style_for_tone, synthesize_lines, with_language
from narovva.narration import tts as tts_module
from narovva.narration.script import write_script
from narovva.platforms import PublishPlatform

rc = sys.modules["narovva.orchestration.run_channel"]
BRIEF, ARTICLE = sample_brief_and_article()
SPOKEN_BRAND = "कॉन्टेक्स्ट अनफिल्टर्ड"


def _wav(seconds=1.0, freq=300, rate=24000) -> bytes:
    n = int(seconds * rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n)))
    return buf.getvalue()


# -- the profile ---------------------------------------------------------------

def test_profiles_and_unknown_language():
    assert get_language(None) is ENGLISH and get_language("HI") is HINDI
    assert set(LANGUAGES) == {"en", "hi"}
    with pytest.raises(ValueError, match="unknown language"):
        get_language("fr")


def test_script_checks():
    assert HINDI.is_native("यह एक नई खबर है") and not HINDI.is_native("This is news")
    assert HINDI.is_screen_text("This is news") and not HINDI.is_screen_text("यह खबर")
    assert HINDI.speakable("एआई।") and not HINDI.speakable("...") and not HINDI.speakable("")
    assert ENGLISH.is_native("anything") and ENGLISH.speakable("AI") and not ENGLISH.speakable("A.")


def test_glossary_swaps_known_terms_only():
    out = HINDI.say("यह नया AI model developers के लिए GPU और OpenAI का है, Zorblax भी।")
    assert out == "यह नया एआई मॉडल डेवलपर्स के लिए जीपीयू और ओपनएआई का है, Zorblax भी।"
    assert ENGLISH.say("AI model") == "AI model"


def test_hindi_call_to_follow_uses_the_spoken_brand_and_an_english_caption():
    spoken, screen = HINDI.cta("Context Unfiltered", spoken_brand=SPOKEN_BRAND)
    assert spoken.startswith(SPOKEN_BRAND) and screen == "Follow Context Unfiltered for the story behind the news."
    assert HINDI.cta("X", lesson=True)[1] == "Save this, and follow X to see how AI works."
    assert ENGLISH.cta("X") == ("Follow X for the story behind the news.",) * 2


# -- config --------------------------------------------------------------------

def _channel(**kw):
    base = dict(
        id="c", ig_business_account_id="1", genres=[GenreSetting(genre="tech")],
        brand=BrandKitConfig(name="Context Unfiltered", social_handle="cu", logo_path="assets/logo/CU.png"),
        publish_format="motion_reel", narration=NarrationConfig(provider="kokoro"),
        motion=MotionStyleConfig.model_validate({"story": {"mode": "slides"}}),
    )
    base.update(kw)
    return ChannelConfig(**base)


def test_language_precedence_and_validation():
    ch = _channel(language="en", genres=[GenreSetting(genre="tech"), GenreSetting(genre="ai", language="HI")])
    tech, ai = ch.genres
    assert ch.language_for(tech) is ENGLISH and ch.language_for(ai) is HINDI
    assert ch.language_for(ai, override="en") is ENGLISH and ch.language_for(tech, override="hi") is HINDI
    assert _channel(language="HI").language == "hi"
    with pytest.raises(ValueError):
        _channel(language="fr")
    with pytest.raises(ValueError):
        GenreSetting(genre="x", language="de")


def test_per_language_narration_settings_reject_a_misspelt_language():
    assert NarrationConfig(spoken_names={"hi": SPOKEN_BRAND}, voices_by_language={"hi": ["hf_alpha"]})
    for field in ("spoken_names", "voices_by_language"):
        with pytest.raises(ValueError, match="unknown language"):
            NarrationConfig(**{field: {"hindi": SPOKEN_BRAND if field == "spoken_names" else ["x"]}})


def test_live_channel_stays_english_until_switched_and_has_hindi_settings():
    ch = load_channel("config/channels/example-tech-ig.yaml")
    assert ch.language == "en" and ch.language_for() is ENGLISH
    assert ch.narration.spoken_names["hi"] == SPOKEN_BRAND and ch.language_for(override="hi") is HINDI


# -- voices and TTS --------------------------------------------------------------

def test_hindi_voice_pools_and_direction():
    assert default_voices("kokoro", HINDI) == ["hf_alpha", "hf_beta", "hm_omega", "hm_psi"]
    assert default_voices("openai", HINDI) == default_voices("openai")        # multilingual voices
    assert default_voices("kokoro") == default_voices("kokoro", ENGLISH) and "af_heart" in default_voices("kokoro")
    assert "Hindi" in style_for_tone("urgent", HINDI)[0] and "Hindi" not in style_for_tone("urgent")[0]
    assert style_for_tone("urgent") == style_for_tone("urgent", ENGLISH)
    assert with_language(("a", "[x]"), ENGLISH) == ("a", "[x]")


def test_kokoro_gets_the_hindi_language_code_and_pace(monkeypatch):
    calls = []

    class _Kokoro:
        def create(self, text, voice, speed, lang):
            calls.append((text, voice, speed, lang))
            return [0.0] * 24000, 24000

    monkeypatch.setitem(sys.modules, "soundfile", type("SF", (), {"write": staticmethod(
        lambda buf, samples, rate, format: buf.write(_wav(1.0)))}))
    k = tts_module.KokoroTTS.__new__(tts_module.KokoroTTS)
    k._kokoro, k._speed = _Kokoro(), 1.12
    k.synthesize("नमस्ते", voice="hf_alpha", style=("", ""), lang=HINDI)
    k.synthesize("Hello", voice="bf_emma", style=("", ""))
    k.synthesize("Hello", voice="af_heart", style=("", ""), lang=ENGLISH)
    assert calls == [("नमस्ते", "hf_alpha", 1.0, "hi"), ("Hello", "bf_emma", 1.12, "en-gb"),
                     ("Hello", "af_heart", 1.12, "en-us")]


def test_the_language_reaches_an_engine_only_when_it_is_not_english():
    seen = []

    class _Strict:   # the English interface, which has no `lang`
        def synthesize(self, text, *, voice, style):
            seen.append(("strict", text))
            return _wav(1.0)

    class _Hindi:
        def synthesize(self, text, *, voice, style, lang):
            seen.append(("hindi", lang.code))
            return _wav(1.0)

    synthesize_lines(_Strict(), ["Hello there."], voice="v", style=("", ""))
    synthesize_lines(_Strict(), ["Hello there."], voice="v", style=("", ""), lang=ENGLISH)
    synthesize_lines(_Hindi(), ["नमस्ते दोस्तों"], voice="v", style=("", ""), lang=HINDI)
    assert seen == [("strict", "Hello there."), ("strict", "Hello there."), ("hindi", "hi")]


def _kokoro_models_present() -> bool:
    d = tts_module.kokoro_dir()
    return (d / "kokoro-v1.0.onnx").exists() and (d / "voices-v1.0.bin").exists()


@pytest.mark.skipif(not _kokoro_models_present(), reason="Kokoro model files not cached (set NAROVVA_KOKORO_DIR)")
def test_real_kokoro_speaks_hindi():
    provider = tts_module.build_provider("kokoro", "")
    clips = synthesize_lines(provider, ["मिस्ट्रल ने एक नया एआई मॉडल लॉन्च किया है।"], voice="hf_alpha",
                             style=("", ""), lang=HINDI)
    assert 1.5 < clips[0].seconds < 8.0


# -- the storyboard ----------------------------------------------------------------

def _hindi_beat(scene, data, hindi, english, **kw):
    return {"scene": scene, "lines": [hindi], "screen": [english], "data": data, **kw}


def _hindi_raw(*middle, hook=None):
    filler = [_hindi_beat("headline", {"text": f"Point {w} of the story"}, "एक और अहम बात ये है।",
                          f"Point {w} of the story.") for w in ("one", "two", "three")]
    first = hook or _hindi_beat("question", {"text": "WHY?"}, "आखिर ऐसा क्यों हुआ?", "Why did this happen?")
    return {"subject": "AI pricing",
            "beats": [first, *middle, *filler,
                      _hindi_beat("cta", {}, "Follow Context Unfiltered", "Follow us.")]}


def _hindi_board(raw=None, **kw):
    return parse_storyboard(copy.deepcopy(raw or _hindi_raw()), BRIEF, ARTICLE, brand="Context Unfiltered",
                            max_beats=14, max_stamps=3, language=HINDI, spoken_brand=SPOKEN_BRAND, **kw)


def test_english_prompts_are_unchanged_and_hindi_adds_its_rules():
    assert _system("B", 10, 45, 3, 2, ENGLISH) == _system_en("B", 10, 45, 3, 2)
    hindi = _system("B", 10, 45, 3, 2, HINDI)
    assert "Devanagari" in hindi and "ENGLISH" in hindi
    assert HINDI.ear_rules in hindi and "Spell numbers as words" not in hindi
    assert hindi.index("LANGUAGE --") < hindi.index("Respond as JSON")      # the rules come before the format


def test_hindi_beats_keep_hindi_lines_and_english_captions():
    board = _hindi_board()
    assert board.translated and len(board.beats) == 5
    first = board.beats[0]
    assert first["lines"] == ["आखिर ऐसा क्यों हुआ?"] and first["screens"] == ["Why did this happen?"]
    specs = beat_specs(board, stamp_colors=stamp_colors(MotionStyleConfig()))
    assert [p["caption"] for p in specs[0]["parts"]] == ["Why did this happen?"]     # English on screen
    assert all(not HINDI.is_native(c) for s in specs for c in s["screens"])


def test_hindi_lines_without_a_usable_english_caption_are_dropped():
    bad = [
        _hindi_beat("headline", {"text": "Prices fell"}, "कीमतें गिर गईं।", ""),                       # no caption
        _hindi_beat("headline", {"text": "Prices fell"}, "कीमतें गिर गईं।", "कीमतें गिर गईं।"),         # Devanagari on screen
        _hindi_beat("headline", {"text": "Prices fell"}, "Prices fell sharply.", "Prices fell sharply."),  # not Hindi
        _hindi_beat("headline", {"text": "Prices fell"}, "कीमतें 91 प्रतिशत गिरीं।", "Prices fell 91%."),   # figure not in source
    ]
    board = _hindi_board(_hindi_raw(*bad))
    assert len(board.beats) == 5                                                    # none of the four survived
    assert all(HINDI.is_native(b["lines"][0]) for b in board.beats)


def test_known_english_terms_are_written_for_the_voice_and_figures_are_grounded():
    ok = _hindi_beat("headline", {"text": "Prices fell"}, "AI model की कीमत 67 प्रतिशत गिरी।", "AI prices fell 67%.")
    board = _hindi_board(_hindi_raw(ok))
    line = next(b["lines"][0] for b in board.beats if "कीमत" in b["lines"][0] and "67" in b["lines"][0])
    assert line == "एआई मॉडल की कीमत 67 प्रतिशत गिरी।"


def test_the_hindi_call_to_follow_is_fixed_text_with_the_spoken_brand():
    board = _hindi_board()
    cta = board.beats[-1]
    assert cta["scene"] == "cta" and cta["lines"][0].startswith(SPOKEN_BRAND)
    assert cta["screens"] == ["Follow Context Unfiltered for the story behind the news."]
    raw = _hindi_raw()
    raw["beats"].pop()                                                              # the model forgot the cta beat
    assert _hindi_board(raw).beats[-1]["lines"][0].startswith(SPOKEN_BRAND)


def test_hindi_hook_replaces_the_first_line_and_a_missing_one_keeps_the_writers():
    hook, said = "Can your voice agent speak?", "क्या आपका वॉइस एजेंट बोल सकता है?"
    board = hook_board(_hindi_board(), hook, said, "Headline")
    assert board.beats[0]["lines"][0] == said and board.beats[0]["screens"][0] == hook
    board = hook_board(_hindi_board(), hook, None, "Headline")                      # no Hindi version yet
    assert board.beats[0]["lines"][0] == "आखिर ऐसा क्यों हुआ?" and board.beats[0]["screens"][0] == hook


def test_checks_for_lecturing_read_the_english_text():
    jargon = _hindi_beat("headline", {"text": "Matrices"}, "ये एक कठिन बात है।", "It multiplies matrices and vectors.")
    board = _hindi_board(_hindi_raw(jargon))
    assert heavy_lines(board) and "matrices" in heavy_lines(board)[0]


def test_write_storyboard_tells_the_writer_the_hook_in_both_languages():
    seen = {}

    class _LLM:
        def complete_json(self, system, user):
            seen.update(system=system, user=user)
            return _hindi_raw()

    board = write_storyboard(_LLM(), BRIEF, ARTICLE, brand="Context Unfiltered", hook="English hook here",
                             said="हिंदी हुक यहाँ", language=HINDI, spoken_brand=SPOKEN_BRAND)
    assert board is not None and board.translated
    assert "हिंदी हुक यहाँ" in seen["user"] and "English hook here" in seen["user"]
    assert "Devanagari" in seen["system"]


# -- the slide-based script ----------------------------------------------------------

class _ScriptLLM:
    def __init__(self, out):
        self.out, self.seen = out, None

    def complete_json(self, system, user):
        self.seen = (system, user)
        return self.out


SPECS = [
    {"kind": "hook", "heading": "Chips just got cheaper", "body": "Here is why"},
    {"kind": "stats", "heading": "The numbers", "facts": ["67% cheaper"]},
    {"kind": "cta", "heading": "Follow"},
]
SB = type("B", (), {"tone": "neutral", "headline": "Chips", "summary": "Chips got cheaper"})()


def test_hindi_script_has_hindi_lines_and_english_screens():
    llm = _ScriptLLM({
        "lines": ["चिप्स अचानक सस्ते हो गए!", "कीमत 67 प्रतिशत गिरी।", "Follow us."],
        "screen": ["Chips just got cheaper!", "Prices fell 67%.", "Follow us."],
    })
    out = write_script(llm, SB, SPECS, brand="Context Unfiltered", language=HINDI, spoken_brand=SPOKEN_BRAND)
    assert out.lines[:2] == ["चिप्स अचानक सस्ते हो गए!", "कीमत 67 प्रतिशत गिरी।"]
    assert out.screen[:2] == ["Chips just got cheaper!", "Prices fell 67%."]
    assert out.lines[2].startswith(SPOKEN_BRAND) and "Follow" in out.screen[2]         # fixed call to follow
    assert "Devanagari" in llm.seen[0]
    assert "Devanagari" not in write_script(_ScriptLLM({"lines": ["a b c"]}), SB, SPECS, brand="CU").lines[0]


def test_hindi_script_replaces_english_lines_with_hindi_fallbacks_and_keeps_english_screens():
    llm = _ScriptLLM({"lines": ["Chips got cheaper.", "Prices fell by 91 percent", "x"], "screen": ["यह हिंदी है", "", ""]})
    out = write_script(llm, SB, SPECS, brand="CU", language=HINDI)
    assert all(HINDI.is_native(line) for line in out.lines)                            # never English to a Hindi voice
    assert out.lines[1] == HINDI.generic_lines["stats"]
    assert all(HINDI.is_screen_text(s) and s for s in out.screen)                       # never Devanagari on screen
    assert out.screen[0] == "Chips just got cheaper."                                   # English from the slide itself


def test_a_hindi_hook_without_its_english_caption_is_not_used_as_a_caption():
    out = write_script(_ScriptLLM({"lines": ["एक बात।", "दो बात।", "तीन बात।"], "screen": ["One.", "Two.", "Three."]}),
                       SB, SPECS, brand="CU", language=HINDI, hook="क्या आप तैयार हैं?", hook_screen="Are you ready?")
    assert out.lines[0] == "क्या आप तैयार हैं?" and out.screen[0] == "Are you ready?"
    out = write_script(_ScriptLLM({"lines": ["एक बात।", "दो बात।", "तीन बात।"], "screen": ["One.", "Two.", "Three."]}),
                       SB, SPECS, brand="CU", language=HINDI, hook=None, hook_screen="Are you ready?")
    assert out.lines[0] == "एक बात।" and out.screen[0] == "Are you ready?"


# -- the hook package ------------------------------------------------------------------

class _Brief:
    headline = "Mistral AI unveils Voxtral 3 for real-time voice agents"
    summary = "Mistral released Voxtral 3, a voice agent stack with 200 ms latency, open weights."
    why_it_matters = "Developers can build real-time voice agents without a closed API."
    key_facts = ["Latency is 200 ms", "Weights are open"]
    tone = "neutral"
    hook = None
    category = "ai"


GOOD_HI = {
    "hook": "Can your voice agent finally speak in real time?", "formula": "the-question",
    "cover": "Mistral's open stack", "hook_spoken": "क्या आपका वॉइस एजेंट अब रियल टाइम में बोल सकता है?",
    "opener": "Open weights aur 200 ms latency: ab self-host karna aasan hai.",
}


def test_hindi_package_needs_a_hindi_spoken_hook_and_a_hinglish_opener():
    pkg, why = writer.pick({"options": [GOOD_HI]}, _Brief, language=HINDI)
    assert pkg.hook == GOOD_HI["hook"] and pkg.spoken == GOOD_HI["hook_spoken"]
    assert pkg.opener == GOOD_HI["opener"] and pkg.cover == "MISTRAL'S OPEN STACK"
    # No Hindi version: the option is rejected, with the reason.
    pkg, why = writer.pick({"options": [{**GOOD_HI, "hook_spoken": "Can your agent speak?"}]}, _Brief, language=HINDI)
    assert pkg is None and "hook_spoken" in why[0]
    # A number the story lacks, or a Devanagari opener (the caption is Roman), do not pass.
    assert writer.pick({"options": [{**GOOD_HI, "hook_spoken": "अब सिर्फ 50 एमएस में जवाब मिलता है।"}]}, _Brief,
                       language=HINDI)[0] is None
    pkg, _ = writer.pick({"options": [{**GOOD_HI, "opener": "ओपन वेट्स और 200 एमएस लेटेंसी, अब खुद चलाएं।"}]}, _Brief,
                         language=HINDI)
    assert pkg.opener is None
    # English: nothing about Hindi is required.
    pkg, _ = writer.pick({"options": [{k: v for k, v in GOOD_HI.items() if k != "hook_spoken"}]}, _Brief)
    assert pkg.spoken is None and pkg.hook == GOOD_HI["hook"]


def test_hindi_package_prompt_and_english_prompt():
    seen = []

    class _LLM:
        def complete_json(self, system, user):
            seen.append(system)
            return {"options": [GOOD_HI]}

    pkg = writer.write_package(_LLM(), _Brief, language=HINDI)
    assert pkg.spoken and "hook_spoken" in seen[0] and "HINGLISH" in seen[0]
    writer.write_package(_LLM(), _Brief)
    assert "hook_spoken" not in seen[1] and "HINGLISH" not in seen[1]


# -- the caption -------------------------------------------------------------------------

def test_the_caption_is_hinglish_for_hindi_posts_only():
    seen = []

    class _LLM:
        def complete_json(self, system, user):
            seen.append(system)
            return {"caption": "Ye naya model developers ke liye kaam asaan karta hai.", "hashtags": ["#AI"]}

    brief = ContentBrief(key_event="k", summary="Chips got cheaper", headline="Chips", tone="neutral", category="ai")
    generate_caption(brief, publish_platform=PublishPlatform.INSTAGRAM, tone=CaptionTone(), llm=_LLM(), language=HINDI)
    generate_caption(brief, publish_platform=PublishPlatform.INSTAGRAM, tone=CaptionTone(), llm=_LLM())
    assert "HINGLISH" in seen[0] and "never Devanagari" in seen[0] and "HINGLISH" not in seen[1]


# -- narration end to end --------------------------------------------------------------------

class _Track:
    id, audio_bytes, attribution = "t", _wav(3.0, 220, rate=44100), "c"


def _brief():
    return ContentBrief(key_event="k", summary="Chips got cheaper", headline="Chips", tone="neutral", category="ai")


def _asset(n=3):
    slides = [DeckSlide(kind=SlideKind.HOOK, heading="H")] + [DeckSlide(kind=SlideKind.TEXT, heading=f"T{i}")
                                                              for i in range(n - 1)]
    plan = AssetPlan(asset_type=AssetType.CAROUSEL, platform=Platform.INSTAGRAM_STORY, headline="H", slides=slides)
    return GeneratedAsset(asset_type=AssetType.CAROUSEL, platform=Platform.INSTAGRAM_STORY,
                          paths=[f"/tmp/{i}.png" for i in range(n)], plan=plan)


class _Provider:
    def __init__(self):
        self.calls = []

    def synthesize(self, text, *, voice, style, lang=ENGLISH):
        self.calls.append((text, voice, style[0], lang.code))
        return _wav(1.5, 350)


class _SlidesLLM:
    def __init__(self, lines, screen):
        self.out = {"lines": lines, "screen": screen}

    def complete_json(self, system, user):
        return self.out


def _narrated(monkeypatch, language, narration=None, **kw):
    provider, captured = _Provider(), {}
    monkeypatch.setattr(rc, "build_provider", lambda *a, **k: provider)
    monkeypatch.setattr(rc, "resolve_env", lambda name: "key")
    monkeypatch.setattr(rc, "render_motion_reel", lambda specs, audio, out, **k: captured.update(specs=specs) or out)
    llm = _SlidesLLM(["एक बात।", "दो बात।", "तीन बात।"], ["One thing.", "Two things.", "Three things."])
    ch = _channel(narration=narration or NarrationConfig(provider="kokoro"))
    path, voice = rc._try_motion_reel(ch, [_asset(3)], _brief(), _Track(), "/tmp/o.mp4", llm=llm, seed="s",
                                      language=language, **kw)
    return path, voice, provider, captured["specs"]


def test_a_hindi_reel_speaks_hindi_in_a_hindi_voice_and_shows_english(monkeypatch):
    path, voice, provider, specs = _narrated(
        monkeypatch, HINDI, NarrationConfig(provider="kokoro", spoken_names={"hi": SPOKEN_BRAND}))
    assert path == "/tmp/o.mp4" and voice in default_voices("kokoro", HINDI)
    assert [c[1] for c in provider.calls] == [voice] * 3 and {c[3] for c in provider.calls} == {"hi"}
    assert all(HINDI.is_native(c[0]) for c in provider.calls[:2])                          # Devanagari to the voice
    assert provider.calls[0][0] == "एक बात।" and "Hindi" in provider.calls[0][2]            # and told it is Hindi
    assert provider.calls[2][0].startswith(SPOKEN_BRAND)                                   # the brand is not in Latin
    captions = [p["caption"] for s in specs for p in s["parts"]]
    assert captions[:2] == ["One thing.", "Two things."] and all(HINDI.is_screen_text(c) for c in captions)


def test_english_reels_are_unchanged_and_configured_hindi_voices_win(monkeypatch):
    llm_en = _SlidesLLM(["One.", "Two.", "Three."], ["One.", "Two.", "Three."])
    provider = _Provider()
    monkeypatch.setattr(rc, "build_provider", lambda *a, **k: provider)
    monkeypatch.setattr(rc, "resolve_env", lambda name: "key")
    monkeypatch.setattr(rc, "render_motion_reel", lambda specs, audio, out, **k: out)
    rc._try_motion_reel(_channel(narration=NarrationConfig(provider="kokoro", voices=["af_heart"])), [_asset(3)],
                        _brief(), _Track(), "/tmp/o.mp4", llm=llm_en, seed="s")
    assert {c[1] for c in provider.calls} == {"af_heart"} and {c[3] for c in provider.calls} == {"en"}
    assert all("Hindi" not in c[2] for c in provider.calls)

    # Hindi ignores the English `voices` (Kokoro's English names would speak Hindi badly) unless
    # the channel lists Hindi voices.
    _, voice, _, _ = _narrated(monkeypatch, HINDI, NarrationConfig(provider="kokoro", voices=["af_heart"]))
    assert voice in default_voices("kokoro", HINDI)
    _, voice, _, _ = _narrated(monkeypatch, HINDI, NarrationConfig(provider="kokoro", voices=["af_heart"],
                                                                    voices_by_language={"hi": ["hm_omega"]}))
    assert voice == "hm_omega"


# -- the pipeline: caption lead, language recorded ------------------------------------------

class _Pipe:
    def __init__(self, *a, **k):
        pass

    def analyze(self, url):
        return object(), _Brief

    def run_from_brief(self, *a, **k):
        return []


class _Cap:
    text, hashtags = "Ye update aapke workflow ko badal sakta hai.\n\n#AI", ["#AI"]


def _process(monkeypatch, channel, genre_idx=0, package=None, **kw):
    from info_snipe.models import Article

    seen = {}
    monkeypatch.setattr(rc, "_build_llm", lambda c: object())
    monkeypatch.setattr(rc, "Pipeline", _Pipe)
    monkeypatch.setattr(rc, "generate_caption", lambda *a, **k: seen.update(caption_language=k.get("language")) or _Cap())
    monkeypatch.setattr(rc, "write_package", lambda llm, brief, **k: seen.update(package_language=k.get("language")) or package)
    art = Article(content_id="x", title="t", url="https://x.example/a", source_name="s", genre="tech")
    return rc._process_one(art, channel.genres[genre_idx], channel, dry_run=True, hook_style="auto", **kw), seen


def test_hindi_posts_use_a_hinglish_caption_and_never_lead_it_with_the_english_hook(monkeypatch):
    pkg = writer.HookPackage(hook="Can your voice agent speak?", formula="the-question", score=57,
                             spoken="क्या आपका वॉइस एजेंट बोल सकता है?")           # no opener
    out, seen = _process(monkeypatch, _channel(language="hi"), package=pkg)
    assert seen == {"caption_language": HINDI, "package_language": HINDI}
    assert out.language == "hi" and out.caption_text.startswith("Ye update")             # not the English hook
    out, _ = _process(monkeypatch, _channel(language="en"), package=pkg)
    assert out.language == "en" and out.caption_text.startswith("Can your voice agent speak?\n\n")
    pkg.opener = "Open weights aur 200 ms latency: ab self-host karna aasan hai."
    out, _ = _process(monkeypatch, _channel(language="hi"), package=pkg)
    assert out.caption_text.startswith(pkg.opener + "\n\n")


def test_a_run_override_beats_the_channel_and_the_genre(monkeypatch):
    ch = _channel(language="en", genres=[GenreSetting(genre="tech"), GenreSetting(genre="ai", language="hi")])
    assert _process(monkeypatch, ch, genre_idx=1)[0].language == "hi"
    assert _process(monkeypatch, ch, genre_idx=0)[0].language == "en"
    assert _process(monkeypatch, ch, genre_idx=1, language_override="en")[0].language == "en"


# -- CLI --------------------------------------------------------------------------------------

def test_cli_language_flag(monkeypatch):
    from narovva import cli

    got = {}
    monkeypatch.setattr(cli, "load_channel", lambda p: _channel())
    monkeypatch.setattr(cli, "run_channel", lambda *a, **k: got.update(k) or rc.ChannelRunResult(channel_id="c"))
    assert cli.main(["run-channel", "x.yaml", "--language", "hi"]) == 0 and got["language"] == "hi"
    cli.main(["run-channel", "x.yaml"])
    assert got["language"] is None
    with pytest.raises(SystemExit):
        cli.main(["run-channel", "x.yaml", "--language", "fr"])

    import narovva.orchestration.viral as ov

    monkeypatch.setattr(ov, "run_viral", lambda c, **k: got.update(viral=k) or rc.ChannelRunResult(channel_id="c"))
    assert cli.main(["run-viral", "x.yaml", "--force", "--language", "hi"]) == 0
    assert got["viral"]["language"] == "hi"
