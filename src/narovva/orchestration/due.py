"""Which (channel, genre) pairs are due right now.

Two scheduling modes per channel:
- Rotation (channel.rotation_minutes is set): the channel posts at most one
  item every rotation_minutes, cycling through channel.genres in configured
  order so consecutive posts alternate genres.
- Independent (legacy, rotation_minutes unset): each genre becomes due on
  its own genre.cadence_minutes clock, independently of the others -- a
  channel can post once per genre in the same run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..config.schema import ChannelConfig
from ..db.engine import get_connection
from ..db.repo import Repo
from ..settings import get_settings

ROTATION_GRACE_MINUTES = 20
VIRAL_GENRE = "viral"  # post_history.genre of viral posts


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
        if not channel.enabled or not channel.genres:
            continue
        if channel.rotation_minutes is not None:
            genre = _next_rotation_genre(channel, repo, now)
            if genre is not None:
                # The due genre first, then the others in rotation order as fallbacks: a
                # genre with nothing new to post must not hold up the whole rotation
                # (the caller posts at most one item per rotation slot).
                order = [g.genre for g in channel.genres]
                start = order.index(genre)
                for name in order[start:] + order[:start]:
                    due.append(DueGenre(channel=channel, genre=name))
        else:
            for genre_setting in channel.genres:
                last = repo.last_successful_post_at(channel.id, genre_setting.genre) if repo else None
                if last is None or now - last >= timedelta(minutes=genre_setting.cadence_minutes):
                    due.append(DueGenre(channel=channel, genre=genre_setting.genre))
    return due


def _next_rotation_genre(channel: ChannelConfig, repo: Repo | None, now: datetime) -> str | None:
    genre_order = [g.genre for g in channel.genres]
    if repo is None:
        # No persistence to check cadence against -- treat as always due,
        # starting the rotation from the first configured genre.
        return genre_order[0]

    # Viral posts are extra, outside the genre rotation: they must not reset its order.
    last = repo.last_successful_post(channel.id, exclude_genres=(VIRAL_GENRE,))
    if last is None:
        return genre_order[0]

    last_genre, last_at = last
    # Posts are stamped after the render/upload (several minutes into the hour),
    # while the scheduler ticks on the hour; without a grace window a 120-minute
    # rotation would only ever fire every 3 hours.
    if now - last_at < timedelta(minutes=channel.rotation_minutes - ROTATION_GRACE_MINUTES):
        return None

    idx = (genre_order.index(last_genre) + 1) % len(genre_order) if last_genre in genre_order else 0
    return genre_order[idx]


def due_channels_with_genres(channels: list[ChannelConfig]) -> list[tuple[ChannelConfig, list[str]]]:
    """Group due_genres() by channel, ready for run_channel(channel, genres_filter=...)."""
    grouped: dict[str, tuple[ChannelConfig, list[str]]] = {}
    for item in due_genres(channels):
        if item.channel.id not in grouped:
            grouped[item.channel.id] = (item.channel, [])
        grouped[item.channel.id][1].append(item.genre)
    return list(grouped.values())
