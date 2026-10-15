from __future__ import annotations

import json
import shutil
import sys

import pytest
from poster_core.models import (
    AssetPlan, AssetType, ComparisonPair, ContentBrief, DeckSlide, GeneratedAsset, Platform,
    Quote, SlideKind, StoryCategory, TimelineEvent,
)

from narovva.config.schema import BrandKitConfig, ChannelConfig, GenreSetting
from narovva.motion import MotionRenderError, slide_specs_from_assets, total_duration
from narovva.motion import render as render_module
from narovva.motion.render import stage_project
from narovva.motion.sample import SAMPLE_SLIDES

import narovva.orchestration.run_channel  # noqa: F401

run_channel_module = sys.modules["narovva.orchestration.run_channel"]


def _carousel_asset(n_slides: int = 3) -> GeneratedAsset:
    slides = [
        DeckSlide(kind=SlideKind.HOOK, heading="Big news", body="Details"),
        DeckSlide(kind=SlideKind.TIMELINE, timeline=[TimelineEvent(when="2025", what="Started")]),
        DeckSlide(kind=SlideKind.COMPARISON, comparison=ComparisonPair(label_a="A", value_a=1, label_b="B", value_b=2)),
        DeckSlide(kind=SlideKind.QUOTE, quote=Quote(text="Hi", attribution="Me")),
    ][:n_slides]
    plan = AssetPlan(
        asset_type=AssetType.CAROUSEL, platform=Platform.INSTAGRAM_STORY, headline="H",
        category=StoryCategory.AI, slides=slides,
    )
    return GeneratedAsset(
        asset_type=AssetType.CAROUSEL, platform=Platform.INSTAGRAM_STORY,
        paths=[f"/tmp/s{i}.png" for i in range(n_slides)], plan=plan,
    )


def test_total_duration_subtracts_scene_overlap():
    assert total_duration([]) == 0.0
    assert total_duration([3.0]) == pytest.approx(3.0)
    assert total_duration([3.0, 4.0, 5.0]) == pytest.approx(12.0 - 0.6)


def test_slide_specs_cover_one_spec_per_image_with_durations_and_default_kicker():
    cover = GeneratedAsset(
        asset_type=AssetType.COVER, platform=Platform.INSTAGRAM_STORY, paths=["/tmp/c.png"],
        plan=AssetPlan(asset_type=AssetType.COVER, platform=Platform.INSTAGRAM_STORY, headline="Cover", subheadline="Sub", category=StoryCategory.PRODUCT_LAUNCH),
    )
    assets = [cover, _carousel_asset()]
    specs = slide_specs_from_assets(assets, [2.2, 3.0, 4.0, 5.0])
    assert [s["kind"] for s in specs] == ["hook", "hook", "timeline", "comparison"]
    assert specs[0]["kicker"] == "PRODUCT LAUNCH" and specs[0]["body"] == "Sub"
    assert specs[2]["kicker"] == "TIMELINE" and specs[2]["timeline"] == [{"when": "2025", "what": "Started"}]
    assert specs[3]["comparison"]["value_a"] == "1"  # poster_core stringifies values
    assert [s["duration"] for s in specs] == [2.2, 3.0, 4.0, 5.0]
    json.dumps(specs)  # plain data only


def test_slide_specs_default_to_brisk_durations_and_compact_text():
    long_body = "Word " * 80
    asset = _carousel_asset(2)
    asset.plan.slides[0].body = long_body
    specs = slide_specs_from_assets([asset])
    assert len(specs[0]["body"]) <= 106 and specs[0]["duration"] <= 3.6
    assert all(1.7 <= s["duration"] <= 3.6 for s in specs)


def test_motion_duration_voice_sets_length_with_floor():
    from narovva.motion.slides import motion_duration

    assert motion_duration(0, "text", 3.0) == pytest.approx(3.45)  # + 0.15 lead + 0.3 tail
    assert motion_duration(0, "text", 0.5) == 1.7      # never shorter than the floor
    assert motion_duration(999, "text") == 3.6          # reading time is capped
    assert motion_duration(10, "hook") >= 2.2


