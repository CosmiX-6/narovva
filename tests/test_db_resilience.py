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


def test_run_channel_aborts_before_any_work_when_token_is_dead(monkeypatch):
    import sys
    from narovva.config.schema import BrandKitConfig, ChannelConfig, GenreSetting
    import narovva.orchestration.run_channel  # noqa: F401

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
