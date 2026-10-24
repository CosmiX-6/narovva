from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from narovva.config.schema import BrandKitConfig, ChannelConfig, GenreSetting, ViralConfig
from narovva.narration.script import write_script
import importlib

rc = importlib.import_module("narovva.orchestration.run_channel")
from narovva.orchestration import viral as ov
from narovva.viral import editor
from narovva.viral.detect import find_stories, same_story, tokens
from narovva.viral.schedule import slot_status
from narovva.viral.sources import Headline, Trend, parse_traffic, parse_trends

NOW = datetime(2026, 10, 17, 14, 0, tzinfo=timezone.utc)  # 19:30 IST


def _h(title, source, minutes_ago=30, url=None):
    return Headline(title=title, url=url or f"https://{source}.example/{abs(hash(title)) % 10**8}",
                    source=source, published_at=NOW - timedelta(minutes=minutes_ago))


def _channel(**viral) -> ChannelConfig:
    return ChannelConfig(
        id="chan", genres=[GenreSetting(genre="tech")], brand=BrandKitConfig(name="CU"),
        viral=ViralConfig(enabled=True, timezone="Asia/Kolkata", trends_geos=[], **viral),
    )


# -- sources ---------------------------------------------------------------

def test_parse_traffic():
    assert parse_traffic("20,000+") == 20000
    assert parse_traffic("2K+") == 2000
    assert parse_traffic("1M+") == 1_000_000
    assert parse_traffic("") == 0


def test_parse_trends_reads_traffic_time_and_news():
    raw = b"""<?xml version="1.0"?><rss xmlns:ht="https://trends.google.com/trending/rss"><channel>
    <item><title>chip ban</title><ht:approx_traffic>50000+</ht:approx_traffic>
    <pubDate>Sat, 17 Oct 2026 06:30:00 -0700</pubDate>
    <ht:news_item><ht:news_item_title>US widens chip export ban</ht:news_item_title>
    <ht:news_item_url>https://x.example/a</ht:news_item_url><ht:news_item_source>X</ht:news_item_source></ht:news_item>
    </item></channel></rss>"""
    [t] = parse_trends(raw, "US")
    assert t.query == "chip ban" and t.traffic == 50000
    assert t.started_at == datetime(2026, 10, 17, 13, 30, tzinfo=timezone.utc)
    assert t.news[0].title == "US widens chip export ban" and t.news[0].source == "X"


# -- detection -------------------------------------------------------------

def test_same_story_matches_rewordings_not_neighbours():
    a = tokens("Israeli settlers attack European diplomats in West Bank")
    b = tokens("EU diplomats say they were attacked by settlers in West Bank")
    c = tokens("Bank of England holds interest rates")
    assert same_story(a, b)
    assert not same_story(a, c)


def test_story_needs_several_outlets_and_freshness():
    heads = [
        _h("Nvidia unveils new AI chip for phones", "bbc"),
        _h("Nvidia's new AI chip targets phones", "verge"),
        _h("Nvidia unveils AI chip for phones", "bbc", url="https://bbc.example/dupe"),  # same outlet
        _h("Local bakery wins award", "cbs"),                                      # one outlet only
        _h("Old news about volcano eruption today", "bbc", minutes_ago=600),
        _h("Volcano eruption today grounds flights", "dw", minutes_ago=500),
    ]
    stories = find_stories(heads, [], now=NOW, max_age_minutes=240, min_sources=2)
    assert len(stories) == 1
    assert "Nvidia" in stories[0].title and len(stories[0].sources) == 2


def test_trends_alone_do_not_make_a_story_viral_but_boost_one():
    trend = Trend(query="nvidia chip", traffic=100000, started_at=NOW, geo="US", news=[
        _h("Nvidia chip news one", "espn"), _h("Nvidia chip news two", "yahoo"),
    ])
    sports = Trend(query="jalen hurts", traffic=200000, started_at=NOW, geo="US", news=[
        _h("Jalen Hurts placed on injured reserve", "espn"),
        _h("Jalen Hurts out indefinitely with injury", "nbc"),
    ])
    heads = [
        _h("Nvidia unveils new chip for phones", "bbc"), _h("Nvidia's new chip targets phones", "verge"),
        _h("Storm floods coastal towns overnight", "bbc"), _h("Storm floods coastal towns, thousands evacuated", "dw"),
        _h("Storm floods towns along coast", "cbs"),
    ]
    stories = find_stories(heads, [trend, sports], now=NOW, max_age_minutes=240, min_sources=2)
    titles = [s.title for s in stories]
    assert not any("Jalen" in t for t in titles)  # Google Trends' own links count as one source
    nvidia = next(s for s in stories if "Nvidia" in s.title)
    assert nvidia.trend is trend and nvidia.score > 0


def test_exclusions_and_recent_posts_are_skipped():
    heads = [
        _h("Arsenal vs Chelsea: score and highlights", "bbc"), _h("Arsenal vs Chelsea score", "sky"),
        _h("Apple delays its AI glasses to 2027", "bbc"), _h("Apple AI glasses delayed to 2027", "verge"),
    ]
    stories = find_stories(heads, [], now=NOW, max_age_minutes=240, min_sources=2,
                           exclude_keywords=["vs", "score"], skip_titles=["Apple delays AI glasses until 2027"])
    assert stories == []


