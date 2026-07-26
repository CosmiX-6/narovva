"""Which (channel, genre) pairs are due right now, given each genre's
configured cadence and the last successful post for that channel+genre."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..config.schema import ChannelConfig
from ..db.engine import get_connection
from ..db.repo import Repo
from ..settings import get_settings


@dataclass
class DueGenre:
    channel: ChannelConfig
    genre: str


def due_genres(channels: list[ChannelConfig]) -> list[DueGenre]:
    settings = get_settings()
    repo = Repo(get_connection()) if settings.database_url else None

    now = datetime.now(timezone.utc)
    due: list[DueGenre] = []
    for channel in channels:
        if not channel.enabled:
            continue
        for genre_setting in channel.genres:
            last = repo.last_successful_post_at(channel.id, genre_setting.genre) if repo else None
            if last is None or now - last >= timedelta(minutes=genre_setting.cadence_minutes):
                due.append(DueGenre(channel=channel, genre=genre_setting.genre))
    return due


def due_channels_with_genres(channels: list[ChannelConfig]) -> list[tuple[ChannelConfig, list[str]]]:
    """Group due_genres() by channel, ready for run_channel(channel, genres_filter=...)."""
    grouped: dict[str, tuple[ChannelConfig, list[str]]] = {}
    for item in due_genres(channels):
        if item.channel.id not in grouped:
            grouped[item.channel.id] = (item.channel, [])
        grouped[item.channel.id][1].append(item.genre)
    return list(grouped.values())
