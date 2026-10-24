from __future__ import annotations

import importlib

import pytest

from narovva.config.schema import BrandKitConfig, ChannelConfig, FocusConfig, GenreSetting, HooksConfig, VoiceConfig
from narovva.hooks import writer
from narovva.hooks.score import classify, library, score
from narovva.hooks.voice import drop_banned_sentences, find_banned, voice_brief

rc = importlib.import_module("narovva.orchestration.run_channel")


class Brief:
    headline = "Mistral AI unveils Voxtral 3 for real-time voice agents"
    summary = "Mistral released Voxtral 3, a voice agent stack with 200 ms latency, open weights."
    why_it_matters = "Developers can build real-time voice agents without a closed API."
    key_facts = ["Latency is 200 ms", "Weights are open", "Runs on one GPU"]
    tone = "neutral"
    hook = None
    category = "ai"


class _LLM:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def complete_json(self, system, user):
        self.calls.append((system, user))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


# -- library and scorer ------------------------------------------------------

def test_every_formula_example_passes_and_classifies_as_itself():
    lib = library()["formulas"]
    assert len(lib) == 18
    for f in lib:
        assert {"id", "name", "shape", "example", "fails_when", "match"} <= set(f)
        s = score(f["example"])
        assert s.verdict >= 45, (f["id"], s.verdict)
        assert classify(f["example"]) == f["id"]


def test_summaries_score_below_real_hooks():
    summary = score("European diplomats face violent assault in the West Bank.")  # run 711's hook
    headline = score("Mistral AI unveils Voxtral 3 for real-time voice agents.")
    hype = score("This is a huge game changer for AI.")
    good = score("Can your voice agent finally speak in real time?")
    assert summary.band == headline.band == hype.band == "WEAK"
    assert max(summary.verdict, headline.verdict, hype.verdict) < 45 <= good.verdict
    assert summary.formula == "unclassified"


def test_weakest_property_is_named():
    s = score("Can your voice agent finally speak in real time?")
    assert s.weakest in s.parts and s.parts[s.weakest] == min(s.parts.values())


# -- rules -------------------------------------------------------------------

STORY = writer._story_text(Brief)


@pytest.mark.parametrize("text, ok", [
    ("Can your voice agent finally speak in real time?", True),
    ("Your voice agent now answers in 200 ms.", True),        # number from the story
    ("Your voice agent now answers in 50 ms.", False),        # invented number
    ("Voice agents got faster because Mistral shipped.", False),  # answers itself
    ("This voice stack is a game changer.", False),           # banned by the channel
    ("Mistral AI unveils Voxtral 3 for real-time voice agents", False),  # the headline
])
def test_clean_hook_rules(text, ok):
    got = writer.clean_hook(text, Brief.headline, story=STORY, banned=["game changer"])
    assert (got is not None) is ok


def test_clean_cover_is_short_upper_and_not_the_hooks_words():
    hook = "Can your voice agent finally speak in real time?"
    assert writer.clean_cover("Open voice stack", hook) is None  # 'voice' is the hook's word
    assert writer.clean_cover("Mistral's open stack", hook) == "MISTRAL'S OPEN STACK"
    assert writer.clean_cover("Real time agents", hook) is None          # repeats the hook
    assert writer.clean_cover("One", hook) is None                       # too short
    assert writer.clean_cover("A very long cover line here", hook) is None


def test_clean_opener_fits_before_more_and_does_not_repeat():
    hook = "Can your voice agent finally speak in real time?"
    good = "Open weights, 200 ms replies: you can self-host it today."
    assert writer.clean_opener(good, hook, "MISTRAL'S OPEN STACK", Brief.headline) == good
    assert writer.clean_opener("x" * 130, hook, None, Brief.headline) is None
    assert writer.clean_opener("Can your voice agent finally speak in real time now?", hook, None,
                               Brief.headline) is None


def test_pick_prefers_a_complete_package_and_reports_failures():
    raw = {"options": [
        {"hook": "Mistral unveils Voxtral 3 for voice agents.", "formula": "the-reveal"},  # restates
        {"hook": "Can your voice agent finally speak in real time?", "formula": "the-question",
         "cover": "Mistral's open stack", "opener": "Open weights, 200 ms replies: you can self-host it today."},
        {"hook": "Your voice agent now answers in 50 ms.", "formula": "the-statistic"},  # invented number
    ]}
    pkg, why = writer.pick(raw, Brief)
    assert pkg.hook == "Can your voice agent finally speak in real time?"
    assert pkg.formula == "the-question" and pkg.cover == "MISTRAL'S OPEN STACK" and pkg.opener
    assert len(why) == 2


def test_write_package_retries_with_reasons_then_falls_back():
    llm = _LLM({"options": [{"hook": "Mistral AI unveils Voxtral 3 for real-time voice agents"}]},
               {"options": [{"hook": "Your voice agent now answers in 200 ms.", "formula": "the-statistic",
                             "cover": "Mistral's open stack"}]})
    pkg = writer.write_package(llm, Brief, formulas=["the-statistic", "the-question"], audience="AI engineers")
    assert pkg.hook == "Your voice agent now answers in 200 ms." and pkg.cover == "MISTRAL'S OPEN STACK"
    assert "Your last options failed" in llm.calls[1][1]
    assert "the-statistic" in llm.calls[0][0] and "the-mistake" not in llm.calls[0][0]
    assert "Audience and house rules: AI engineers" in llm.calls[0][1]

    class WithHook(Brief):
        hook = "What does real-time voice cost you now?"

    pkg = writer.write_package(_LLM({"options": []}, {"options": []}), WithHook)
    assert pkg.hook == "What does real-time voice cost you now?" and pkg.cover is None