def test_one_word_trend_does_not_match_on_words():
    trend = Trend(query="the diplomat", traffic=5000, started_at=NOW, geo="US", news=[])
    heads = [_h("EU diplomats attacked in West Bank", "bbc"), _h("European diplomats attacked in West Bank", "dw")]
    [story] = find_stories(heads, [trend], now=NOW, max_age_minutes=240, min_sources=2)
    assert story.trend is None


# -- schedule --------------------------------------------------------------

@pytest.mark.parametrize("utc, posted, due", [
    ("03:00", 0, False),  # 08:30 IST: before the first slot
    ("03:45", 0, True),   # 09:15 IST: slot 09:00 open
    ("04:30", 1, False),  # 10:00 IST: slot filled
    ("06:00", 0, False),  # 11:30 IST: 09:00 window over, 13:00 not yet
    ("07:45", 0, True),   # 13:15 IST: 13:00 open; 09:00 was missed -> 0 < 2
    ("08:45", 1, True),   # 14:15 IST: the missed slot is made up in this window
    ("08:50", 2, False),  # caught up
    ("16:10", 3, True),   # 21:40 IST: last slot
])
def test_slot_status(utc, posted, due):
    hh, mm = map(int, utc.split(":"))
    now = datetime(2026, 10, 17, hh, mm, tzinfo=timezone.utc)
    assert slot_status(_channel().viral, now, posted)[0] is due


def test_viral_not_due_right_after_another_post():
    class Repo:
        def count_successful_posts_since(self, *a):
            return 0

        def last_post_at(self, cid):
            return NOW - timedelta(minutes=10)

    due, why = ov.viral_due(_channel(), NOW, Repo())
    assert not due and "10 min ago" in why


def test_config_rejects_bad_slot_and_timezone():
    with pytest.raises(ValueError):
        ViralConfig(slots=["25:00"])
    with pytest.raises(ValueError):
        ViralConfig(timezone="Mars/Base")
    assert ViralConfig(slots=["21:30", "9:00"]).slots == ["09:00", "21:30"]


# -- editor + hook ---------------------------------------------------------

class _LLM:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def complete_json(self, system, user):
        self.calls.append(user)
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def _stories():
    titles = ["Story one: volcano erupts near Naples", "Story two: central bank cuts rates",
              "Story three: satellite lands on asteroid"]
    heads = [_h(t, s, minutes_ago=30 + 20 * i) for i, t in enumerate(titles) for s in ("bbc", "dw")]
    return find_stories(heads, [], now=NOW, max_age_minutes=240, min_sources=2)


def test_editor_follows_the_model_and_falls_back_on_bad_output():
    stories = _stories()
    assert len(stories) == 3
    picked = editor.editor_pick(_LLM({"picks": [3, "1", 99]}), stories, now=NOW)
    assert picked == [stories[2], stories[0]]
    assert editor.editor_pick(_LLM({"picks": []}), stories, now=NOW) == []
    assert editor.editor_pick(_LLM(ValueError("bad json")), stories, now=NOW) == stories[:3]


def test_editor_lets_a_dead_model_chain_stop_the_run():
    from narovva.llm import LLMUnavailable

    with pytest.raises(LLMUnavailable):
        editor.editor_pick(_LLM(LLMUnavailable("none left")), _stories(), now=NOW)


@pytest.mark.parametrize("text, ok", [
    ("Your next phone may cost more", True),
    ("Why did the EU lose patience?", True),
    ("You won't believe what Apple did", False),
    ("Too short", False),
    ("This is a very long hook that goes on and on and never stops talking", False),
    ("Apple delays its AI glasses", False),  # the headline itself
    ("SHOCKING NEWS ABOUT APPLE TODAY", False),
])
def test_clean_hook(text, ok):
    assert (editor.clean_hook(text, "Apple delays its AI glasses") is not None) is ok


def test_write_hook_falls_back_to_the_briefs_hook():
    class Brief:
        headline, summary, why_it_matters, key_facts, tone = "H", "S", None, ["f"], "neutral"
        hook = "What changes for your bills next month?"

    assert editor.write_hook(_LLM({"hook": "SHOCKING!!"}), Brief()) == "What changes for your bills next month?"
    assert editor.write_hook(_LLM({"hook": "The rules on your data just changed"}), Brief()) == \
        "The rules on your data just changed."


def test_spoken_spells_short_acronyms():
    assert editor.spoken("Why AI chips cost more in the US") == "Why A I chips cost more in the U S"


def test_hook_opens_the_reel_and_is_spoken_first():
    specs = [{"kind": "hook", "kicker": "AI", "heading": "Old headline"}, {"kind": "stats", "heading": "x"}]
    out = rc.apply_hook(specs, "Your data is the price.", "Old headline")
    assert out[0]["heading"] == "Your data is the price." and out[0]["kicker"] == "TRENDING NOW"
    assert out[0]["body"] == "Old headline" and out[1]["heading"] == "x"
    assert rc.apply_hook([{"kind": "stats"}], "Hook here now.", "h") == [{"kind": "stats"}]

    class Brief:
        tone, headline, summary = "neutral", "H", "S"

    lines = write_script(_LLM({"lines": ["model hook", "line two words here"]}), Brief(), specs, brand="CU",
                         hook="Your data is the price.")
    assert lines.lines[0] == "Your data is the price." and lines.screen[0] == "Your data is the price."


