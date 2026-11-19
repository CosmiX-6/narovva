"""Render character reels from live stories without posting anything:

    python -m narovva.characters.trial out_dir [--genre ai] [--count 1] [--scale 1.0] [--no-music-api]

For the freshest stories of one news genre it runs the real pipeline up to the video -- article analysis, the formula
hook, the cast's script and staging from the channel's writer chain, the voices, the render, the mix -- and writes per
story the script (`*-script.json`) and the reel (`*.mp4`). It works with `characters.enabled: false` (that is the point:
judge the format before turning it on). Nothing is posted, uploaded or marked as seen."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from ..config import load_channel

logger = logging.getLogger(__name__)


class _NoTrack:
    audio_bytes = None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out_dir")
    parser.add_argument("--channel", default="config/channels/example-tech-ig.yaml")
    parser.add_argument("--genre", default="ai")
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--scale", type=float, default=None, help="render scale (1.0 = 1080x1920)")
    parser.add_argument("--no-music-api", action="store_true", help="skip Jamendo; use the built-in score")
    parser.add_argument("--url", help="one article URL instead of the genre feed")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from ..hooks.writer import write_package
    from ..motion.trial import _pipeline, _Recorder
    from ..orchestration.run_channel import _build_llm, _pick_music_track, writer_llm
    from . import build_character_reel, script

    channel = load_channel(args.channel)
    if not channel.characters.cast:
        sys.exit("the channel has no characters.cast")
    if args.scale:
        channel.characters.scale = args.scale
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base = _build_llm(channel)
    pipeline = _pipeline(channel, base)
    writer = _Recorder(writer_llm(channel, base, lesson=None, llm_cache={}))

    # keep what the writer returned, for the report
    kept: list = []
    _parse = script.parse

    def recording_parse(raw, **kw):
        cs = _parse(raw, **kw)
        kept.append((raw, cs))
        return cs

    script.parse = recording_parse

    if args.url:
        items = [type("Item", (), {"url": args.url, "title": args.url, "content_id": "trial"})()]
    else:
        from info_snipe import ContentStore, NewsFetcher, RSSSource

        store = ContentStore(db_path=Path(tempfile.mkdtemp(prefix="narovva-trial-")) / "seen.db")
        items = NewsFetcher(sources=[RSSSource()], store=store).fetch(args.genre, limit=8, mark_seen=False)
    genre_setting = next((g for g in channel.genres if g.genre == args.genre), channel.genres[0])
    done, ok = 0, True
    for item in items:
        if done >= args.count:
            break
        try:
            article, brief = pipeline.analyze(item.url)
        except Exception as exc:  # a site that refuses the download: try the next story
            print(f"skipping {item.url}: {exc}")
            continue
        print(f"\nstory: {item.title} -- {item.url}")
        package = write_package(base, brief, formulas=channel.hooks.formulas, style="auto", audience=channel.audience,
                                banned=channel.banned_words, min_score=channel.hooks.min_score,
                                candidates=channel.hooks.candidates)
        print(f"hook: {package.hook if package else None!r} ({package.formula if package else '-'})")
        track = _NoTrack()
        if not args.no_music_api:
            try:
                track = _pick_music_track(channel, genre_setting, brief)
                print(f"music: {track.attribution}")
            except Exception as exc:
                print(f"no Jamendo track ({exc}); using the built-in score")
        name = f"chars-{done + 1}"
        path, voice = build_character_reel(channel, brief, article, track, str(out_dir / f"{name}.mp4"), llm=writer,
                                           hook=package.hook if package else None,
                                           said=package.spoken if package else None, seed=str(getattr(item, "content_id", name)),
                                           workdir=tempfile.mkdtemp(prefix="narovva-chars-"))
        raw, cs = kept[-1] if kept else (None, None)
        (out_dir / f"{name}-script.json").write_text(json.dumps(
            {"story": item.title, "url": item.url, "hook": package.hook if package else None, "reply": raw,
             "kept": asdict(cs) if cs else None}, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        if cs:
            for ln in cs.lines:
                tag = f"[{ln['broll']['piece']}]" if ln.get("broll") else f"({ln['shot']})"
                print(f"   {ln['speaker_name']:4} {tag:16} {ln['text']}")
        print(f"== {name}: {'OK ' + path if path else 'FAILED (a real post would fall back to the motion reel)'}")
        ok &= bool(path)
        done += 1
    return 0 if ok and done else 1


if __name__ == "__main__":
    sys.exit(main())
