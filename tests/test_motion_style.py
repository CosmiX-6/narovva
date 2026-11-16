from __future__ import annotations

import json
import sys
from datetime import UTC, datetime

import pytest
from poster_core.models import (
    AssetPlan,
    AssetType,
    ContentBrief,
    DeckSlide,
    Entity,
    GeneratedAsset,
    Platform,
    SlideKind,
    StoryCategory,
)

import narovva.orchestration.run_channel  # noqa: F401
from narovva.config import load_channel
from narovva.config.schema import BrandKitConfig, ChannelConfig, GenreSetting, MotionStyleConfig, NarrationConfig
from narovva.motion.render import stage_project
from narovva.motion.sample import SAMPLE_SLIDES, sample_deck
from narovva.motion.style import deck_ui, direct_scenes, story_subject
from narovva.narration.script import Script

rc = sys.modules["narovva.orchestration.run_channel"]
WHEN = datetime(2026, 10, 24, 9, 30, tzinfo=UTC)


def _ui(**changes) -> dict:
    look = MotionStyleConfig.model_validate(changes)
    return deck_ui(look, subject="STARLINK", category="POLITICS", brand="CONTEXT UNFILTERED", when=WHEN)


def test_default_look_is_the_case_file():
    ui = _ui()
    assert ui["hud"] == {"style": "case_file", "label": "CASE FILE: STARLINK", "meta": "timecode", "date": "24 OCT 2026", "rec": True}
    assert ui["progress"] == "top" and ui["captions"]["style"] == "karaoke" and ui["timeline"] == "cards"


def test_each_header_style_brings_its_own_label_meta_and_progress():
    ui = _ui(hud={"style": "breakdown"})
    assert (ui["hud"]["label"], ui["hud"]["meta"], ui["progress"]) == ("STARLINK BREAKDOWN", "date", "hud")
    ui = _ui(hud={"style": "brand"})
    assert (ui["hud"]["label"], ui["hud"]["meta"], ui["progress"]) == ("CONTEXT UNFILTERED", "none", "bottom")
    assert _ui(hud={"style": "none"})["progress"] == "bottom"
    assert _ui(hud={"style": "brand"}, progress="hud")["progress"] == "bottom"   # no header line to run under


def test_label_template_meta_and_progress_are_configurable():
    ui = _ui(hud={"label": "{brand} // file {subject} ({category}, {date})", "meta": "date", "rec_dot": False}, progress="none")
    assert ui["hud"]["label"] == "CONTEXT UNFILTERED // FILE STARLINK (POLITICS, 24 OCT 2026)"
    assert ui["hud"]["meta"] == "date" and ui["hud"]["rec"] is False and ui["progress"] == "none"
    assert _ui(hud={"label": "dossier {unknown}"})["hud"]["label"] == "DOSSIER {UNKNOWN}"
    assert _ui(hud={"label": "broken {"})["hud"]["label"] == "BROKEN {"


def test_caption_look_is_validated():
    assert _ui(captions={"style": "pill", "highlight": "#F59E0B"})["captions"] == {"style": "pill", "highlight": "#F59E0B", "chunk": 3}
    with pytest.raises(ValueError):
        MotionStyleConfig.model_validate({"captions": {"style": "comic-sans"}})
    with pytest.raises(ValueError):
        MotionStyleConfig.model_validate({"captions": {"chunk_words": 0}})


def test_direction_is_needed_only_when_the_look_uses_it():
    assert MotionStyleConfig().wants_direction
    quiet = {"stamps": {"enabled": False}, "heading_marks": False}
    assert MotionStyleConfig.model_validate({**quiet, "hud": {"style": "brand"}}).wants_direction is False
    assert MotionStyleConfig.model_validate({**quiet, "hud": {"label": "FILE 7"}}).wants_direction is False
    assert MotionStyleConfig.model_validate({**quiet, "hud": {"label": "FILE {subject}"}}).wants_direction is True


