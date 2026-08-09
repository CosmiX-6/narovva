"""Channel-scoped dedup store.

Prefers info_snipe.store_postgres.PostgresContentStore (namespaced per
channel_id) whenever DATABASE_URL is set, since that's the only backend
that survives Vercel's serverless filesystem -- each invocation can get a
fresh disk, so a local SQLite file wouldn't persist dedup state across
runs. Falls back to a local SQLite info_snipe.ContentStore per channel
when there's no database configured (e.g. a quick local smoke test with
no Postgres set up yet). NewsFetcher only ever calls filter_unseen()/
mark_seen_many() on whatever it's given, so nothing else in the
orchestration layer needs to know which backend is in play.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

from info_snipe import ContentStore
from info_snipe.store_postgres import PostgresContentStore

from ..settings import get_settings


def get_store_for_channel(channel_id: str) -> Union[ContentStore, PostgresContentStore]:
    settings = get_settings()
    if settings.database_url:
        return PostgresContentStore(settings.database_url, namespace=channel_id)

    db_dir = Path(settings.local_dedup_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    return ContentStore(db_path=db_dir / f"{channel_id}.db")
