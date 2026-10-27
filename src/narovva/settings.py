"""Process-wide settings read from environment variables."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel


class Settings(BaseModel):
    database_url: str | None = None
    blob_read_write_token: str | None = None
    token_encryption_key: str | None = None
    newsapi_key: str | None = None
    channels_dir: str = "config/channels"
    local_dedup_dir: str = ".narovva/dedup"
    max_publish_attempts: int = 3
    blob_orphan_ttl_minutes: int = 30


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get("DATABASE_URL"),
        blob_read_write_token=os.environ.get("BLOB_READ_WRITE_TOKEN"),
        token_encryption_key=os.environ.get("TOKEN_ENCRYPTION_KEY"),
        newsapi_key=os.environ.get("NEWSAPI_KEY"),
    )


def resolve_env(var_name: str | None) -> str | None:
    """Resolve a channel config field that names an env var, not a value."""
    if not var_name:
        return None
    return os.environ.get(var_name)
