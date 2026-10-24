"""Regression tests for the fixes from the October code review."""

import sys

import httpx
import pytest
from info_snipe.models import Article as FeedArticle

import narovva.orchestration  # noqa: F401
from narovva.config.schema import BrandKitConfig, ChannelConfig, GenreSetting
from narovva.narration.script import caption_text

rc = sys.modules["narovva.orchestration.run_channel"]
TOKEN = "IG" + "Z" * 60


def _channel(**kw):
    base = dict(id="c", platform="instagram", ig_business_account_id="1",
                genres=[GenreSetting(genre="tech"), GenreSetting(genre="ai")], brand=BrandKitConfig(name="T"))
    base.update(kw)
    return ChannelConfig(**base)


def _art(i, genre):
    return FeedArticle(content_id=f"{genre}{i}", title="t", url=f"https://e.com/{genre}/{i}",
                       source_name="e", genre=genre)


def test_caption_text_joins_tts_spellings_only():
    assert caption_text("A spy inside Open A I? The G P U race heats up.") == "A spy inside Open AI? The GPU race heats up."
    assert caption_text("A new model ships today.") == "A new model ships today."


def test_refresh_failure_never_stores_the_token(monkeypatch):
    import narovva.tokens.instagram_token_store as store

    saved = {}

    class _Repo:
        def __init__(self, conn): pass
        def mark_instagram_token_refresh_failed(self, cid, err): saved["err"] = err

    req = httpx.Request("GET", f"https://graph.instagram.com/refresh_access_token?access_token={TOKEN}")
    monkeypatch.setattr(store, "get_valid_token", lambda ch: TOKEN)
    monkeypatch.setattr(store, "get_connection", lambda: None)
    monkeypatch.setattr(store, "Repo", _Repo)
    monkeypatch.setattr(store.httpx, "get", lambda *a, **k: httpx.Response(400, request=req, text="bad"))
    with pytest.raises(store.InstagramTokenError) as ei:
        store.refresh_token(_channel())
    assert TOKEN not in saved["err"] and TOKEN not in str(ei.value)


def _wire_run(monkeypatch, articles_by_genre, process):
    class _Fetcher:
        def __init__(self, *a, **k): pass
        def fetch(self, genre, country, limit, mark_seen): return articles_by_genre.get(genre, [])

    class _Store:
        def mark_seen(self, a): pass

    monkeypatch.setattr(rc, "NewsFetcher", _Fetcher)
    monkeypatch.setattr(rc, "_preflight_token", lambda c: None)
    monkeypatch.setattr(rc, "get_store_for_channel", lambda cid: _Store())
    monkeypatch.setattr(rc, "get_settings", lambda: rc.Settings(database_url=None, newsapi_key=None))
    monkeypatch.setattr(rc, "_process_one", process)


def _ok(article, genre_setting, channel, dry_run, **kw):
    return rc._Outcome(status="success", caption_text="c", hashtags=[], asset_types=["reel"], platform_post_id="p")


def test_rotation_falls_back_to_next_genre_and_posts_once(monkeypatch):
    seen = []

    def process(article, genre_setting, channel, dry_run, **kw):
        seen.append(genre_setting.genre)
        return _ok(article, genre_setting, channel, dry_run)

    # due genre "ai" has nothing new; "tech" must post instead, and only once
    _wire_run(monkeypatch, {"tech": [_art(1, "tech"), _art(2, "tech")]}, process)
    result = rc.run_channel(_channel(), genres_filter=["ai", "tech"], max_posts_per_genre=1, max_posts_total=1)
    assert result.posted == 1 and seen == ["tech"]


def test_genres_filter_order_is_respected(monkeypatch):
    seen = []

    def process(article, genre_setting, channel, dry_run, **kw):
        seen.append(genre_setting.genre)
        return _ok(article, genre_setting, channel, dry_run)

    _wire_run(monkeypatch, {"tech": [_art(1, "tech")], "ai": [_art(1, "ai")]}, process)
    rc.run_channel(_channel(), genres_filter=["ai", "tech"], max_posts_total=1)
    assert seen == ["ai"]