# -- the viral run ---------------------------------------------------------

class _Store:
    def __init__(self):
        self.seen = set()

    def filter_unseen(self, ids):
        return {i for i in ids if i not in self.seen}

    def mark_seen(self, article):
        self.seen.add(article.content_id)


def _patch_run(monkeypatch, outcomes, stories=None):
    store, calls = _Store(), []
    monkeypatch.setattr(ov, "get_settings", lambda: rc.Settings(database_url=None, newsapi_key=None))
    monkeypatch.setattr(ov, "_open_repo", lambda s: None)
    monkeypatch.setattr(ov, "_preflight_token", lambda c: None)
    monkeypatch.setattr(ov, "_build_llm", lambda c: _LLM({"picks": [1, 2]}))
    monkeypatch.setattr(ov, "get_store_for_channel", lambda cid: store)
    monkeypatch.setattr(ov, "scan", lambda channel, **kw: stories if stories is not None else _stories())

    def process(article, genre, channel, **kw):
        calls.append((article, genre, kw))
        return outcomes.pop(0)

    monkeypatch.setattr(ov, "_process_one", process)
    return store, calls


def _ok():
    return rc._Outcome(status="success", caption_text="c", hashtags=[], asset_types=["reel"], platform_post_id="1")


def _bad():
    return rc._Outcome(status="failed", caption_text="", hashtags=[], asset_types=[], error="403 Forbidden")


def test_forced_viral_run_posts_once_with_a_hook_and_marks_every_copy_seen(monkeypatch):
    store, calls = _patch_run(monkeypatch, [_ok()])
    result = ov.run_viral(_channel(), force=True)
    assert result.posted == 1 and result.failed == 0
    article, genre, kw = calls[0]
    assert genre.genre == "viral" and kw["hook_style"] == "auto" and article.genre == "viral"
    assert len(store.seen) == 2  # both outlets' links to the story


def test_a_blocked_page_tries_another_outlet_then_the_next_story(monkeypatch):
    _, calls = _patch_run(monkeypatch, [_bad(), _bad(), _ok()])
    result = ov.run_viral(_channel(), force=True)
    assert result.posted == 1 and result.failed == 2
    assert calls[0][0].title != calls[1][0].title or calls[0][0].url != calls[1][0].url
    assert calls[2][0].title.startswith("Story two")  # second pick after both copies of the first failed


def test_viral_run_waits_outside_its_slots(monkeypatch):
    _, calls = _patch_run(monkeypatch, [])
    monkeypatch.setattr(ov, "viral_due", lambda c, now, repo: (False, "outside peak windows"))
    result = ov.run_viral(_channel())
    assert calls == [] and result.considered == 0


def test_run_due_posts_viral_first_and_holds_the_rotation(monkeypatch, capsys):
    from narovva import cli

    ch = _channel()
    monkeypatch.setattr(cli, "load_all_channels", lambda d: [ch])
    monkeypatch.setattr(cli, "due_channels_with_genres", lambda chans: [(ch, ["tech"])])
    monkeypatch.setattr(ov, "run_viral", lambda c, **kw: rc.ChannelRunResult(channel_id=c.id, considered=1, posted=1))
    monkeypatch.setattr(cli, "run_channel", lambda *a, **k: pytest.fail("rotation must wait for the next run"))
    assert cli.main(["run-due"]) == 0
    assert "rotation waits" in capsys.readouterr().out


def test_run_due_runs_rotation_when_no_viral_slot(monkeypatch):
    from narovva import cli

    ch, ran = _channel(), []
    monkeypatch.setattr(cli, "load_all_channels", lambda d: [ch])
    monkeypatch.setattr(cli, "due_channels_with_genres", lambda chans: [(ch, ["tech"])])
    monkeypatch.setattr(ov, "run_viral", lambda c, **kw: rc.ChannelRunResult(channel_id=c.id))
    monkeypatch.setattr(cli, "run_channel", lambda c, **k: ran.append(c.id) or rc.ChannelRunResult(channel_id=c.id))
    assert cli.main(["run-due"]) == 0 and ran == ["chan"]


def test_a_hook_that_restates_the_headline_is_rejected_and_retried():
    class Brief:
        headline = "Israeli settlers attack European diplomats in West Bank"
        summary, why_it_matters, key_facts, tone, hook = "S", None, [], "serious", None

    llm = _LLM(
        {"hooks": ["European diplomats face violent assault in the West Bank."]},
        {"hooks": ["European diplomats attacked in West Bank.", "Who attacks diplomats and walks away?"]},
    )
    assert editor.write_hook(llm, Brief()) == "Who attacks diplomats and walks away?"
    assert len(llm.calls) == 2 and "only described the event" in llm.calls[1]
