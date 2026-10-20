from __future__ import annotations

import importlib
from datetime import datetime, timedelta, timezone

from info_snipe.models import Article

from narovva.config import load_channel
from narovva.config.schema import BrandKitConfig, ChannelConfig, FocusConfig, GenreSetting, ViralConfig
from narovva.focus import keep_on_topic, mentions, screen
from narovva.narration.script import write_script
from narovva.viral import editor
from narovva.viral.sources import Headline

rc = importlib.import_module("narovva.orchestration.run_channel")
ov = importlib.import_module("narovva.orchestration.viral")

NOW = datetime.now(timezone.utc)


def _art(title, hours_ago=1, desc="", cid=None):
    return Article(content_id=cid or title, title=title, url=f"https://x.example/{abs(hash(title))}",
                   source_name="src", genre="ai_practitioner", description=desc,
                   published_at=NOW - timedelta(hours=hours_ago))


def _focus(**kw):
    return FocusConfig(enabled=True, name="AI", audience="AI engineers",
                       genres=[GenreSetting(genre="ai_practitioner")], **kw)


def _channel(focus=None, **kw):
    return ChannelConfig(id="chan", genres=[GenreSetting(genre="tech"), GenreSetting(genre="world")],
                         brand=BrandKitConfig(name="CU"), focus=focus, **kw)


class _LLM:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def complete_json(self, system, user):
        self.calls.append((system, user))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def test_focus_replaces_genres_and_caption_while_enabled():
    ch = _channel(_focus(caption_voice="practical", extra_hashtags=["#AI"]))
    assert [g.genre for g in ch.genres] == ["ai_practitioner"]
    assert ch.caption.voice == "practical" and ch.caption.extra_hashtags == ["#AI"]
    assert ch.focus_on and ch.audience == "AI engineers"

    off = _channel(FocusConfig(enabled=False, audience="x", genres=[GenreSetting(genre="ai_practitioner")]))
    assert [g.genre for g in off.genres] == ["tech", "world"] and off.audience == ""


def test_live_channel_config_is_in_ai_focus():
    ch = load_channel("config/channels/example-tech-ig.yaml")
    assert ch.focus_on and [g.genre for g in ch.genres] == ["ai_practitioner"]
    from info_snipe import get_genre

    assert len(get_genre("ai_practitioner").rss_feeds) >= 15


def test_mentions_matches_whole_words():
    assert mentions("New AI tools for coders", ["ai"])
    assert not mentions("He said the rain stopped", ["ai"])
    assert mentions("Fine-tuning made simple", ["fine tuning"])


def test_keep_on_topic_drops_old_offtopic_and_money_stories():
    arts = [
        _art("OpenAI ships a cheaper GPT model for developers"),
        _art("Anthropic raises $5B at a record valuation"),  # money, not usable
        _art("Ukraine rescues soldier with drones"),            # not AI
        _art("Claude gets a new coding agent", hours_ago=100),  # stale
        _art("GitHub ships a feature", desc="Copilot can now review pull requests"),  # AI in summary
    ]
    kept = keep_on_topic(arts, _focus(), now=NOW)
    assert [a.title for a in kept] == ["OpenAI ships a cheaper GPT model for developers", "GitHub ships a feature"]


def test_screen_orders_by_the_model_and_falls_back():
    arts = [_art("a AI"), _art("b AI"), _art("c AI")]
    llm = _LLM({"picks": [3, 1]})
    assert screen(llm, arts, "AI engineers") == [arts[2], arts[0]]
    assert "AI engineers" in llm.calls[0][0]
    assert screen(_LLM({"picks": []}), arts, "x") == []
    assert screen(_LLM(ValueError("bad")), arts, "x") == arts


def test_rotation_posts_only_screened_articles(monkeypatch):
    fetched = [_art("Funding: AI startup raises $1B"), _art("New open-source LLM beats GPT on code"),
               _art("Copilot adds agent mode")]
    processed = []

    class _Fetcher:
        def __init__(self, **kw):
            pass

        def fetch(self, genre, **kw):
            assert genre == "ai_practitioner"
            return list(fetched)

    class _Store:
        def mark_seen(self, a):
            pass

    def process(article, genre, channel, **kw):
        processed.append(article.title)
        return rc._Outcome(status="dry_run", caption_text="", hashtags=[], asset_types=[])

    monkeypatch.setattr(rc, "NewsFetcher", _Fetcher)
    monkeypatch.setattr(rc, "get_store_for_channel", lambda cid: _Store())
    monkeypatch.setattr(rc, "get_settings", lambda: rc.Settings(database_url=None, newsapi_key=None))
    monkeypatch.setattr(rc, "_process_one", process)
    monkeypatch.setattr(rc, "_build_llm", lambda c: _LLM({"picks": [2, 1]}))
    rc.run_channel(_channel(_focus()), dry_run=True)
    # money story dropped by keywords; the screener put Copilot first
    assert processed == ["Copilot adds agent mode", "New open-source LLM beats GPT on code"]


def test_viral_scan_keeps_only_on_topic_stories_in_focus(monkeypatch):
    def h(title, src):
        return Headline(title=title, url=f"https://{src}.example/{abs(hash(title))}", source=src,
                        published_at=NOW - timedelta(minutes=30))

    heads = [h("Storm floods coastal towns overnight", "bbc"), h("Storm floods coastal towns again", "dw"),
             h("Gemini comes to cars with new AI features", "verge"), h("Gemini AI is coming to cars", "ars")]
    monkeypatch.setattr(ov, "fetch_headlines", lambda feeds: heads)
    monkeypatch.setattr(ov, "fetch_trends", lambda geos: [])
    ch = _channel(_focus(), viral=ViralConfig(enabled=True, trends_geos=[]))
    stories = ov.scan(ch, now=NOW)
    assert [s.title for s in stories] == ["Gemini comes to cars with new AI features"]
    assert any("simonwillison" in f for f in ov.viral_feeds(ch))


def test_audience_reaches_editor_hook_and_script():
    from narovva.viral.detect import find_stories

    heads = [Headline(title=t, url=f"https://{src}.example/1", source=src, published_at=NOW - timedelta(minutes=5))
             for t, src in (("Gemini AI comes to cars", "verge"), ("Gemini AI is coming to cars", "ars"))]
    llm = _LLM({"picks": [1]})
    editor.editor_pick(llm, find_stories(heads, [], now=NOW, max_age_minutes=60, min_sources=2),
                       now=NOW, audience="AI engineers")
    assert "audience: AI engineers" in llm.calls[0][0]

    class Brief:
        headline, summary, why_it_matters, key_facts, tone, hook = "H", "S", None, [], "neutral", None

    hook_llm = _LLM({"hooks": ["Your code reviews just got a robot colleague."]})
    editor.write_hook(hook_llm, Brief(), audience="AI engineers")
    assert "Audience: AI engineers" in hook_llm.calls[0][1]

    script_llm = _LLM({"lines": ["one two three", "four five six"]})
    write_script(script_llm, Brief(), [{"kind": "hook", "heading": "x"}, {"kind": "cta"}], brand="CU",
                 audience="AI engineers")
    assert "Audience: AI engineers" in script_llm.calls[0][1]
