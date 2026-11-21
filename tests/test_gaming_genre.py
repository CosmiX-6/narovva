from types import SimpleNamespace

import narovva.genres  # noqa: F401  (registers narovva's genres)
from narovva.captions.generator import _build_candidate_hashtags
from narovva.captions.hashtag_pools import pool_for
from narovva.config.loader import load_channel
from narovva.genres import GAMING_FEEDS
from narovva.motion.local_director import _icon_for


def test_gaming_is_registered_with_the_checked_feeds():
    from info_snipe.genres import _GENRES

    g = _GENRES["gaming"]
    assert g.label == "Gaming" and g.rss_feeds == GAMING_FEEDS and len(GAMING_FEEDS) == 11
    assert "esports" in g.newsapi_query and "PlayStation" in g.newsapi_query
    assert not any("gamespot" in f or "gematsu" in f for f in GAMING_FEEDS)     # their articles answer 403


def test_gaming_posts_get_gaming_hashtags_not_tech_ones(monkeypatch):
    monkeypatch.setattr("narovva.captions.generator.trending_for_category", lambda topic: [f"#trend_{topic}"])
    brief = SimpleNamespace(category=SimpleNamespace(value="technology"))
    tags = _build_candidate_hashtags(brief, genre="gaming")
    assert tags[0] == "#trend_gaming" and "#Gaming" in tags and "#PS5" in tags and "#Tech" not in tags
    assert _build_candidate_hashtags(brief, genre="tech")[1] == "#Tech"          # other genres: the category's
    assert pool_for("technology", "gaming")[0] == "#Gaming" and pool_for("health")[0] == "#Health"


def test_consoles_and_platforms_get_a_gamepad():
    assert _icon_for("PlayStation") == "gamepad-2" and _icon_for("Nintendo Switch") == "gamepad-2"


def test_the_example_channel_posts_gaming():
    channel = load_channel("config/channels/example-tech-ig.yaml")
    gaming = [g for g in channel.genres if g.genre == "gaming"]
    assert len(gaming) == 1 and gaming[0].cadence_minutes == 90 and gaming[0].music_tags == ["electronic", "energetic"]
