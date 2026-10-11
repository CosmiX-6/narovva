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
