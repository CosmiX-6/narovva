"""Render the sample deck from the repo root: python -m narovva.motion [out.mp4] [logo.png]"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

from .render import render_motion_reel, stage_project  # noqa: F401
from .sample import SAMPLE_SLIDES
from .slides import compact_spec, display_chars, motion_duration, total_duration


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "motion-sample.mp4"
    # Relative to the working directory (repo root), like channel.brand.logo_path.
    logo = Path(sys.argv[2] if len(sys.argv) > 2 else "assets/logo/CU.png")
    slides = [compact_spec(dict(s)) for s in SAMPLE_SLIDES]
    for s in slides:
        s["duration"] = motion_duration(display_chars(s), s["kind"])
    total = total_duration([s["duration"] for s in slides])
    audio = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220",
         "-t", f"{total:.2f}", "-f", "mp3", "-"], capture_output=True, check=True,
    ).stdout
    path = render_motion_reel(
        slides, audio, out, accent="#3B82F6", handle="contextunfiltered",
        brand="CONTEXT UNFILTERED", logo_path=str(logo),
    )
    print(path)


if __name__ == "__main__":
    main()
