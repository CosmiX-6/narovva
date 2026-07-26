"""Postgres connection + schema bootstrap."""

from __future__ import annotations

from pathlib import Path

import psycopg

from ..settings import get_settings

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_connection() -> psycopg.Connection:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is not set. narovva needs a Postgres connection "
            "string (Neon's pooled endpoint is recommended for serverless)."
        )
    return psycopg.connect(settings.database_url, autocommit=True)


def ensure_schema(conn: psycopg.Connection) -> None:
    """Idempotently apply every migrations/*.sql file, in filename order."""
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        for statement in _split_statements(sql):
            conn.execute(statement)


def _split_statements(sql: str) -> list[str]:
    return [s.strip() for s in sql.split(";") if s.strip() and not s.strip().startswith("--")]
