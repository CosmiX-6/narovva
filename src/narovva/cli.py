"""Local dev entrypoint: `narovva run-channel <path> [--dry-run]`."""

from __future__ import annotations

import argparse
import logging
import sys

from . import logsafe
from .config import load_all_channels, load_channel
from .orchestration import due_channels_with_genres, run_channel


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="narovva")
    parser.add_argument("-v", "--verbose", action="store_true", help="Debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run-channel", help="Run one channel's pipeline end to end")
    run_p.add_argument("path", help="Path to a channel YAML config")
    run_p.add_argument("--genre", action="append", help="Restrict to one or more genre keys (repeatable)")
    run_p.add_argument(
        "--dry-run", action="store_true",
        help="Fetch, analyze, render and caption, but never host images or publish",
    )
    run_p.add_argument(
        "--max-posts-per-genre", type=int, default=None,
        help="Cap successful publishes per genre in this run (default: unlimited)",
    )

    refresh_p = sub.add_parser(
        "refresh-token", help="Exchange a channel's Instagram token for a fresh ~60-day one (run weekly)",
    )
    refresh_p.add_argument("path", help="Path to a channel YAML config")

    audio_p = sub.add_parser(
        "audio-probe", help="Read-only check: can this channel's token search Instagram's audio library?",
    )
    audio_p.add_argument("path", help="Path to a channel YAML config")
    audio_p.add_argument("--query", default=None, help="Search text (default: trending)")

    ins_p = sub.add_parser(
        "insights-probe", help="Read-only check: can this channel's token read its posts' insights?",
    )
    ins_p.add_argument("path", help="Path to a channel YAML config")

    met_p = sub.add_parser("collect-metrics", help="Snapshot insights for recent posts (run daily)")
    met_p.add_argument("path", help="Path to a channel YAML config")
    met_p.add_argument("--days", type=int, default=14, help="Posts published in the last N days")

    rep_p = sub.add_parser("performance-report", help="Posts vs the channel's own median, by hook formula/topic")
    rep_p.add_argument("path", help="Path to a channel YAML config")
    rep_p.add_argument("--days", type=int, default=90, help="Posts published in the last N days")
    rep_p.add_argument("--out", default=None, help="Also append the markdown report to this file")

    viral_p = sub.add_parser(
        "run-viral", help="Post one viral story (any genre) if a peak-hour slot is open",
    )
    viral_p.add_argument("path", help="Path to a channel YAML config")
    viral_p.add_argument("--force", action="store_true", help="Post now, ignoring the slots")
    viral_p.add_argument("--dry-run", action="store_true", help="Pick and analyse, never publish")

    scan_p = sub.add_parser("viral-scan", help="List the stories going viral right now (read-only)")
    scan_p.add_argument("path", help="Path to a channel YAML config")
    scan_p.add_argument("--editor", action="store_true", help="Also ask the AI editor which ones it would post")

    due_p = sub.add_parser("run-due", help="Run every channel/genre currently due, per configured cadence")
    due_p.add_argument("--channels-dir", default="config/channels")
    due_p.add_argument("--dry-run", action="store_true")
    due_p.add_argument(
        "--max-posts-per-genre", type=int, default=1,
        help="Cap successful publishes per genre in this run (default: 1, matching "
        "'at most once per cadence window'). Pass 0 for unlimited.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logsafe.install(logging.DEBUG if args.verbose else logging.INFO)

    if args.command == "run-channel":
        channel = load_channel(args.path)
        result = run_channel(
            channel, genres_filter=args.genre, dry_run=args.dry_run,
            max_posts_per_genre=args.max_posts_per_genre,
        )
        _print_result(result)
        return 1 if result.failed else 0

    if args.command == "refresh-token":
        from .tokens import InstagramTokenError, refresh_token

        channel = load_channel(args.path)
        try:
            refresh_token(channel)
        except InstagramTokenError as exc:
            print(f"error: {exc}")
            return 1
        print(f"channel={channel.id} Instagram token refreshed")
        return 0

    if args.command == "audio-probe":
        from .publishers.audio_probe import probe_audio_api

        channel = load_channel(args.path)
        for r in probe_audio_api(channel, args.query):
            print(f"== {r['host']} audio_type={r['audio_type']} query={r['query']} -> HTTP {r['status']}")
            print(r["body"])
        return 0

    if args.command == "insights-probe":
        from .publishers.insights import probe
        from .tokens import get_valid_token

        channel = load_channel(args.path)
        for line in probe(channel.ig_business_account_id, get_valid_token(channel)):
            print(logsafe.redact(line))
        return 0

    if args.command in ("collect-metrics", "performance-report"):
        return _metrics_command(args)

    if args.command == "run-viral":
        from .orchestration.viral import run_viral

        channel = load_channel(args.path)
        result = run_viral(channel, dry_run=args.dry_run, force=args.force)
        _print_result(result)
        return 1 if result.failed and not result.posted else 0

    if args.command == "viral-scan":
        return _viral_scan(load_channel(args.path), editor=args.editor)

    if args.command == "run-due":
        from .orchestration.viral import run_viral

        channels = load_all_channels(args.channels_dir)
        failed_any = False
        # Viral slots first: one post per run, so a channel that just posted a viral
        # story waits for the next run before its rotation post.
        viral_posted: set[str] = set()
        for channel in channels:
            if not (channel.enabled and channel.viral and channel.viral.enabled):
                continue
            try:
                result = run_viral(channel, dry_run=args.dry_run)
            except Exception as exc:  # a viral failure must not stop the regular post
                print(f"channel={channel.id} viral crashed: {logsafe.redact(str(exc))}")
                continue
            if result.considered or result.failed:
                print("viral:", end=" ")
                _print_result(result)
            if result.posted:
                viral_posted.add(channel.id)
            elif result.failed and not result.considered:
                failed_any = True  # e.g. Instagram token rejected
        due = [(c, g) for c, g in due_channels_with_genres(channels) if c.id not in viral_posted]
        if not due:
            print("Nothing due." if not viral_posted else "Posted a viral story; rotation waits for the next run.")
            return 1 if failed_any else 0
        max_posts = args.max_posts_per_genre or None
        for channel, genres in due:
            try:
                result = run_channel(
                    channel, genres_filter=genres, dry_run=args.dry_run, max_posts_per_genre=max_posts,
                    # A rotation slot is one post: later genres are only fallbacks.
                    max_posts_total=1 if channel.rotation_minutes else None,
                )
            except Exception as exc:  # one broken channel must not stop the others
                print(f"channel={channel.id} crashed: {logsafe.redact(str(exc))}")
                failed_any = True
                continue
            _print_result(result)
            failed_any = failed_any or bool(result.failed)
        return 1 if failed_any else 0

    return 2


def _metrics_command(args) -> int:
    from datetime import datetime, timedelta, timezone

    from .db.engine import ensure_schema, get_connection
    from .db.repo import Repo
    from .settings import get_settings

    channel = load_channel(args.path)
    if not get_settings().database_url:
        print("error: DATABASE_URL is required (post history and metrics live in Postgres)")
        return 1
    conn = get_connection()
    ensure_schema(conn)
    repo = Repo(conn)
    if args.command == "collect-metrics":
        from .metrics.collect import collect
        from .tokens import get_valid_token

        result = collect(channel, repo, get_valid_token(channel), days=args.days)
        print(f"channel={channel.id} metrics fetched={result.fetched} skipped={result.skipped} failed={result.failed}")
        for err in result.errors[:5]:
            print(f"  error: {logsafe.redact(err)}")
        return 1 if result.failed and not result.fetched and not result.skipped else 0
    from .metrics.report import build_report

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    text = build_report(channel.id, repo.published_posts(channel.id, since), repo.metrics_snapshots(channel.id, since))
    print(text)
    if args.out:
        with open(args.out, "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    return 0


def _viral_scan(channel, *, editor: bool) -> int:
    from datetime import datetime, timezone

    from .orchestration.viral import scan, viral_due
    from .viral.editor import editor_pick

    if not channel.viral:
        print("channel has no 'viral' section")
        return 1
    now = datetime.now(timezone.utc)
    print("slot:", viral_due(channel, now)[1])
    stories = scan(channel, now=now)
    for i, s in enumerate(stories[:20], 1):
        trend = f"  [search: {s.trend.query} {s.trend.traffic}+]" if s.trend else ""
        print(f"{i:2}. {s.score:5.2f}  {len(s.sources)} outlets  {s.age_minutes(now):3.0f} min  {s.title}{trend}")
    if editor and stories:
        from .orchestration.run_channel import _build_llm

        picks = editor_pick(
            _build_llm(channel), stories, now=now, limit=channel.viral.editor_candidates, audience=channel.audience,
        )
        print("editor would post:", [p.title for p in picks] or "none")
    return 0


def _print_result(result) -> None:
    print(
        f"channel={result.channel_id} considered={result.considered} "
        f"posted={result.posted} failed={result.failed} skipped={result.skipped}"
    )
    for error in result.errors:
        print(f"  error: {logsafe.redact(str(error))}")


if __name__ == "__main__":
    sys.exit(main())
