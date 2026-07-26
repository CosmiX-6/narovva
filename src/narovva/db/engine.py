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
