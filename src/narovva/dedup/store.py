"""Channel-scoped dedup store.

Prefers info_snipe.store_postgres.PostgresContentStore (namespaced per
channel_id) whenever DATABASE_URL is set, since that's the only backend
that survives between CI runs -- each GitHub Actions job starts on a fresh
disk, so a local SQLite file wouldn't persist dedup state across runs.
Falls back to a local SQLite info_snipe.ContentStore per channel
when there's no database configured (e.g. a quick local smoke test with
no Postgres set up yet). NewsFetcher only ever calls filter_unseen()/
mark_seen_many() on whatever it's given, so nothing else in the
orchestration layer needs to know which backend is in play.
"""

from __future__ import annotations

import logging
from pathlib import Path

import psycopg
from info_snipe import ContentStore
from info_snipe.store_postgres import PostgresContentStore

from ..settings import get_settings

logger = logging.getLogger(__name__)


class ResilientPostgresStore:
    """PostgresContentStore that rebuilds itself (new connection) and retries
    once if the server dropped its long-idle connection -- e.g. mark_seen()
    after a multi-minute motion-reel render."""

    def __init__(self, dsn: str, namespace: str):
        self._dsn, self._namespace = dsn, namespace
        self._store = PostgresContentStore(dsn, namespace=namespace)

    def __getattr__(self, name):
        attr = getattr(self._store, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            try:
                return getattr(self._store, name)(*args, **kwargs)
            except (psycopg.OperationalError, psycopg.InterfaceError):
                logger.warning("dedup store connection was closed; reconnecting")
                self._store = PostgresContentStore(self._dsn, namespace=self._namespace)
                return getattr(self._store, name)(*args, **kwargs)

        return call


def get_store_for_channel(channel_id: str) -> ContentStore | ResilientPostgresStore:
    settings = get_settings()
    if settings.database_url:
        return ResilientPostgresStore(settings.database_url, namespace=channel_id)

    db_dir = Path(settings.local_dedup_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    return ContentStore(db_path=db_dir / f"{channel_id}.db")
