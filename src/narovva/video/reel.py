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
_XFADE_SECONDS = 0.6  # crossfade overlap between consecutive slides
_XFADE_TRANSITION = "fade"


class VideoAssemblyError(RuntimeError):
    """Raised when ffmpeg is unavailable or fails to produce a video."""


def assemble_reel(image_paths: list[str], audio_bytes: bytes, output_path: str) -> str:
    """Renders a slow zoom/pan (Ken Burns) slideshow of `image_paths`, each
    shown for _SECONDS_PER_IMAGE seconds and crossfaded into the next,
    backed by `audio_bytes` trimmed and faded to the video's total length.
    Returns `output_path`."""
    if not image_paths:
        raise VideoAssemblyError("at least one image is required to assemble a reel")

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    audio_path = out.parent / f"{out.stem}_audio.mp3"
    audio_path.write_bytes(audio_bytes)

    n = len(image_paths)
    # A hard cap keeps the overlap sane if a caller ever shortens
    # _SECONDS_PER_IMAGE below 2x the crossfade length.
    xfade_seconds = min(_XFADE_SECONDS, _SECONDS_PER_IMAGE / 2)

    filter_parts = []
    for i in range(n):
        # Alternate zoom-in / zoom-out so consecutive slides don't feel
        # identical; zoompan needs the image pre-scaled 2x so it has room
        # to zoom into without pixelating.
        zoom_expr = "min(zoom+0.0015,1.3)" if i % 2 == 0 else "if(eq(on,0),1.3,max(zoom-0.0015,1.0))"
        filter_parts.append(
            f"[{i}:v]scale={_WIDTH * 2}:{_HEIGHT * 2},"
            f"zoompan=z='{zoom_expr}':d=1:s={_WIDTH}x{_HEIGHT}:fps={_FPS},"
            f"setsar=1,format=yuv420p[v{i}]"
        )

    if n == 1:
        vout_label = "v0"
        duration = _SECONDS_PER_IMAGE
    else:
        # Chain xfade filters instead of a hard-cut concat: each transition
        # blends the tail of the running stream into the next slide rather
        # than jump-cutting, so slide changes read as a deliberate edit
        # instead of a stutter. offset is the point (in the RUNNING merged
        # stream's own timeline) where each transition starts, so it's
        # tracked cumulatively rather than computed as a closed form.
        label = "v0"
        running_duration = _SECONDS_PER_IMAGE
        for i in range(1, n):
            out_label = "vout" if i == n - 1 else f"x{i}"
            offset = running_duration - xfade_seconds
            filter_parts.append(
                f"[{label}][v{i}]xfade=transition={_XFADE_TRANSITION}:"
                f"duration={xfade_seconds}:offset={offset}[{out_label}]"
            )
            running_duration += _SECONDS_PER_IMAGE - xfade_seconds
            label = out_label
        vout_label = "vout"
        duration = running_duration
    filter_complex = ";".join(filter_parts)

    audio_input_index = n
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y"]
    for img in image_paths:
        # -framerate must match zoompan's fps below: with d=1 (one output
        # frame per input frame, needed so the zoom expression advances
        # once per real frame instead of zoompan re-multiplying an
        # already-looped input), a framerate mismatch here desyncs each
        # segment's real length from its intended _SECONDS_PER_IMAGE.
        cmd += ["-loop", "1", "-framerate", str(_FPS), "-t", str(_SECONDS_PER_IMAGE), "-i", img]
    cmd += [
        "-i", str(audio_path),
        "-filter_complex", filter_complex,
        "-map", f"[{vout_label}]",
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
