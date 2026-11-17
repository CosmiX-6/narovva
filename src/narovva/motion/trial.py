"""Try the story writer on live material without posting anything:

    python -m narovva.motion.trial out_dir [--lesson ID] [--genre health] [--no-render]

For a lesson of the channel's series (default: the first one) and for the
freshest story of one news genre, it runs the real pipeline up to the video --
the article analysis, the animated storyboard from the channel's text-model
chain, the 3D render -- and writes, per item, the model's raw reply
(`*-reply.json`), what survived validation (`*-board.json`) and the video
(`*.mp4`, music-free and voice-free, with captions). Nothing is posted,
uploaded or marked as seen.

Costs what a post's writing costs: about two text-model calls per item
(free-tier Gemini first, per the channel's llm_chain)."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg

from ..config import load_channel
from ..lessons import load_series, reference_source
from ..viral.editor import spoken
from .render import render_motion_reel
from .slides import total_duration
from .storyboard import beat_specs, hook_board, write_storyboard
from .style import category_label, deck_ui, stamp_colors, story_subject

logger = logging.getLogger(__name__)


class _Recorder:
    """The channel's text model, keeping each reply for the report."""

    def __init__(self, llm):
        self.llm, self.replies = llm, []

    def complete_json(self, system, user, *a, **kw):
        out = self.llm.complete_json(system, user, *a, **kw)
        self.replies.append(out)
        return out

    def __getattr__(self, name):
        return getattr(self.llm, name)


def _pipeline(channel, llm):
    from poster_core import Pipeline, PipelineConfig

    return Pipeline(PipelineConfig(text_provider=channel.text_provider, image_provider="none",
                                   output_dir=tempfile.mkdtemp(prefix="narovva-trial-"),
                                   brand=channel.brand.to_poster_core()), llm=llm)


def _render(channel, board, brief, out: Path) -> None:
    look = channel.motion
    specs = beat_specs(board, stamp_colors=stamp_colors(look), heading_marks=look.heading_marks)
    total = total_duration([s["duration"] for s in specs])
    audio = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
         "-t", f"{total:.2f}", "-f", "mp3", "-"], capture_output=True, check=True,
    ).stdout
    category = getattr(brief.category, "value", str(brief.category))
    render_motion_reel(
        specs, audio, str(out), accent=channel.brand.category_accents.get(category) or channel.brand.accent_color,
        handle=channel.brand.social_handle or "", brand=channel.brand.name, logo_path=channel.brand.logo_path or "",
        seed=out.stem, ui=deck_ui(look, subject=story_subject(board.subject, brief), category=category_label(category),
                                  brand=channel.brand.name),
    )


def _report(name: str, rec: _Recorder, board, out_dir: Path) -> bool:
    reply = rec.replies[-1] if rec.replies else None
    (out_dir / f"{name}-reply.json").write_text(json.dumps(reply, indent=2, ensure_ascii=False), encoding="utf-8")
    asked = [(b.get("scene"), (b.get("data") or {}).get("piece")) for b in (reply or {}).get("beats", []) if isinstance(b, dict)]
    print(f"\n== {name}: the model wrote {len(asked)} beats: {asked}")
    if board is None:
        print(f"== {name}: DID NOT VALIDATE (a real post would fall back to the slide reel)")
        return False
    kept = [(b["scene"], b["data"].get("piece")) for b in board.beats]
    (out_dir / f"{name}-board.json").write_text(json.dumps(board.beats, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"== {name}: {len(kept)} beats kept: {kept}")
    for b in board.beats:
        print(f"   [{b['scene']:6}] {(b['data'].get('title') or '')!r:44} {' / '.join(b['lines'])}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("out_dir")
    parser.add_argument("--channel", default="config/channels/example-tech-ig.yaml")
    parser.add_argument("--lesson", help="lesson id (default: the series' first lesson)")
    parser.add_argument("--genre", default="health", help="news genre to try ('none' to skip)")
    parser.add_argument("--no-render", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    from ..orchestration.run_channel import _build_llm

    channel = load_channel(args.channel)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rec = _Recorder(_build_llm(channel))
    pipeline = _pipeline(channel, rec)
    brand = channel.brand.name.title() if channel.brand.name.isupper() else channel.brand.name
    story = channel.motion.story
    ok = True

    series_key = next((g.series for g in channel.genres if g.series), None)
    if series_key:
        series = load_series(series_key)
        lesson = next((x for x in series.lessons if x.id == args.lesson), None) if args.lesson else series.lessons[0]
        if lesson is None:
            sys.exit(f"no lesson {args.lesson!r} in {series_key}")
        article, brief = pipeline.analyze(reference_source(lesson))
        board = write_storyboard(rec, brief, article, brand=brand, max_beats=story.max_beats,
                                 target_seconds=story.target_seconds, hook=lesson.hook, audience=channel.audience,
                                 max_asks=story.viewer_questions, lesson=lesson)
        ok &= _report(f"lesson-{lesson.id}", rec, board, out_dir)
        if board and not args.no_render:
            hook_board(board, lesson.hook, spoken(lesson.hook), brief.headline, trending=False)
            _render(channel, board, brief, out_dir / f"lesson-{lesson.id}.mp4")

    if args.genre != "none":
        from info_snipe import ContentStore, NewsFetcher, RSSSource

        store = ContentStore(db_path=Path(tempfile.mkdtemp(prefix="narovva-trial-")) / "seen.db")
        articles = NewsFetcher(sources=[RSSSource()], store=store).fetch(args.genre, limit=5, mark_seen=False)
        for item in articles:
            try:
                article, brief = pipeline.analyze(item.url)
            except Exception as exc:  # a site that refuses the download: try the next story
                print(f"skipping {item.url}: {exc}")
                continue
            print(f"\nnews ({args.genre}): {item.title} -- {item.url}")
            board = write_storyboard(rec, brief, article, brand=brand, max_beats=story.max_beats,
                                     target_seconds=story.target_seconds, max_stamps=0, audience=channel.audience,
                                     max_asks=story.viewer_questions, mode="animated",
                                     when=(item.published_at.strftime("%d %b %Y") if item.published_at else ""))
            ok &= _report(f"news-{args.genre}", rec, board, out_dir)
            if board and not args.no_render:
                _render(channel, board, brief, out_dir / f"news-{args.genre}.mp4")
            break
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
