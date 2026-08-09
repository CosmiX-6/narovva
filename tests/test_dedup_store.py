from __future__ import annotations

import os

import pytest
from info_snipe.models import Article
from info_snipe.store_postgres import PostgresContentStore

from narovva import dedup
from narovva.settings import Settings


def test_store_is_scoped_per_channel(tmp_path, monkeypatch):
    monkeypatch.setattr(
        dedup.store, "get_settings", lambda: Settings(local_dedup_dir=str(tmp_path))
    )

    store_a = dedup.get_store_for_channel("channel-a")
    store_b = dedup.get_store_for_channel("channel-b")

    article = Article(
        content_id="abc123", title="A story", url="https://example.com/a",
        source_name="Example", genre="tech",
    )
    store_a.mark_seen(article)

    assert store_a.has_seen("abc123") is True
    assert store_b.has_seen("abc123") is False
    assert (tmp_path / "channel-a.db").exists()
    assert (tmp_path / "channel-b.db").exists()


@pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="DATABASE_URL not set")
def test_database_url_prefers_postgres_store_over_sqlite(monkeypatch):
    database_url = os.environ["DATABASE_URL"]
    monkeypatch.setattr(
        dedup.store, "get_settings", lambda: Settings(database_url=database_url)
    )

    store = dedup.get_store_for_channel("test-narovva-dedup-channel")
    try:
        assert isinstance(store, PostgresContentStore)
        assert store.namespace == "test-narovva-dedup-channel"
    finally:
        store._conn.execute(
            "DELETE FROM seen_content WHERE namespace = %s", (store.namespace,)
        )
        store.close()
