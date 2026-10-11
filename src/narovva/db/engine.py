"""Postgres connection + schema bootstrap."""

from __future__ import annotations

import logging
from pathlib import Path

import psycopg

from ..settings import get_settings

logger = logging.getLogger(__name__)
_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


# Postgres servers/proxies drop idle connections; keepalives help, and
# ResilientConnection reconnects when one is dropped anyway (a motion-reel
# render keeps the connection idle for minutes between DB calls).
_CONNECT_KWARGS = dict(autocommit=True, keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=5)


def _connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, **_CONNECT_KWARGS)


class ResilientConnection:
    """psycopg connection that transparently reconnects once if the server
    has closed it. Every statement narovva runs is autocommit and
    idempotent/upsert-shaped, so retrying a failed one is safe."""

    def __init__(self, database_url: str):
        self._url = database_url
        self._conn = _connect(database_url)

    def execute(self, *args, **kwargs):
        try:
            return self._conn.execute(*args, **kwargs)
        except (psycopg.OperationalError, psycopg.InterfaceError):
            logger.warning("database connection was closed; reconnecting")
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = _connect(self._url)
            return self._conn.execute(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def get_connection() -> ResilientConnection:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. narovva needs a Postgres connection "
            "string (Neon's pooled endpoint is recommended for serverless)."
        )
    return ResilientConnection(settings.database_url)


def ensure_schema(conn: psycopg.Connection) -> None:
    """Idempotently apply every migrations/*.sql file, in filename order."""
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        for statement in _split_statements(sql):
            conn.execute(statement)


def _split_statements(sql: str) -> list[str]:
    """Split on top-level semicolons. A leading-comment-only chunk (e.g. the
    file's header comment glued to the first real statement) is fine to send
    as-is -- Postgres ignores SQL comments -- so this only drops chunks that
    are *entirely* comments/whitespace once comment lines are stripped."""
    statements = []
    for chunk in sql.split(";"):
        code_lines = [
            line for line in chunk.splitlines() if line.strip() and not line.strip().startswith("--")
        ]
        if code_lines:
            statements.append(chunk.strip())
    return statements