def test_slide_specs_reject_mismatched_durations():
    with pytest.raises(ValueError):
        slide_specs_from_assets([_carousel_asset()], [2.0])


def test_stage_project_writes_deck_audio_and_total(tmp_path, monkeypatch):
    monkeypatch.setattr(render_module, "_prepare_audio", lambda audio, total, dest: dest.write_bytes(b"x"))
    slides = [dict(s) for s in SAMPLE_SLIDES[:2]]
    slides[0]["heading"] = "</script><b>x</b>"  # hostile article text
    total = stage_project(
        tmp_path / "p", slides, accent="#3B82F6", handle="h", brand="B",
        logo_path="assets/logo/CU.png", audio_bytes=b"mp3",
    )
    assert total == pytest.approx(total_duration([s["duration"] for s in slides]))
    html = (tmp_path / "p" / "index.html").read_text()
    assert "{{TOTAL}}" not in html and "HF_AUDIO" not in html and 'id="music"' in html
    deck_js = (tmp_path / "p" / "deck.js").read_text()
    assert "</script>" not in deck_js and "\\u003c/script>" in deck_js
    assert (tmp_path / "p" / "assets" / "logo.png").is_file()


def _deck(tmp_path, name) -> dict:
    text = (tmp_path / name / "deck.js").read_text(encoding="utf-8")
    return json.loads(text[len("window.CU_DECK = "):].rstrip().rstrip(";"))


def test_stage_project_stages_the_article_photo_and_a_stable_seed(tmp_path):
    from narovva.motion.sample import write_sample_photo

    photo = write_sample_photo(tmp_path / "in.jpg")
    kwargs = dict(accent="#3B82F6", handle="h", brand="B", logo_path="assets/logo/CU.png", audio_bytes=None)
    stage_project(tmp_path / "a", [dict(s) for s in SAMPLE_SLIDES[:2]], photo_path=photo, photo_credit="Image: Wire", seed="story-1", **kwargs)
    deck = _deck(tmp_path, "a")
    assert deck["photo"]["mode"] == "card" and deck["photo"]["credit"] == "Image: Wire"
    assert (tmp_path / "a" / "assets" / "photo.jpg").is_file() and (tmp_path / "a" / "assets" / "photo_bg.jpg").is_file()
    assert deck["captions"] is False
    for extra in ("ambient.js", "viz.js"):
        assert (tmp_path / "a" / extra).is_file()

    stage_project(tmp_path / "b", [dict(s) for s in SAMPLE_SLIDES[:2]], seed="story-1", **kwargs)
    stage_project(tmp_path / "c", [dict(s) for s in SAMPLE_SLIDES[:2]], seed="story-2", **kwargs)
    assert _deck(tmp_path, "b")["seed"] == deck["seed"] != _deck(tmp_path, "c")["seed"]
    assert _deck(tmp_path, "b")["photo"] is None            # no photo is a normal case


def test_stage_project_survives_an_unusable_photo(tmp_path):
    (tmp_path / "bad.jpg").write_bytes(b"nope")
    stage_project(
        tmp_path / "p", [dict(s) for s in SAMPLE_SLIDES[:1]], accent="#fff", handle="h", brand="B",
        logo_path="assets/logo/CU.png", audio_bytes=None, photo_path=str(tmp_path / "bad.jpg"),
    )
    assert _deck(tmp_path, "p")["photo"] is None


def test_sample_deck_carries_charts_and_captions():
    from narovva.motion.sample import sample_deck

    deck = sample_deck(captions=True)
    # Scream scene: "67% cheaper per token" \u2192 single ring item
    scream = next(s for s in deck if s["kind"] == "scream")
    assert scream["viz"]["items"][0]["type"] == "ring"
    # Stats scene: 3.2x / $1.2B / 14 \u2014 no two facts share a unit, so all "number"
    stats = next(s for s in deck if s["kind"] == "stats")
    assert all(i["type"] == "number" for i in stats["viz"]["items"])
    assert next(s for s in deck if s["kind"] == "comparison")["viz"]["delta"] == "\u221267%"
    assert all(s["caption"] and s["duration"] >= s["voice"] + 0.25 - 1e-6 for s in deck)
    assert all("caption" not in s for s in sample_deck(captions=False))
    json.dumps(deck)


