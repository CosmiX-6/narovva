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


def test_a_moving_gemini_alias_is_called_on_v1beta():
    pytest.importorskip("google.genai")
    from narovva.llm.fallback import _beta_for_aliases

    class _Client:
        model, _client = "gemini-flash-latest", None

    alias = _Client()
    _beta_for_aliases(alias, "dummy-key")
    assert alias._client._api_client._http_options.api_version == "v1beta"
    pinned = _Client()
    pinned.model = "gemini-3.5-flash-lite"
    _beta_for_aliases(pinned, "dummy-key")
    assert pinned._client is None  # pinned ids keep the SDK's default


def test_the_writer_chain_is_used_where_configured(monkeypatch):
    import sys

    import narovva.orchestration.run_channel  # noqa: F401
    from narovva.config.schema import BrandKitConfig, ChannelConfig, GenreSetting

    rc = sys.modules["narovva.orchestration.run_channel"]
    built = []
    monkeypatch.setattr(rc, "build_llm_chain", lambda specs, keys: built.append(specs) or "WRITER")
    base = dict(id="c", genres=[GenreSetting(genre="ai")], brand=BrandKitConfig(name="X"),
                llm_chain=["gemini:gemini-flash-latest"])
    plain = ChannelConfig(**base)
    assert rc.writer_llm(plain, "BASE", lesson=object()) == "BASE"                  # no writer chain
    lessons_only = ChannelConfig(**base, writer={"chain": ["gemini:gemini-3.1-pro-preview"]})
    assert rc.writer_llm(lessons_only, "BASE", lesson=None) == "BASE"              # a news post
    cache = {}
    assert rc.writer_llm(lessons_only, "BASE", lesson=object(), llm_cache=cache) == "WRITER"
    assert rc.writer_llm(lessons_only, "BASE", lesson=object(), llm_cache=cache) == "WRITER"
    assert built == [["gemini:gemini-3.1-pro-preview", "gemini:gemini-flash-latest"]]  # once, Pro first
    every = ChannelConfig(**base, writer={"chain": ["gemini:gemini-3.1-pro-preview"], "use_for": "all"})
    assert rc.writer_llm(every, "BASE", lesson=None) == "WRITER"


# -- Claude (anthropic:) ---------------------------------------------------------------------------------------------

class _Block:
    def __init__(self, type_, text=""):
        self.type, self.text = type_, text


class _Msg:
    def __init__(self, text, stop="end_turn"):
        self.content = [_Block("thinking"), _Block("text", text)]
        self.stop_reason, self.stop_details = stop, None


class _Stream:
    def __init__(self, msg):
        self.msg = msg

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.msg


class _Claude:
    def __init__(self, msg):
        self.msg, self.kwargs = msg, None
        self.messages = self

    def stream(self, **kwargs):
        self.kwargs = kwargs
        return _Stream(self.msg)


def test_claude_returns_the_json_and_caches_the_system_prompt():
    from narovva.llm.fallback import AnthropicChat

    fake = _Claude(_Msg('{"beats": [1, 2]}'))
    chat = AnthropicChat("claude-sonnet-5-5", "k", client=fake)
    assert chat.complete_json("SYSTEM", "USER") == {"beats": [1, 2]}
    assert fake.kwargs["model"] == "claude-sonnet-5-5"
    assert fake.kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert fake.kwargs["system"][0]["text"].startswith("SYSTEM")
    assert fake.kwargs["messages"] == [{"role": "user", "content": "USER"}]
    assert fake.kwargs["output_config"] == {"effort": "medium"}


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_claude_refusal_or_cut_off_reply_goes_to_the_next_model(stop):
    from narovva.llm.fallback import AnthropicChat

    claude = AnthropicChat("claude-sonnet-5-5", "k", client=_Claude(_Msg('{"a": 1', stop)))
    backup = _Fake({"ok": True})
    chain = FallbackLLM([_Entry("claude", claude), _Entry("free", backup)], sleep=lambda s: None)
    assert chain.complete_json("s", "u") == {"ok": True}


def test_claude_overload_and_empty_balance_are_classified():
    assert classify_error(_Err("Overloaded", 529)) == "overload"
    assert classify_error(_Err("Your credit balance is too low to access the Anthropic API.", 400)) == "quota"


