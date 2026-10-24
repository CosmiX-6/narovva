from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from narovva.config.schema import BrandKitConfig, ChannelConfig, GenreSetting
from narovva.metrics import collect as col
from narovva.metrics.report import build_report, measure, recommendation
from narovva.publishers.insights import InsightsError

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def _post(i, views, formula="the-question", genre="ai_practitioner", hours_old=None):
    published = NOW - timedelta(hours=hours_old if hours_old is not None else 24 * (40 - i))
    return {"platform_post_id": f"p{i}", "published_at": published, "genre": genre,
            "article_title": f"Story {i}", "hook_text": f"Hook {i}?", "hook_formula": formula,
            "hook_score": 55, "cover_text": "COVER"}, \
        {"platform_post_id": f"p{i}", "fetched_at": published + timedelta(hours=50), "views": views,
         "reach": views // 2, "avg_watch_ms": 9000}


def _data(values, formulas=None):
    posts, snaps = [], []
    for i, v in enumerate(values):
        p, s = _post(i, v, formula=(formulas[i] if formulas else "the-question"))
        posts.append(p)
        snaps.append(s)
    return posts, snaps


def test_multiple_is_over_the_median_of_earlier_posts():
    posts, snaps = _data([100, 100, 100, 100, 100, 300, 50])
    m = measure(posts, snaps, now=NOW)
    assert [x.multiple for x in m] == [None] * 5 + [3.0, 0.5]


def test_too_new_posts_are_not_judged_and_late_snapshots_are_flagged():
    posts, snaps = _data([100] * 6)
    young, ysnap = _post(99, 1000, hours_old=10)
    old_no_late_snap, _ = _post(98, 0, hours_old=200)
    early = {"platform_post_id": "p98", "fetched_at": old_no_late_snap["published_at"] + timedelta(hours=5),
             "views": 40, "reach": 20}
    m = measure(posts + [young, old_no_late_snap], snaps + [ysnap, early], now=NOW)
    ids = {x.post["platform_post_id"]: x for x in m}
    assert "p99" not in ids and ids["p98"].late and not ids["p5"].late


def test_report_groups_formulas_and_recommends():
    values = [100] * 5 + [300, 280, 260, 290, 310] + [60, 50, 70, 55, 65]
    formulas = ["the-question"] * 5 + ["the-mistake"] * 5 + ["the-list"] * 5
    posts, snaps = _data(values, formulas)
    text = build_report("chan", posts, snaps, now=NOW)
    assert "## Top 5" in text and "the-mistake:" in text
    assert "Favour the-mistake hooks" in text and "the-list" in text
    assert "Average watch time: 9.0 s" in text


def test_report_with_too_little_data_says_so():
    posts, snaps = _data([100, 120])
    assert "Nothing to compare yet" in build_report("chan", posts, snaps, now=NOW)
    assert "Not enough data" in recommendation([], 3, 5)


class _Repo:
    def __init__(self, posts):
        self.posts, self.saved, self.done = posts, [], {"p0"}

    def published_posts(self, channel_id, since):
        return self.posts

    def has_metrics_snapshot(self, channel_id, pid, day):
        return pid in self.done

    def upsert_metrics(self, channel_id, pid, day, metrics):
        self.saved.append((pid, day, metrics))


def test_collect_maps_columns_skips_done_and_stops_on_permission(monkeypatch):
    ch = ChannelConfig(id="chan", genres=[GenreSetting(genre="tech")], brand=BrandKitConfig())
    posts = [{"platform_post_id": f"p{i}"} for i in range(4)]

    def fake(pid, token):
        if pid == "p2":
            raise InsightsError("HTTP 400: (#100) missing permission")
        return {"views": 10, "ig_reels_avg_watch_time": 8000, "saved": 2, "unknown_metric": 1}

    monkeypatch.setattr(col, "media_insights", fake)
    repo = _Repo(posts)
    r = col.collect(ch, repo, "tok", now=NOW)
    assert (r.fetched, r.skipped, r.failed) == (1, 1, 1)
    assert repo.saved == [("p1", date(2026, 11, 20), {"views": 10, "avg_watch_ms": 8000, "saved": 2})]


def test_choose_formulas_is_gentle():
    from narovva.metrics.learn import choose_formulas

    configured = ["the-mistake", "the-question", "the-list", "the-warning"]
    stats = {"the-mistake": (25, 1.9), "the-question": (22, 0.6), "the-list": (3, 0.2)}
    seeds = [f"article-{i}" for i in range(200)]
    picks = [choose_formulas(configured, stats, seed=s) for s in seeds]
    narrowed = [p for p in picks if p != configured]
    # Proven-weak the-question is dropped; strong first; untested/too-few kept.
    assert all(p == ["the-mistake", "the-list", "the-warning"] for p in narrowed)
    assert 0.1 < 1 - len(narrowed) / len(picks) < 0.3  # ~20% still explore every formula
    assert choose_formulas(configured, stats, seed="x") == choose_formulas(configured, stats, seed="x")
    # Nothing proven yet: no change.
    assert choose_formulas(configured, {"the-list": (3, 0.2)}, seed="y") == configured
    # Never narrows below three.
    weak = {f: (30, 0.5) for f in configured}
    assert len(choose_formulas(configured, weak, seed="article-1")) >= 3


def test_hook_stats_off_without_learn_or_db():
    import importlib

    from narovva.config.schema import HooksConfig

    rc = importlib.import_module("narovva.orchestration.run_channel")
    ch = ChannelConfig(id="c", genres=[GenreSetting(genre="tech")], brand=BrandKitConfig())
    assert rc.load_hook_stats(object(), ch) is None
    ch.hooks = HooksConfig(learn=True)
    assert rc.load_hook_stats(None, ch) is None

    class Broken:
        def published_posts(self, *a):
            raise RuntimeError("db down")

    assert rc.load_hook_stats(Broken(), ch) is None


def test_late_measurements_are_not_compared_and_prehook_posts_are_not_a_formula():
    posts, snaps = _data([100] * 8, [None] * 8)
    for s in snaps[:3]:
        s["fetched_at"] += timedelta(days=5)  # backfilled long after 48 h
    rows = measure(posts, snaps, now=NOW)
    assert all(m.multiple is None for m in rows if m.late) and sum(m.late for m in rows) == 3
    text = build_report("chan", posts, snaps, now=NOW)
    assert "3 posts were first measured more than a day after" in text
    assert "none:" not in text  # posts from before hooks are not a 'formula'