def _brief(**kw):
    return ContentBrief(key_event="k", summary="s", headline="h", category="politics", **kw)


def test_story_subject_prefers_the_script_then_the_main_entity_then_the_category():
    assert story_subject("STARLINK", _brief()) == "STARLINK"
    assert story_subject(None, _brief(entities=[Entity(name="Elon Musk Foundation Trust", kind="org")])) == "ELON MUSK FOUNDATION"
    assert story_subject(None, _brief()) == "POLITICS"


def _script(n=3, **kw):
    base = dict(lines=["x"] * n, screen=["x"] * n, stamps=[None] * n, line_marks=[None] * n, heading_marks=[None] * n)
    base.update(kw)
    return Script(**base)


def test_direct_scenes_colours_stamps_by_tone_and_honours_the_switches():
    specs = [{"kind": "hook"}, {"kind": "stats"}, {"kind": "cta"}]
    script = _script(stamps=[None, {"text": "UP 20%", "tone": "positive"}, None],
                     heading_marks=[None, "jobs", None], line_marks=["now", "20%", None])
    direct_scenes(specs, script, MotionStyleConfig())
    assert specs[1]["stamp"] == {"text": "UP 20%", "color": "#22C55E"} and specs[1]["hmark"] == "jobs"
    assert specs[0]["lines"] == ["x"] and specs[0]["cmarks"] == ["now"] and "stamp" not in specs[0]
    assert specs[2]["cmarks"] == [None]
    direct_scenes(specs, script, MotionStyleConfig.model_validate({"stamps": {"enabled": False}, "heading_marks": False}))
    assert "stamp" not in specs[1] and "hmark" not in specs[1] and specs[1]["cmarks"] == ["20%"]


def test_stage_project_writes_the_look_and_an_empty_one_by_default(tmp_path):
    kwargs = dict(accent="#3B82F6", handle="h", brand="B", logo_path="assets/logo/CU.png", audio_bytes=None)
    stage_project(tmp_path / "a", [dict(s) for s in SAMPLE_SLIDES[:2]], ui=_ui(), **kwargs)
    stage_project(tmp_path / "b", [dict(s) for s in SAMPLE_SLIDES[:2]], **kwargs)
    deck = lambda d: json.loads((tmp_path / d / "deck.js").read_text(encoding="utf-8")[len("window.CU_DECK = "):].rstrip().rstrip(";"))
    assert deck("a")["ui"]["hud"]["label"] == "CASE FILE: STARLINK" and deck("b")["ui"] == {}
    assert (tmp_path / "a" / "fonts" / "jetbrains-mono-latin-700-normal.woff2").is_file()


def test_sample_deck_carries_stamps_and_emphasis_with_the_look():
    deck = sample_deck(captions=True, look=MotionStyleConfig())
    stamped = [s for s in deck if s.get("stamp")]
    assert len(stamped) == 3 and {s["kind"] for s in stamped} == {"timeline", "impact", "comparison"}
    assert next(s for s in deck if s["kind"] == "scream")["caption"] == "67% cheaper per token."
    assert all("stamp" not in s for s in sample_deck(captions=True))


def test_example_channel_spells_out_the_look():
    look = load_channel("config/channels/example-tech-ig.yaml").motion
    assert look.hud.style == "chapter" and look.captions.style == "boxed" and look.stamps.enabled
    assert look.story.viewer_questions == 2


def test_chapter_header_has_no_progress_bar_of_its_own():
    from narovva.config.schema import MotionStyleConfig
    look = MotionStyleConfig.model_validate({"hud": {"style": "chapter"}, "captions": {"style": "boxed"}})
    ui = deck_ui(look, subject="STARLINK", category="POLITICS", brand="CU", when=WHEN)
    assert ui["hud"]["style"] == "chapter" and ui["progress"] == "none" and ui["captions"]["style"] == "boxed"


# -- orchestration ---------------------------------------------------------

