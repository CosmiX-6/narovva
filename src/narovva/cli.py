"""Local dev entrypoint: `narovva run-channel <path> [--dry-run]`."""

from __future__ import annotations

import argparse
import logging
import sys

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
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "run-channel":
        channel = load_channel(args.path)
        result = run_channel(channel, genres_filter=args.genre, dry_run=args.dry_run)
        _print_result(result)
        return 1 if result.failed else 0

    if args.command == "run-due":
        channels = load_all_channels(args.channels_dir)
        due = due_channels_with_genres(channels)
        if not due:
            print("Nothing due.")
            return 0
        max_posts = args.max_posts_per_genre or None
        failed_any = False
        for channel, genres in due:
            result = run_channel(
                channel, genres_filter=genres, dry_run=args.dry_run, max_posts_per_genre=max_posts,
            )
            _print_result(result)
            failed_any = failed_any or bool(result.failed)
        return 1 if failed_any else 0

    return 2


def _print_result(result) -> None:
    print(
        f"channel={result.channel_id} considered={result.considered} "
        f"posted={result.posted} failed={result.failed} skipped={result.skipped}"
    )
    for error in result.errors:
        print(f"  error: {error}")


if __name__ == "__main__":
    sys.exit(main())
