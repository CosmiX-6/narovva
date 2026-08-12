"""Assembles poster-core's rendered PNG images plus a downloaded music
track into a 9:16 Ken-Burns-style MP4 for Instagram Reels, via ffmpeg
(bundled through imageio-ffmpeg -- no system ffmpeg install required, so
this works the same in CI as on a laptop)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import imageio_ffmpeg

_WIDTH, _HEIGHT = 1080, 1920  # 9:16, matches poster_core.Platform.INSTAGRAM_STORY
_SECONDS_PER_IMAGE = 4.0
_FPS = 30
_AUDIO_FADE_SECONDS = 1.5


class VideoAssemblyError(RuntimeError):
    """Raised when ffmpeg is unavailable or fails to produce a video."""


def assemble_reel(image_paths: list[str], audio_bytes: bytes, output_path: str) -> str:
    """Renders a slow zoom/pan (Ken Burns) slideshow of `image_paths`, each
    shown for _SECONDS_PER_IMAGE seconds, backed by `audio_bytes` trimmed
    and faded to the video's total length. Returns `output_path`."""
    if not image_paths:
        raise VideoAssemblyError("at least one image is required to assemble a reel")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    audio_path = out.parent / f"{out.stem}_audio.mp3"
    audio_path.write_bytes(audio_bytes)

    duration = _SECONDS_PER_IMAGE * len(image_paths)
    frames_per_image = int(_SECONDS_PER_IMAGE * _FPS)

    filter_parts = []
    for i in range(len(image_paths)):
        # Alternate zoom-in / zoom-out so consecutive slides don't feel
        # identical; zoompan needs the image pre-scaled 2x so it has room
        # to zoom into without pixelating.
        zoom_expr = "min(zoom+0.0015,1.3)" if i % 2 == 0 else "if(eq(on,0),1.3,max(zoom-0.0015,1.0))"
        filter_parts.append(
            f"[{i}:v]scale={_WIDTH * 2}:{_HEIGHT * 2},"
            f"zoompan=z='{zoom_expr}':d={frames_per_image}:s={_WIDTH}x{_HEIGHT}:fps={_FPS},"
            f"setsar=1[v{i}]"
        )
    concat_inputs = "".join(f"[v{i}]" for i in range(len(image_paths)))
    filter_parts.append(f"{concat_inputs}concat=n={len(image_paths)}:v=1:a=0[vout]")
    filter_complex = ";".join(filter_parts)

    audio_input_index = len(image_paths)
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y"]
    for img in image_paths:
        cmd += ["-loop", "1", "-t", str(_SECONDS_PER_IMAGE), "-i", img]
    cmd += [
        "-i", str(audio_path),
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-map", f"{audio_input_index}:a",
        "-af", f"afade=t=out:st={max(duration - _AUDIO_FADE_SECONDS, 0)}:d={_AUDIO_FADE_SECONDS}",
        "-t", str(duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-shortest",
        str(out),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    finally:
        audio_path.unlink(missing_ok=True)

    if result.returncode != 0:
        raise VideoAssemblyError(f"ffmpeg failed (exit {result.returncode}): {result.stderr[-2000:]}")
    return str(out)
