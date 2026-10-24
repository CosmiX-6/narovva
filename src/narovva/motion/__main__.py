"""Render the sample deck from the repo root:

    python -m narovva.motion [out.mp4] [logo.png] [photo.jpg]

Without a photo argument a synthetic one is drawn, so every path the real
pipeline takes (photo card, charts, captions) is exercised with no assets
beyond the repo's own."""

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


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "motion-sample.mp4"
    # Relative to the working directory (repo root), like channel.brand.logo_path.
    logo = Path(sys.argv[2] if len(sys.argv) > 2 else "assets/logo/CU.png")
    look = MotionStyleConfig()  # the default look, as a channel without a `motion:` block gets it
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