def test_chart_specs_are_built_before_long_facts_are_trimmed():
    asset = _carousel_asset(1)
    fact = "After two years of negotiation between the regulators and the company the fine was finally set at 60%"
    asset.plan.slides[0] = DeckSlide(kind=SlideKind.STATS, facts=[fact])
    spec = slide_specs_from_assets([asset])[0]
    assert len(spec["facts"][0]) <= 65                       # the on-screen copy is trimmed...
    assert spec["viz"]["items"][0]["text"] == "60%"          # ...but the number it ended on survives


def test_stage_project_rejects_empty_and_missing_logo(tmp_path):
    with pytest.raises(MotionRenderError):
        stage_project(tmp_path / "a", [], accent="#fff", handle="h", brand="B", logo_path="x", audio_bytes=None)
    with pytest.raises(MotionRenderError):
        stage_project(tmp_path / "b", SAMPLE_SLIDES[:1], accent="#fff", handle="h", brand="B", logo_path="/nope.png", audio_bytes=None)


def test_render_fails_cleanly_when_hyperframes_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERFRAMES_BIN", "/definitely/not/hyperframes")
    with pytest.raises(MotionRenderError):
        render_module.render_motion_reel(
            SAMPLE_SLIDES[:1], None, str(tmp_path / "o.mp4"), accent="#fff", handle="h", brand="B",
            logo_path="assets/logo/CU.png",
        )


@pytest.mark.skipif(not (shutil.which("npx") and shutil.which("ffmpeg")), reason="needs Node toolchain + ffmpeg")
def test_real_hyperframes_render_of_two_slides(tmp_path):
    out = render_module.render_motion_reel(
        [dict(s) for s in SAMPLE_SLIDES[:2]], None, str(tmp_path / "o.mp4"),
        accent="#EC4899", handle="contextunfiltered", brand="CONTEXT UNFILTERED",
        logo_path="assets/logo/CU.png",
    )
    expected = total_duration([s["duration"] for s in SAMPLE_SLIDES[:2]])
    assert render_module._probe_duration(out) == pytest.approx(expected, abs=0.2)


def _channel(**kw) -> ChannelConfig:
    base = dict(
        id="c", ig_business_account_id="1", genres=[GenreSetting(genre="tech")],
        brand=BrandKitConfig(name="CU", accent_color="#111111", category_accents={"ai": "#3B82F6"},
                             social_handle="cu", logo_path="assets/logo/CU.png"),
        publish_format="motion_reel",
    )
    base.update(kw)
    return ChannelConfig(**base)


def test_motion_reel_is_a_video_format():
    assert _channel().is_video and _channel(publish_format="reel").is_video
    assert not _channel(publish_format="carousel").is_video


def _brief() -> ContentBrief:
    return ContentBrief(key_event="k", summary="s", headline="h", category="ai")


class _Track:
    id = "t1"
    audio_bytes = b"a"
    attribution = "credit"


def test_try_motion_reel_passes_category_accent_and_handle(monkeypatch):
    seen = {}

    def fake_render(slides, audio, out, **kw):
        seen.update(kw, out=out)
        return out

    monkeypatch.setattr(run_channel_module, "render_motion_reel", fake_render)
    path, voice = run_channel_module._try_motion_reel(_channel(), [_carousel_asset(2)], _brief(), _Track(), "/tmp/x.mp4")
    assert path == "/tmp/x.mp4" and voice is None and seen["accent"] == "#3B82F6" and seen["handle"] == "cu"
    assert seen["photo_path"] is None and seen["photo_credit"] is None