def test_claude_goes_first_when_its_key_is_set():
    chain = build_llm_chain(["anthropic:claude-sonnet-5-5", "openai:gpt-4o-mini"], {"anthropic": "k", "openai": "k"})
    assert [e.name for e in chain.entries] == ["anthropic:claude-sonnet-5-5", "openai:gpt-4o-mini"]
    assert chain.entries[0].client.model == "claude-sonnet-5-5"
    no_key = build_llm_chain(["anthropic:claude-sonnet-5-5", "openai:gpt-4o-mini"], {"openai": "k"})
    assert [e.name for e in no_key.entries] == ["openai:gpt-4o-mini"]


def test_channel_passes_the_anthropic_key(monkeypatch):
    from narovva.config.loader import load_channel

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    channel = load_channel("config/channels/example-tech-ig.yaml")
    assert "anthropic:claude-sonnet-5-5" in channel.llm_chain[:2]
    assert rc._llm_keys(channel)["anthropic"] == "sk-test"


# -- Claude on a claude.ai plan (claude-code:) -----------------------------------------------------------------------

class _Proc:
    def __init__(self, out, code=0, err=""):
        self.stdout, self.returncode, self.stderr = out, code, err


def _cli(reply: dict | str, code=0):
    import json as _json

    calls = []

    def run(cmd, **kw):
        sys_file = cmd[cmd.index("--system-prompt-file") + 1]
        with open(sys_file, encoding="utf-8") as f:
            calls.append({"cmd": cmd, "system": f.read(), **kw})
        return _Proc(reply if isinstance(reply, str) else _json.dumps(reply), code)

    return run, calls


def _cc(run):
    from narovva.llm.fallback import ClaudeCodeChat

    return ClaudeCodeChat("claude-sonnet-5-5", "oauth-token", binary="claude", run=run)


def test_claude_code_runs_headless_with_no_tools_on_the_plan(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "would-bill-the-api")
    run, calls = _cli({"type": "result", "is_error": False, "stop_reason": "end_turn", "result": '{"ok": 1}'})
    assert _cc(run).complete_json("SYSTEM", "USER") == {"ok": 1}
    call = calls[0]
    cmd = call["cmd"]
    assert cmd[:4] == ["claude", "-p", "--output-format", "json"]
    assert cmd[cmd.index("--model") + 1] == "claude-sonnet-5-5"
    assert cmd[cmd.index("--tools") + 1] == ""
    assert {"--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands"} <= set(cmd)
    assert call["system"].startswith("SYSTEM") and call["input"] == "USER"
    assert call["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-token"
    assert "ANTHROPIC_API_KEY" not in call["env"]        # it would win over the token and bill the API


def test_claude_code_usage_limit_hands_over_to_the_next_model():
    run, _ = _cli({"type": "result", "is_error": True, "api_error_status": 429,
                   "result": "Claude AI usage limit reached|1764000000"}, code=1)
    plan, backup = _cc(run), _Fake({"ok": True})
    chain = FallbackLLM([_Entry("plan", plan), _Entry("free", backup)], sleep=lambda s: None)
    assert chain.complete_json("s", "u") == {"ok": True}
    assert chain.entries[0].dead_reason.startswith("quota")   # not asked again this run
    assert classify_error(_Err("claude CLI: You've hit your limit · resets 3pm")) == "quota"


def test_claude_code_expired_token_and_broken_output():
    run, _ = _cli({"type": "result", "is_error": True, "api_error_status": 401,
                   "result": "OAuth token has expired. Please run /login"}, code=1)
    with pytest.raises(Exception) as exc:
        _cc(run).complete_json("s", "u")
    assert classify_error(exc.value) == "auth"
    run, _ = _cli("Segmentation fault", code=139)
    with pytest.raises(Exception, match="exit 139"):
        _cc(run).complete_json("s", "u")


def test_claude_code_without_the_cli_is_left_out(monkeypatch):
    monkeypatch.delenv("CLAUDE_BIN", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    chain = build_llm_chain(["claude-code:claude-sonnet-5-5", "openai:gpt-4o-mini"],
                            {"claude-code": "t", "openai": "k"})
    assert [e.name for e in chain.entries] == ["openai:gpt-4o-mini"]


def test_channel_puts_the_plan_first(monkeypatch):
    from narovva.config.loader import load_channel

    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "t")
    channel = load_channel("config/channels/example-tech-ig.yaml")
    assert channel.llm_chain[:2] == ["claude-code:claude-sonnet-5-5", "anthropic:claude-sonnet-5-5"]
    assert rc._llm_keys(channel)["claude-code"] == "t"
