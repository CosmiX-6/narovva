from __future__ import annotations

import sys

from info_snipe.models import Article as FeedArticle

from narovva.config.schema import BrandKitConfig, ChannelConfig, GenreSetting

import narovva.orchestration.run_channel  # noqa: F401 -- registers the submodule in sys.modules

# The orchestration package re-exports a `run_channel` *function* under the
# same name as this submodule, which shadows `narovva.orchestration.run_channel`
# as an attribute lookup. Go through sys.modules to get the actual module.
run_channel_module = sys.modules["narovva.orchestration.run_channel"]


def _channel(**overrides) -> ChannelConfig:
    defaults = dict(
        id="test-channel",
        platform="instagram",
        ig_business_account_id="123",
        genres=[GenreSetting(genre="tech")],
        brand=BrandKitConfig(name="Test"),
    )
    defaults.update(overrides)
    return ChannelConfig(**defaults)


def _article() -> FeedArticle:
    return FeedArticle(
        content_id="abc123", title="A story", url="https://example.com/a",
        source_name="Example", genre="tech",
    )


def test_process_one_returns_failed_outcome_instead_of_raising(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("simulated LLM outage")

    monkeypatch.setattr(run_channel_module, "_build_llm", _boom)

    outcome = run_channel_module._process_one(
        _article(), GenreSetting(genre="tech"), _channel(), dry_run=False,
    )

    assert outcome.status == "failed"
    assert "simulated LLM outage" in outcome.error


def test_process_one_failure_in_render_is_caught(monkeypatch):
    class _FakeLLM:
        def complete_json(self, system, user):
            return {}

    monkeypatch.setattr(run_channel_module, "_build_llm", lambda channel: _FakeLLM())

    class _FakePipeline:
        def __init__(self, *args, **kwargs):
            pass

        def analyze(self, source):
            raise Exception("bad article extraction")

    monkeypatch.setattr(run_channel_module, "Pipeline", _FakePipeline)

    outcome = run_channel_module._process_one(
        _article(), GenreSetting(genre="tech"), _channel(), dry_run=True,
    )

    assert outcome.status == "failed"
    assert "bad article extraction" in outcome.error


def test_max_posts_per_genre_caps_publishes_within_one_run(monkeypatch):
    articles = [
        FeedArticle(
            content_id=f"id-{i}", title=f"Story {i}", url=f"https://example.com/{i}",
            source_name="Example", genre="tech",
        )
        for i in range(5)
    ]

    class _FakeFetcher:
        def __init__(self, *args, **kwargs):
            pass

        def fetch(self, genre, country, limit, mark_seen):
            return articles

    class _FakeStore:
        def mark_seen(self, article):
            pass

    monkeypatch.setattr(run_channel_module, "NewsFetcher", _FakeFetcher)
    monkeypatch.setattr(run_channel_module, "get_store_for_channel", lambda channel_id: _FakeStore())
    monkeypatch.setattr(
        run_channel_module, "get_settings",
        lambda: run_channel_module.Settings(database_url=None, newsapi_key=None),
    )
    monkeypatch.setattr(
        run_channel_module,
        "_process_one",
        lambda article, genre_setting, channel, dry_run: run_channel_module._Outcome(
            status="success", caption_text="caption", hashtags=[], asset_types=["cover"],
            platform_post_id="fake-id",
        ),
    )

    result = run_channel_module.run_channel(
        _channel(genres=[GenreSetting(genre="tech", limit=5)]),
        max_posts_per_genre=1,
    )

    assert result.posted == 1
    assert result.considered == 1