def test_try_motion_reel_hands_over_the_article_photo(monkeypatch):
    seen = {}
    monkeypatch.setattr(run_channel_module, "render_motion_reel", lambda slides, audio, out, **kw: (seen.update(kw), out)[1])
    cover = _carousel_asset(1)                       # typographic: no photo
    deck = _carousel_asset(2)
    deck.source_image_path, deck.credit = "/tmp/src.jpg", "Image: Wire"
    run_channel_module._try_motion_reel(_channel(), [cover, deck], _brief(), _Track(), "/tmp/x.mp4", seed="abc")
    assert seen["photo_path"] == "/tmp/src.jpg" and seen["photo_credit"] == "Image: Wire" and seen["seed"] == "abc"


def test_try_motion_reel_returns_none_on_any_failure(monkeypatch):
    def boom(*a, **k):
        raise MotionRenderError("chrome crashed")

    monkeypatch.setattr(run_channel_module, "render_motion_reel", boom)
    assert run_channel_module._try_motion_reel(_channel(), [_carousel_asset(2)], _brief(), _Track(), "/tmp/x.mp4") == (None, None)


def test_process_one_falls_back_to_plain_reel_when_motion_render_fails(monkeypatch, tmp_path):
    asset = _carousel_asset(2)

    class _Pipe:
        def __init__(self, *a, **k): pass
        def analyze(self, url): return object(), _brief()
        def run_from_brief(self, *a, **k): return [asset]

    class _Caption:
        text, hashtags = "cap", ["#x"]

    class _Host:
        def upload(self, data, name, content_type=None):
            class H: url = "https://blob/x"
            return H()
        def delete(self, h): pass

    class _Pub:
        def publish(self, assets, caption, channel):
            class R: status, platform_post_id, error = "success", "42", None
            return R()

    calls = {}
    monkeypatch.setattr(run_channel_module, "_build_llm", lambda c: object())
    monkeypatch.setattr(run_channel_module, "Pipeline", _Pipe)
    monkeypatch.setattr(run_channel_module, "generate_caption", lambda *a, **k: _Caption())
    monkeypatch.setattr(run_channel_module, "_pick_music_track", lambda *a, **k: _Track())
    monkeypatch.setattr(run_channel_module, "VercelBlobImageHost", _Host)
    monkeypatch.setattr(run_channel_module, "get_publisher", lambda p: _Pub())
    monkeypatch.setattr(run_channel_module, "render_motion_reel", lambda *a, **k: (_ for _ in ()).throw(MotionRenderError("boom")))

    def fake_assemble(paths, audio, out, durations=None):
        calls["assemble"] = (paths, out)
        p = tmp_path / "r.mp4"; p.write_bytes(b"v")
        return str(p)

    monkeypatch.setattr(run_channel_module, "assemble_reel", fake_assemble)
    from info_snipe.models import Article as FeedArticle
    art = FeedArticle(content_id="abc", title="t", url="https://e.com/a", source_name="e", genre="tech")
    out = run_channel_module._process_one(art, GenreSetting(genre="tech"), _channel(), dry_run=False)
    assert out.status == "success" and "assemble" in calls and out.music_track_id == "t1"


def test_select_scenes_keeps_hook_cta_and_strongest_middle_in_order():
    from narovva.motion.slides import select_scenes

    kinds = ["hook", "text", "evidence", "stats", "text", "timeline", "conclusion", "comparison", "text", "cta"]
    specs = [{"kind": k, "i": i} for i, k in enumerate(kinds)]
    out = select_scenes(specs, max_scenes=6)
    assert len(out) == 6
    assert out[0]["kind"] == "hook" and out[-1]["kind"] == "cta"
    assert [s["i"] for s in out] == sorted(s["i"] for s in out)           # original order kept
    assert {"stats", "timeline", "comparison"} <= {s["kind"] for s in out}  # data beats prose
    assert select_scenes(specs[:5], max_scenes=6) == specs[:5]            # short decks untouched
