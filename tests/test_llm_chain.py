import sys

import pytest

import narovva.orchestration  # noqa: F401
from narovva.llm import FallbackLLM, LLMUnavailable, build_llm_chain, classify_error
from narovva.llm.fallback import _Entry, retry_delay_seconds

rc = sys.modules["narovva.orchestration.run_channel"]


class _Fake:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def complete_json(self, system, user):
        self.calls += 1
        out = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        if isinstance(out, Exception):
            raise out
        return out


class _Err(RuntimeError):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status_code = status


QUOTA = _Err("429 RESOURCE_EXHAUSTED. You exceeded your current quota. Please retry in 20h59m46.6s", 429)
BUSY = _Err("503 UNAVAILABLE. This model is currently experiencing high demand.", 503)


def _chain(*clients):
    return FallbackLLM([_Entry(f"m{i}", c) for i, c in enumerate(clients)], sleep=lambda s: None)


def test_classify_and_retry_delay():
    assert classify_error(QUOTA) == "quota" and classify_error(BUSY) == "overload"
    assert classify_error(_Err("invalid api key", 401)) == "auth"
    assert classify_error(ValueError("Invalid JSON from LLM")) == "bad_output"
    assert retry_delay_seconds(QUOTA) == pytest.approx(20 * 3600 + 59 * 60 + 46.6)
    assert retry_delay_seconds(_Err("retryDelay': '75586s'")) == 75586


GONE = _Err("404 NOT_FOUND. This model models/gemini-2.5-flash is no longer available to new users.", 404)


def test_retired_model_is_skipped_for_the_rest_of_the_run():
    assert classify_error(GONE) == "gone"
    a, b = _Fake(GONE), _Fake({"ok": 1})
    llm = _chain(a, b)
    assert llm.complete_json("s", "u") == {"ok": 1} and llm.complete_json("s", "u") == {"ok": 1}
    assert a.calls == 1


def test_quota_falls_through_and_the_spent_model_is_skipped_afterwards():
    a, b = _Fake(QUOTA), _Fake({"ok": 1})
    llm = _chain(a, b)
    assert llm.complete_json("s", "u") == {"ok": 1}
    assert llm.complete_json("s", "u") == {"ok": 1}
    assert a.calls == 1 and b.calls == 2          # tried once, then never again


def test_overload_is_retried_once_then_next_model_and_recovers_after_cooldown():
    now = [0.0]
    a, b = _Fake(BUSY, BUSY, {"a": 1}), _Fake({"b": 1})
    llm = FallbackLLM([_Entry("a", a), _Entry("b", b)], sleep=lambda s: None, clock=lambda: now[0])
    assert llm.complete_json("s", "u") == {"b": 1} and a.calls == 2
    assert llm.complete_json("s", "u") == {"b": 1} and a.calls == 2   # cooling down
    now[0] = 500.0
    assert llm.complete_json("s", "u") == {"a": 1}                    # tried again later


def test_short_rate_limit_is_waited_out_on_the_same_model():
    waits = []
    a = _Fake(_Err("429 rate limit. Please retry in 7s", 429), {"ok": 1})
    llm = FallbackLLM([_Entry("a", a)], sleep=waits.append)
    assert llm.complete_json("s", "u") == {"ok": 1} and waits and waits[0] < 10


def test_bad_output_moves_on_without_killing_the_model():
    a, b = _Fake(ValueError("Invalid JSON from LLM"), {"a": 2}), _Fake({"b": 1})
    llm = _chain(a, b)
    assert llm.complete_json("s", "u") == {"b": 1}
    assert llm.complete_json("s", "u") == {"a": 2}


def test_all_models_failing_raises_llm_unavailable():
    llm = _chain(_Fake(QUOTA), _Fake(BUSY, BUSY))
    with pytest.raises(LLMUnavailable, match="m0: quota; m1: overload"):
        llm.complete_json("s", "u")
    with pytest.raises(LLMUnavailable):      # and stays down without calling anything again
        llm.complete_json("s", "u")


def test_build_skips_entries_without_keys_and_errors_when_none_left(monkeypatch):
    import narovva.llm.fallback as fb

    monkeypatch.setattr(fb, "GeminiChat", lambda **kw: ("gemini", kw))
    llm = build_llm_chain(
        ["gemini:g1", "openrouter:x:free", "openai"], {"gemini": "k", "openrouter": None, "openai": ""},
    )
    assert [e.name for e in llm.entries] == ["gemini:g1"]
    with pytest.raises(LLMUnavailable, match="no text model is configured"):
        build_llm_chain(["openrouter:x:free"], {})


def test_openrouter_client_parses_json_and_surfaces_errors(monkeypatch):
    import narovva.llm.fallback as fb

    class _Resp:
        def __init__(self, status, payload, text=""):
            self.status_code, self._p, self.text, self.headers = status, payload, text, {}

        def json(self):
            return self._p

    ok = _Resp(200, {"choices": [{"message": {"content": '```json\n{"a": 1}\n```'}}]})
    monkeypatch.setattr(fb.httpx, "post", lambda *a, **k: ok)
    assert fb.OpenRouterChat("m:free", "k").complete_json("s", "u") == {"a": 1}
    monkeypatch.setattr(fb.httpx, "post", lambda *a, **k: _Resp(429, {}, "rate limited"))
    with pytest.raises(Exception) as ei:
        fb.OpenRouterChat("m:free", "k").complete_json("s", "u")
    assert classify_error(ei.value) == "quota"


def test_run_stops_without_burning_attempts_when_no_text_model_is_left(monkeypatch):
    from info_snipe.models import Article as FeedArticle

    from narovva.config.schema import BrandKitConfig, ChannelConfig, GenreSetting

    calls = []
    articles = [
        FeedArticle(content_id=f"c{i}", title="t", url=f"https://e.com/{i}", source_name="e", genre="tech")
        for i in range(3)
    ]

    class _Fetcher:
        def __init__(self, *a, **k): pass
        def fetch(self, genre, country, limit, mark_seen): return articles

    class _Store:
        def mark_seen(self, article): pass

    monkeypatch.setattr(rc, "NewsFetcher", _Fetcher)
    monkeypatch.setattr(rc, "_preflight_token", lambda channel: None)
    monkeypatch.setattr(rc, "get_store_for_channel", lambda cid: _Store())
    monkeypatch.setattr(rc, "get_settings", lambda: rc.Settings(database_url=None, newsapi_key=None))

    def process(article, genre_setting, channel, dry_run, **kw):
        calls.append(article)
        return rc._Outcome(status="failed", caption_text="", hashtags=[], asset_types=[],
                           error="no text model available (m0: quota)", fatal=True)

    monkeypatch.setattr(rc, "_process_one", process)
    channel = ChannelConfig(id="c", platform="instagram", ig_business_account_id="1",
                            genres=[GenreSetting(genre="tech", limit=5)], brand=BrandKitConfig(name="T"))
    result = rc.run_channel(channel)
    assert len(calls) == 1 and result.failed == 1 and result.posted == 0
