"""Which posts beat the channel's normal, and which hook formulas and topics do.

Raw views mostly track follower growth, so every post is judged by its MULTIPLE:
its views (else reach) at `age_hours` old, divided by the median of the channel's
previous `baseline_posts` measured posts. Groups (formula, topic) are only compared
once each has `min_group` posts; with less data the report says so instead of
ranking noise. Method idea from youtube-agent-skill's yt-viral (MIT)."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass
class Measured:
    post: dict
    value: int
    metric: str
    late: bool                      # no snapshot at the target age: the first one after it
    multiple: float | None = None
    avg_watch_ms: int | None = None


def _at_age(post: dict, snaps: list[dict], age: timedelta, now: datetime) -> Measured | None:
    if post["published_at"] is None or now - post["published_at"] < age:
        return None  # too new to judge
    target = post["published_at"] + age
    after = [s for s in snaps if s["fetched_at"] >= target]
    snap = after[0] if after else (snaps[-1] if snaps else None)
    if snap is None:
        return None
    metric = "views" if snap.get("views") is not None else "reach"
    if snap.get(metric) is None:
        return None
    # Late: no snapshot after the target age (only an earlier one), or the first one
    # after it came more than a day late (a missed collector run).
    late = not after or snap["fetched_at"] - target > timedelta(hours=26)
    return Measured(post=post, value=int(snap[metric]), metric=metric, late=late,
                    avg_watch_ms=snap.get("avg_watch_ms"))


def measure(posts: list[dict], snapshots: list[dict], *, now: datetime | None = None,
            age_hours: int = 48, baseline_posts: int = 30, min_baseline: int = 5) -> list[Measured]:
    """Each judgeable post with its multiple over the median of the posts before it."""
    now = now or datetime.now(UTC)
    by_post: dict[str, list[dict]] = {}
    for s in snapshots:
        by_post.setdefault(s["platform_post_id"], []).append(s)
    measured = []
    for post in sorted(posts, key=lambda p: p["published_at"]):
        m = _at_age(post, by_post.get(post["platform_post_id"], []), timedelta(hours=age_hours), now)
        if m:
            measured.append(m)
    # Late measurements (first snapshot long after the target age, e.g. posts from before
    # collection started) include extra days of views, so they are not comparable: they
    # get no multiple and are not used as anyone's baseline.
    on_time = [m for m in measured if not m.late]
    for i, m in enumerate(on_time):
        prior = [x.value for x in on_time[max(0, i - baseline_posts):i] if x.metric == m.metric]
        if len(prior) >= min_baseline:
            base = statistics.median(prior)
            m.multiple = round(m.value / base, 2) if base > 0 else None
    return measured


def _groups(rows: list[Measured], key: str, min_group: int) -> list[tuple[str, int, float]]:
    g: dict[str, list[float]] = {}
    for m in rows:
        if m.multiple is not None and m.post.get(key):  # posts from before hooks have no formula
            g.setdefault(m.post[key], []).append(m.multiple)
    out = [(k, len(v), round(statistics.mean(v), 2)) for k, v in g.items() if len(v) >= min_group]
    return sorted(out, key=lambda t: -t[2])


def recommendation(by_formula: list[tuple[str, int, float]], measured: int, min_group: int) -> str:
    if len(by_formula) >= 2:
        (best, n1, m1), (worst, n2, m2) = by_formula[0], by_formula[-1]
        if m1 - m2 >= 0.3:
            return (f"Favour {best} hooks: they average {m1}x the channel's normal ({n1} posts), "
                    f"against {m2}x for {worst} ({n2} posts).")
        return "No hook formula clearly beats another yet (all within 0.3x); keep the mix."
    return (f"Not enough data to compare hook formulas yet: {measured} posts measured; each formula "
            f"needs {min_group} posts with a baseline.")


def build_report(channel_id: str, posts: list[dict], snapshots: list[dict], *, now: datetime | None = None,
                 min_group: int = 5) -> str:
    """Markdown report (fits a GitHub job summary)."""
    now = now or datetime.now(UTC)
    rows = measure(posts, snapshots, now=now)
    judged = [m for m in rows if m.multiple is not None]
    lines = [f"# Performance report: {channel_id}", "",
             f"{now:%Y-%m-%d}. {len(posts)} posts in range, {len(rows)} at least 48 h old with stats, "
             f"{len(judged)} with a baseline (the median of up to 30 earlier posts).", ""]
    late = sum(m.late for m in rows)
    if late:
        lines += [f"{late} posts were first measured more than a day after their 48 h mark (they were "
                  "published before collection started, or a daily run was missed); their views include "
                  "extra days, so they are left out of the comparisons.", ""]
    if not judged:
        lines.append("Nothing to compare yet: the report needs posts measured at 48 h old, with at "
                     "least 5 such posts before them.")
        watch = [m.avg_watch_ms for m in rows if m.avg_watch_ms]
        if watch:
            lines += ["", f"Average watch time so far: {statistics.mean(watch) / 1000:.1f} s per view."]
        return "\n".join(lines)

    def row(m: Measured) -> str:
        p = m.post
        late = " (late)" if m.late else ""
        return (f"| {m.multiple}x | {m.value:,} {m.metric}{late} | {p.get('hook_formula') or '-'} | "
                f"{(p.get('hook_text') or '-')[:60]} | {(p.get('article_title') or '')[:60]} |")

    head = "| multiple | at 48 h | formula | hook | story |\n|---|---|---|---|---|"
    ranked = sorted(judged, key=lambda m: -m.multiple)
    lines += ["## Top 5", head, *[row(m) for m in ranked[:5]], ""]
    bottom = ranked[max(5, len(ranked) - 5):][::-1]  # never repeats a Top 5 post
    if bottom:
        lines += ["## Bottom 5", head, *[row(m) for m in bottom], ""]
    by_formula = _groups(judged, "hook_formula", min_group)
    by_topic = _groups(judged, "genre", min_group)
    lines.append(f"## By hook formula (groups of {min_group}+)")
    lines += ([f"- {k}: {v}x average over {n} posts" for k, n, v in by_formula]
              or ["- not enough posts per formula yet"])
    lines.append("")
    lines.append(f"## By topic (groups of {min_group}+)")
    lines += [f"- {k}: {v}x average over {n} posts" for k, n, v in by_topic] or ["- not enough posts per topic yet"]
    by_language = _groups(judged, "language", min_group)
    if len({p.get("language") for p in posts if p.get("language")}) > 1:  # only once both languages posted
        lines += ["", f"## By language (groups of {min_group}+)"]
        lines += [f"- {k}: {v}x average over {n} posts" for k, n, v in by_language] or \
            ["- not enough posts per language yet"]
    watch = [m.avg_watch_ms for m in judged if m.avg_watch_ms]
    if watch:
        lines += ["", f"Average watch time: {statistics.mean(watch) / 1000:.1f} s per view "
                      f"(reels run about 30 s; well under that means viewers leave early)."]
    lines += ["", "## Recommendation", recommendation(by_formula, len(judged), min_group)]
    return "\n".join(lines)
