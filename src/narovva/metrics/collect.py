"""Daily insights snapshot for every post published in the last `days` days."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from ..config.schema import ChannelConfig
from ..publishers.insights import InsightsError, media_insights

logger = logging.getLogger(__name__)

# Instagram metric name -> post_metrics column.
_COLUMNS = {
    "views": "views", "reach": "reach", "likes": "likes", "comments": "comments", "saved": "saved",
    "shares": "shares", "total_interactions": "total_interactions",
    "ig_reels_avg_watch_time": "avg_watch_ms", "ig_reels_video_view_total_time": "total_watch_ms",
}


@dataclass
class CollectResult:
    fetched: int = 0
    skipped: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def to_columns(metrics: dict[str, int]) -> dict[str, int]:
    return {_COLUMNS[k]: v for k, v in metrics.items() if k in _COLUMNS}


def collect(channel: ChannelConfig, repo, token: str, *, days: int = 14,
            now: datetime | None = None) -> CollectResult:
    """One snapshot per post per day (re-running the same day skips posts already done).
    Stops early if the token cannot read insights at all."""
    now = now or datetime.now(UTC)
    today = now.date()
    result = CollectResult()
    for post in repo.published_posts(channel.id, now - timedelta(days=days)):
        pid = post["platform_post_id"]
        if repo.has_metrics_snapshot(channel.id, pid, today):
            result.skipped += 1
            continue
        try:
            metrics = media_insights(pid, token)
        except InsightsError as exc:
            result.failed += 1
            result.errors.append(f"{pid}: {exc}")
            if "permission" in str(exc).lower() or "OAuth" in str(exc):
                logger.error("insights not readable with this token (%s); stopping", exc)
                break
            continue
        repo.upsert_metrics(channel.id, pid, today, to_columns(metrics))
        result.fetched += 1
    logger.info("metrics: fetched %d, skipped %d, failed %d", result.fetched, result.skipped, result.failed)
    return result
