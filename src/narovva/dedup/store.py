"""Channel-scoped dedup store.

Phase 1: one info_snipe.ContentStore (SQLite) per channel, so dedup is
naturally channel-scoped -- two channels covering the same genre don't
block each other -- without any info-snipe code change.

Phase 2 (Vercel deploy, no persistent local disk): swap this factory to
return info_snipe.store_postgres.PostgresContentStore(dsn, namespace=
channel_id) once that backend lands upstream. NewsFetcher only ever calls
filter_unseen()/mark_seen_many() on whatever it's given, so nothing else
in the orchestration layer needs to change.
"""

from __future__ import annotations

from pathlib import Path

from info_snipe import ContentStore

from ..settings import get_settings


def get_store_for_channel(channel_id: str) -> ContentStore:
    settings = get_settings()
    db_dir = Path(settings.local_dedup_dir)
    db_dir.mkdir(parents=True, exist_ok=True)
    return ContentStore(db_path=db_dir / f"{channel_id}.db")
