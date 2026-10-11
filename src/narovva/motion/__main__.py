"""Render the sample deck: python -m narovva.motion [out.mp4] [--keep-stage DIR]"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg

from .render import render_motion_reel, stage_project  # noqa: F401
from .sample import SAMPLE_SLIDES


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "motion-sample.mp4"
    logo = Path(__file__).resolve().parents[3] / "assets" / "logo" / "CU.png"
    total = sum(s["duration"] for s in SAMPLE_SLIDES) - 0.4 * (len(SAMPLE_SLIDES) - 1)
    audio = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220",
         "-t", f"{total:.2f}", "-f", "mp3", "-"], capture_output=True, check=True,
    ).stdout
    path = render_motion_reel(
        SAMPLE_SLIDES, audio, out, accent="#3B82F6", handle="contextunfiltered",
        brand="CONTEXT UNFILTERED", logo_path=str(logo),
    )
    print(path)


if __name__ == "__main__":
    main()
