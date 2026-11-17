"""Render the sample deck from the repo root:

    python -m narovva.motion [out.mp4] [logo.png] [photo.jpg] [--worlds | --lesson]

Without a photo argument a synthetic one is drawn, so every path the real
pipeline takes (photo card, charts, captions) is exercised with no assets
beyond the repo's own. The look is the one config/channels/example-tech-ig.yaml
sets (the live channel's), or the default without it."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg

from ..config.schema import MotionStyleConfig
from .render import render_motion_reel
from .sample import sample_story, write_sample_photo
from .slides import total_duration
from .style import deck_ui

CHANNEL = Path("config/channels/example-tech-ig.yaml")


def _look() -> MotionStyleConfig:
    """The live channel's look (so the sample shows what posts), else the default."""
    if CHANNEL.exists():
        from ..config import load_channel
        return load_channel(str(CHANNEL)).motion
    return MotionStyleConfig()


def main() -> None:
    worlds = "--worlds" in sys.argv  # every 3D set piece instead of the sample story
    lesson = "--lesson" in sys.argv  # the sample lesson ("How AI works") instead of the news story
    sys.argv = [a for a in sys.argv if a not in ("--worlds", "--lesson")]
    out = sys.argv[1] if len(sys.argv) > 1 else "motion-sample.mp4"
    # Relative to the working directory (repo root), like channel.brand.logo_path.
    logo = Path(sys.argv[2] if len(sys.argv) > 2 else "assets/logo/CU.png")
    look = _look()
    if worlds:
        from .sample import world_gallery
        slides, subject = world_gallery(look=look)
    elif lesson:
        from .sample import sample_lesson
        slides, subject = sample_lesson(captions=True, look=look)
    else:
        slides, subject = sample_story(captions=True, look=look)
    total = total_duration([s["duration"] for s in slides])
    audio = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220",
         "-t", f"{total:.2f}", "-f", "mp3", "-"], capture_output=True, check=True,
    ).stdout
    with tempfile.TemporaryDirectory(prefix="narovva-sample-") as tmp:
        photo = sys.argv[3] if len(sys.argv) > 3 else write_sample_photo(Path(tmp) / "sample.jpg")
        path = render_motion_reel(
            slides, audio, out, accent="#3B82F6", handle="contextunfiltered",
            brand="CONTEXT UNFILTERED", logo_path=str(logo),
            photo_path=photo, photo_credit="Image: sample", seed="sample",
            ui=deck_ui(look, subject=subject, category="AI", brand="CONTEXT UNFILTERED"),
        )
    print(path)


if __name__ == "__main__":
    main()
