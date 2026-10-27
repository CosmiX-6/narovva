from __future__ import annotations

import psycopg
import pytest

from narovva.db import engine as engine_module
from narovva.dedup import store as store_module


class _FakeConn:
    def __init__(self, fail_first: bool):
        self.fail_first, self.calls, self.closed = fail_first, 0, False

    def execute(self, sql, params=None):
        self.calls += 1
        if self.fail_first:
            raise psycopg.OperationalError("SSL connection has been closed unexpectedly")
        return f"ok:{sql}"

    def close(self):
        self.closed = True


def test_resilient_connection_reconnects_once_and_retries(monkeypatch):
    conns = [_FakeConn(fail_first=True), _FakeConn(fail_first=False)]
    monkeypatch.setattr(engine_module, "_connect", lambda url: conns.pop(0))
    conn = engine_module.ResilientConnection("postgres://x")
    assert conn.execute("SELECT 1") == "ok:SELECT 1"
    assert not conns  # second connection was used


def test_resilient_connection_gives_up_if_reconnect_also_fails(monkeypatch):
    monkeypatch.setattr(engine_module, "_connect", lambda url: _FakeConn(fail_first=True))
    conn = engine_module.ResilientConnection("postgres://x")
    with pytest.raises(psycopg.OperationalError):
        conn.execute("SELECT 1")


def test_resilient_connection_does_not_swallow_other_errors(monkeypatch):
    class Boom(_FakeConn):
        def execute(self, sql, params=None):
            raise psycopg.errors.UniqueViolation("dup")

    monkeypatch.setattr(engine_module, "_connect", lambda url: Boom(False))
    with pytest.raises(psycopg.errors.UniqueViolation):
        engine_module.ResilientConnection("postgres://x").execute("INSERT")


def test_resilient_store_rebuilds_and_retries_mark_seen(monkeypatch):
    built = []

    class FakeStore:
        def __init__(self, dsn, namespace=""):
            self.n = len(built)
            built.append(self)

        def mark_seen(self, article):
            if self.n == 0:
                raise psycopg.OperationalError("the connection is closed")
            return f"marked-by-store-{self.n}"

        marker = "attr"

    monkeypatch.setattr(store_module, "PostgresContentStore", FakeStore)
    store = store_module.ResilientPostgresStore("postgres://x", namespace="chan")
    assert store.mark_seen(object()) == "marked-by-store-1"
    assert len(built) == 2 and store.marker == "attr"


# --- Instagram token preflight / refresh CLI -------------------------------

import httpx  # noqa: E402

from narovva.tokens import InstagramTokenError, check_token  # noqa: E402
from narovva.tokens import instagram_token_store as token_module  # noqa: E402


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.text = status, body, str(body)

    def json(self):
        return self._body


def test_check_token_ok(monkeypatch):
    monkeypatch.setattr(token_module.httpx, "get", lambda *a, **k: _Resp(200, {"id": "1"}))
    check_token("t")


def test_check_token_surfaces_instagram_message(monkeypatch):
    body = {"error": {"message": "Error validating access token: Session has expired", "code": 190}}
    monkeypatch.setattr(token_module.httpx, "get", lambda *a, **k: _Resp(400, body))
    with pytest.raises(InstagramTokenError, match="Session has expired"):
        check_token("t")


def test_check_token_ignores_network_errors(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(token_module.httpx, "get", boom)
    check_token("t")  # not proof the token is bad -> don't block the run


def _token_sources(monkeypatch, *, stored, env, rejected=()):
    """Wire get_valid_token to a stored token, an env token and a fake Instagram."""
    from narovva.config.schema import BrandKitConfig, ChannelConfig, GenreSetting

    calls = []

    def fake_get(url, params, **k):
        calls.append(params["access_token"])
        if params["access_token"] in rejected:
            return _Resp(400, {"error": {"message": "Error validating access token", "code": 190}})
        return _Resp(200, {"id": "1"})

    token_module._chosen.clear()
    monkeypatch.setattr(token_module, "_stored_token", lambda ch: stored)
    if env:
        monkeypatch.setenv("IG_TEST_TOKEN", env)
    else:
        monkeypatch.delenv("IG_TEST_TOKEN", raising=False)
    monkeypatch.setattr(token_module.httpx, "get", fake_get)
    channel = ChannelConfig(id="c", ig_business_account_id="1", genres=[GenreSetting(genre="tech")],
                            brand=BrandKitConfig(name="B"),
                            credentials={"instagram_access_token_env": "IG_TEST_TOKEN"})
    return channel, calls


def test_stored_token_is_preferred_when_instagram_accepts_it(monkeypatch):
    channel, calls = _token_sources(monkeypatch, stored="stored", env="seed")
    assert token_module.get_valid_token(channel) == "stored"
    assert token_module.get_valid_token(channel) == "stored" and calls == ["stored"]  # asked once


def test_env_token_replaces_a_revoked_stored_token(monkeypatch):
    # The fix after a leak: revoke, paste a new token into the secret, nothing else.
    channel, _ = _token_sources(monkeypatch, stored="revoked", env="fresh", rejected={"revoked"})
    assert token_module.get_valid_token(channel) == "fresh"


def test_stored_token_kept_when_both_are_rejected(monkeypatch):
    channel, _ = _token_sources(monkeypatch, stored="old", env="older", rejected={"old", "older"})
    assert token_module.get_valid_token(channel) == "old"  # the preflight reports Instagram's own error


def test_single_token_source_needs_no_network(monkeypatch):
    channel, calls = _token_sources(monkeypatch, stored=None, env="seed")
    assert token_module.get_valid_token(channel) == "seed" and calls == []
    channel, calls = _token_sources(monkeypatch, stored=None, env=None)
    with pytest.raises(InstagramTokenError, match="no Instagram token"):
        token_module.get_valid_token(channel)


def test_run_channel_aborts_before_any_work_when_token_is_dead(monkeypatch):
    import sys

    import narovva.orchestration.run_channel  # noqa: F401
    from narovva.config.schema import BrandKitConfig, ChannelConfig, GenreSetting

    rc = sys.modules["narovva.orchestration.run_channel"]
    monkeypatch.setattr(rc, "get_settings", lambda: rc.Settings(database_url=None, newsapi_key=None))
    monkeypatch.setattr(rc, "_preflight_token", lambda ch: (_ for _ in ()).throw(InstagramTokenError("expired")))
    monkeypatch.setattr(rc, "get_store_for_channel", lambda cid: (_ for _ in ()).throw(AssertionError("must not fetch")))
    channel = ChannelConfig(id="c", ig_business_account_id="1", genres=[GenreSetting(genre="tech")], brand=BrandKitConfig(name="B"))
    result = rc.run_channel(channel)
    assert result.failed == 1 and result.errors == ["expired"] and result.considered == 0


def test_cli_refresh_token_command(monkeypatch, capsys):
    from narovva import cli

    monkeypatch.setattr(cli, "load_channel", lambda path: type("C", (), {"id": "chan"})())
    import narovva.tokens as tokens

    monkeypatch.setattr(tokens, "refresh_token", lambda ch: None)
    assert cli.main(["refresh-token", "x.yaml"]) == 0
    assert "chan" in capsys.readouterr().out

    def fail(ch):
        raise InstagramTokenError("token refresh failed")

    monkeypatch.setattr(tokens, "refresh_token", fail)
    assert cli.main(["refresh-token", "x.yaml"]) == 1