# -- voice -------------------------------------------------------------------

def test_banned_words_are_found_and_dropped_but_hashtags_kept():
    text = "Big release. This is a game-changer for you. Try it today.\n\n#AI #GameChanger"
    assert find_banned(text, ["game-changer"]) == ["game-changer"]
    out = drop_banned_sentences(text, ["game-changer"])
    assert "game-changer for you" not in out and "Try it today." in out and "#GameChanger" in out


def test_voice_brief_and_config():
    v = VoiceConfig(audience="a backend engineer", banned_words=["unlock"], never_claim=["prices not in the story"])
    brief = voice_brief("a backend engineer", v)
    assert brief.startswith("a backend engineer.") and "unlock" in brief and "prices not in the story" in brief
    assert voice_brief("someone", None) == "someone"

    ch = ChannelConfig(id="c", genres=[GenreSetting(genre="tech")], brand=BrandKitConfig(), voice=v,
                       focus=FocusConfig(enabled=True, audience="AI engineers", caption_voice="practical",
                                         genres=[GenreSetting(genre="ai_practitioner")]))
    assert ch.audience.startswith("AI engineers.")      # the focus audience wins
    assert ch.caption.voice.startswith("practical") and "never use: unlock" in ch.caption.voice
    assert ch.banned_words == ["unlock"]


def test_unknown_formula_is_a_config_error():
    with pytest.raises(ValueError):
        HooksConfig(formulas=["the-mistake", "the-nonsense"])


def test_live_config_has_voice_and_hooks():
    from narovva.config import load_channel

    ch = load_channel("config/channels/example-tech-ig.yaml")
    assert ch.hooks.enabled and "the-mistake" in ch.hooks.formulas
    assert "game-changer" in ch.banned_words and "Never claim" in ch.audience


# -- pipeline ----------------------------------------------------------------

def test_regular_post_gets_hook_opener_and_records_it(monkeypatch):
    ch = ChannelConfig(id="c", genres=[GenreSetting(genre="tech")], brand=BrandKitConfig(),
                       hooks=HooksConfig(enabled=True), voice=VoiceConfig(banned_words=["game-changer"]))

    class _Pipe:
        def __init__(self, *a, **k):
            pass

        def analyze(self, url):
            return object(), Brief

        def run_from_brief(self, *a, **k):
            return []

    class _Caption:
        text, hashtags = "A game-changer for builders. Self-host it.\n\n#AI", ["#AI"]

    pkg = writer.HookPackage(hook="Can your voice agent finally speak in real time?", formula="the-question",
                             score=57, cover="MISTRAL'S OPEN STACK",
                             opener="Open weights, 200 ms replies: you can self-host it today.")
    seen = {}

    def fake_write_package(llm, brief, **kw):
        seen.update(kw)
        return pkg

    monkeypatch.setattr(rc, "_build_llm", lambda c: object())
    monkeypatch.setattr(rc, "Pipeline", _Pipe)
    monkeypatch.setattr(rc, "generate_caption", lambda *a, **k: _Caption())
    monkeypatch.setattr(rc, "write_package", fake_write_package)
    from info_snipe.models import Article

    art = Article(content_id="x", title="t", url="https://x.example/a", source_name="s", genre="tech")
    out = rc._process_one(art, ch.genres[0], ch, dry_run=True)
    assert seen["style"] == "auto" and seen["banned"] == ["game-changer"]
    assert out.caption_text.startswith(pkg.opener + "\n\n")
    assert "game-changer" not in out.caption_text and "#AI" in out.caption_text
    assert out.hook is pkg
    assert rc.hook_fields(out.hook) == {"hook_text": pkg.hook, "hook_formula": "the-question",
                                        "hook_score": 57, "cover_text": "MISTRAL'S OPEN STACK"}
    assert rc.hook_fields(None) == {}


def test_cover_uses_the_short_cover_text(monkeypatch, tmp_path):
    made = {}

    def fake_make_cover(out, **kw):
        made.update(kw)
        import os

        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "wb").write(b"jpg")
        return out

    class _Host:
        def upload(self, data, path, content_type=None):
            return type("H", (), {"url": "https://blob/cover.jpg"})()

    class Art:
        content_id = "x"

    monkeypatch.setattr(rc, "make_cover", fake_make_cover)
    ch = ChannelConfig(id="c" + str(tmp_path).replace("/", "")[-6:], genres=[GenreSetting(genre="tech")],
                       brand=BrandKitConfig())
    url = rc._host_cover(_Host(), [], ch, Art(), Brief, [], hook="Can your voice agent speak?",
                         cover_text="MISTRAL'S OPEN STACK")
    assert url == "https://blob/cover.jpg" and made["headline"] == "MISTRAL'S OPEN STACK"
    rc._host_cover(_Host(), [], ch, Art(), Brief, [], hook="Can your voice agent speak?")
    assert made["headline"] == "Can your voice agent speak?"  # no cover text: the hook, as before


def test_only_viral_posts_get_the_trending_label():
    specs = [{"kind": "hook", "kicker": "AI", "heading": "Old"}]
    assert rc.apply_hook([dict(specs[0])], "Hook line here.", "Old", trending=False)[0]["kicker"] == "AI"
    assert rc.apply_hook([dict(specs[0])], "Hook line here.", "Old")[0]["kicker"] == "TRENDING NOW"

    from narovva.motion.storyboard import hook_board

    class Board:
        beats = [{"lines": ["x"], "screens": ["x"], "cmarks": [None], "kicker": "AI", "scene": "text", "data": {}}]

    b = hook_board(Board(), "Can your agent speak?", None, "H", trending=False)
    assert b.beats[0]["kicker"] == "AI" and b.beats[0]["lines"][0] == "Can your agent speak?"