class _Director:
    def __init__(self):
        self.calls = 0

    def complete_json(self, system, user):
        self.calls += 1
        return {
            "lines": ["Why now?", "Two things changed.", "Follow CU."],
            "subject": "chip exports",
            "marks": [{"line": "now"}, {"line": "Two", "heading": "T1"}, {}],
            "stamps": [None, {"text": "CONFIRMED", "tone": "neutral"}, None],
        }


SLIDES = MotionStyleConfig.model_validate({"story": {"mode": "slides"}})


def _channel(**kw):
    base = dict(
        id="c", ig_business_account_id="1", genres=[GenreSetting(genre="tech")],
        brand=BrandKitConfig(name="Context Unfiltered", social_handle="cu", logo_path="assets/logo/CU.png"),
        publish_format="motion_reel", narration=None, motion=SLIDES,
    )
    base.update(kw)
    return ChannelConfig(**base)


def _asset():
    slides = [DeckSlide(kind=SlideKind.HOOK, heading="H"), DeckSlide(kind=SlideKind.TEXT, heading="T1"),
              DeckSlide(kind=SlideKind.TEXT, heading="T2")]
    plan = AssetPlan(asset_type=AssetType.CAROUSEL, platform=Platform.INSTAGRAM_STORY, headline="H",
                     category=StoryCategory.AI, slides=slides)
    return GeneratedAsset(asset_type=AssetType.CAROUSEL, platform=Platform.INSTAGRAM_STORY,
                          paths=[f"/tmp/{i}.png" for i in range(3)], plan=plan)


class _Track:
    id, audio_bytes, attribution = "t", b"music", "c"


def _capture(monkeypatch):
    seen = {}
    monkeypatch.setattr(rc, "render_motion_reel", lambda specs, audio, out, **kw: (seen.update(kw, specs=specs), out)[1])
    return seen


def test_unnarrated_reel_still_gets_its_direction_and_look(monkeypatch):
    seen = _capture(monkeypatch)
    llm = _Director()
    path, voice = rc._try_motion_reel(_channel(), [_asset()], _brief(), _Track(), "/tmp/o.mp4", llm=llm, when=WHEN)
    assert path == "/tmp/o.mp4" and voice is None and llm.calls == 1
    assert seen["ui"]["hud"]["label"] == "CASE FILE: CHIP EXPORTS" and seen["ui"]["hud"]["date"] == "24 OCT 2026"
    assert seen["specs"][1]["stamp"]["text"] == "CONFIRMED" and seen["specs"][1]["hmark"] == "T1"
    assert not any(s.get("parts") for s in seen["specs"])            # no voice, no timed captions


def test_plain_look_without_narration_makes_no_llm_call(monkeypatch):
    seen = _capture(monkeypatch)
    llm = _Director()
    plain = MotionStyleConfig.model_validate(
        {"story": {"mode": "slides"}, "hud": {"style": "brand"}, "stamps": {"enabled": False}, "heading_marks": False})
    rc._try_motion_reel(_channel(motion=plain), [_asset()], _brief(), _Track(), "/tmp/o.mp4", llm=llm)
    assert llm.calls == 0 and seen["ui"]["hud"]["style"] == "brand"
    assert not any("stamp" in s for s in seen["specs"])


def test_narration_failure_keeps_the_direction(monkeypatch):
    class Boom:
        def synthesize(self, *a, **k):
            raise RuntimeError("quota exceeded")

    monkeypatch.setattr(rc, "build_provider", lambda *a, **k: Boom())
    monkeypatch.setattr(rc, "resolve_env", lambda name: "key")
    seen = _capture(monkeypatch)
    channel = _channel(narration=NarrationConfig(provider="openai", voices=["v1"]))
    path, voice = rc._try_motion_reel(channel, [_asset()], _brief(), _Track(), "/tmp/o.mp4", llm=_Director())
    assert path == "/tmp/o.mp4" and voice is None
    assert seen["specs"][1]["stamp"]["text"] == "CONFIRMED" and not any(s.get("parts") for s in seen["specs"])
