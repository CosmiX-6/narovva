"""Lean the hook writer toward the formulas that beat this channel's normal.

Gentle by design: a formula is only judged once it has `min_posts` measured posts;
proven-weak ones (average multiple under `drop_below`) are left out of the prompt,
proven-strong ones are listed first, untested ones stay in; and on `explore` of
posts (chosen per article, so a re-run makes the same choice) every configured
formula is offered, so the channel keeps learning instead of locking in early."""

from __future__ import annotations

import hashlib
import logging
import statistics
from datetime import datetime, timedelta, timezone

from .report import measure

logger = logging.getLogger(__name__)


def formula_stats(repo, channel_id: str, *, days: int = 90, now: datetime | None = None) -> dict[str, tuple[int, float]]:
    """{formula: (posts with a baseline, mean multiple)} from the stored metrics."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    rows = measure(repo.published_posts(channel_id, since), repo.metrics_snapshots(channel_id, since), now=now)
    groups: dict[str, list[float]] = {}
    for m in rows:
        f = m.post.get("hook_formula")
        if f and m.multiple is not None:
            groups.setdefault(f, []).append(m.multiple)
    return {f: (len(v), statistics.mean(v)) for f, v in groups.items()}


def _roll(seed: str) -> float:
    return int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF


def choose_formulas(configured: list[str], stats: dict[str, tuple[int, float]], *, seed: str,
                    min_posts: int = 20, drop_below: float = 0.85, explore: float = 0.2,
                    keep_at_least: int = 3) -> list[str]:
    if not configured or _roll(seed) < explore:
        return list(configured)
    proven = [f for f in configured if stats.get(f, (0, 0))[0] >= min_posts]
    if not proven:
        return list(configured)
    strong = sorted((f for f in proven if stats[f][1] >= drop_below), key=lambda f: -stats[f][1])
    untested = [f for f in configured if f not in proven]
    out = strong + untested
    if len(out) < keep_at_least:  # never narrow to almost nothing
        weak = sorted((f for f in proven if f not in out), key=lambda f: -stats[f][1])
        out += weak[: keep_at_least - len(out)]
    if out != list(configured):
        logger.info("hooks: leaning on %s (dropped %s)", out, [f for f in configured if f not in out])
    return out