def test_unexpected_posting_error_is_a_failed_attempt_not_a_crash(monkeypatch, tmp_path):
    from tests.test_motion import _brief, _carousel_asset

    asset = _carousel_asset(2)

    class _Pipe:
        def __init__(self, *a, **k): pass
        def analyze(self, url): return object(), _brief()
        def run_from_brief(self, *a, **k): return [asset]

    class _Caption:
        text, hashtags = "cap", ["#x"]

    class _Host:
        def upload(self, *a, **k): raise AssertionError("not reached")
        def delete(self, h): pass

    def jamendo_down(*a, **k):
        raise httpx.HTTPStatusError("503", request=httpx.Request("GET", "https://api.jamendo.com"),
                                    response=httpx.Response(503))

    monkeypatch.setattr(rc, "_build_llm", lambda c: object())
    monkeypatch.setattr(rc, "Pipeline", _Pipe)
    monkeypatch.setattr(rc, "generate_caption", lambda *a, **k: _Caption())
    monkeypatch.setattr(rc, "VercelBlobImageHost", _Host)
    monkeypatch.setattr(rc, "_pick_music_track", jamendo_down)
    out = rc._process_one(_art(1, "tech"), GenreSetting(genre="tech"), _channel(publish_format="reel"), dry_run=False)
    assert out.status == "failed" and "503" in out.error and not out.fatal


def test_run_due_continues_after_a_channel_crashes(monkeypatch, capsys):
    from narovva import cli

    a, b = _channel(id="a"), _channel(id="b")
    ran = []

    def fake_run(channel, **kw):
        ran.append(channel.id)
        if channel.id == "a":
            raise RuntimeError(f"db down access_token={TOKEN}")
        return rc.ChannelRunResult(channel_id=channel.id)

    monkeypatch.setattr(cli, "load_all_channels", lambda d: [a, b])
    monkeypatch.setattr(cli, "due_channels_with_genres", lambda chans: [(a, ["tech"]), (b, ["tech"])])
    monkeypatch.setattr(cli, "run_channel", fake_run)
    assert cli.main(["run-due"]) == 1
    out = capsys.readouterr().out
    assert ran == ["a", "b"] and "channel=a crashed" in out and TOKEN not in out


def test_voice_timing_leaves_room_for_the_transition_and_reaches_the_template(tmp_path):
    from narovva.motion.render import stage_project
    from narovva.motion.slides import SCENE_OVERLAP_SECONDS, VOICE_LEAD, motion_duration

    voice = 2.0
    dur = motion_duration(0, "text", voice)
    # next line starts VOICE_LEAD into the next scene, which begins OV before this one ends
    assert dur - SCENE_OVERLAP_SECONDS + VOICE_LEAD >= VOICE_LEAD + voice
    stage_project(tmp_path, [{"kind": "text", "heading": "h", "duration": dur}], accent="#3B82F6",
                  handle="h", brand="B", logo_path="assets/logo/CU.png", audio_bytes=None)
    assert f'"voice_lead": {VOICE_LEAD}' in (tmp_path / "deck.js").read_text()


def test_a_site_that_refuses_is_skipped_for_the_rest_of_the_run_and_a_post_is_success(monkeypatch, capsys):
    from info_snipe.models import Article

    from narovva import cli

    arts = [Article(content_id=f"c{i}", title=f"t{i}", url=u, source_name="s", genre="tech")
            for i, u in enumerate(["https://www.blocked.example/a", "https://blocked.example/b",
                                   "https://ok.example/c"])]
    tried = []

    def process(article, genre, channel, **kw):
        tried.append(article.url)
        if "blocked" in article.url:
            return rc._Outcome(status="failed", caption_text="", hashtags=[], asset_types=[],
                               error=f"Failed to fetch {article.url}: Client error '403 Forbidden'")
        return rc._Outcome(status="success", caption_text="c", hashtags=[], asset_types=["reel"])

    ch = _channel()
    _wire_run(monkeypatch, {ch.genres[0].genre: list(arts)}, process)
    result = rc.run_channel(ch, max_posts_total=1)
    assert tried == ["https://www.blocked.example/a", "https://ok.example/c"]
    assert result.posted == 1 and result.failed == 1

    monkeypatch.setattr(cli, "load_channel", lambda p: _channel())
    monkeypatch.setattr(cli, "run_channel", lambda *a, **k: rc.ChannelRunResult(channel_id="c", posted=1, failed=1))
    assert cli.main(["run-channel", "x.yaml"]) == 0
    monkeypatch.setattr(cli, "run_channel", lambda *a, **k: rc.ChannelRunResult(channel_id="c", failed=1))
    assert cli.main(["run-channel", "x.yaml"]) == 1
