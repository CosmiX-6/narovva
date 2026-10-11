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
    assert total_duration([3.0, 4.0, 5.0]) == pytest.approx(12.0 - 0.8)


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
    assert render_module._probe_duration(out) == pytest.approx(total_duration([4.6, 5.0]), abs=0.2)


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
    path = run_channel_module._try_motion_reel(_channel(), [_carousel_asset(2)], _brief(), _Track(), [2.2, 3.0], "/tmp/x.mp4")
    assert path == "/tmp/x.mp4" and seen["accent"] == "#3B82F6" and seen["handle"] == "cu"


def test_try_motion_reel_returns_none_on_any_failure(monkeypatch):
    def boom(*a, **k):
        raise MotionRenderError("chrome crashed")

    monkeypatch.setattr(run_channel_module, "render_motion_reel", boom)
    assert run_channel_module._try_motion_reel(_channel(), [_carousel_asset(2)], _brief(), _Track(), [2.2, 3.0], "/tmp/x.mp4") is None
    # bad data (durations don't match images) also degrades instead of raising
    assert run_channel_module._try_motion_reel(_channel(), [_carousel_asset(2)], _brief(), _Track(), [2.2], "/tmp/x.mp4") is None


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
