"""Assembles poster-core's rendered PNG images plus a downloaded music
track into a 9:16 Ken-Burns-style MP4 for Instagram Reels, via ffmpeg
(bundled through imageio-ffmpeg -- no system ffmpeg install required, so
this works the same in CI as on a laptop)."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import imageio_ffmpeg

logger = logging.getLogger(__name__)

_WIDTH, _HEIGHT = 1080, 1920  # 9:16, matches poster_core.Platform.INSTAGRAM_STORY
_SECONDS_PER_IMAGE = 4.0  # fallback duration when the caller has no per-slide durations
_FPS = 30
_AUDIO_FADE_SECONDS = 1.5
_XFADE_SECONDS = 0.6  # crossfade overlap between consecutive slides
_XFADE_TRANSITION = "fade"

# Design-system readability formula: duration = max(floor, chars/rate) +
# transition buffer. The floor guarantees even a two-word slide gets a beat
# to register; there is deliberately no ceiling here -- content that would
# blow past a comfortable hold (the design system's 5.5s recommendation) is
# a slide-splitting decision that belongs upstream, in poster-core's own
# text limits, not something this function should silently clamp.
_CHARS_PER_SECOND = 14.0
_MIN_SLIDE_SECONDS = 1.8
_TRANSITION_BUFFER_SECONDS = 0.4
_RECOMMENDED_MAX_SECONDS = 5.5


class VideoAssemblyError(RuntimeError):
    """Raised when ffmpeg is unavailable or fails to produce a video."""


def slide_duration(char_count: int) -> float:
    """Design-system timing formula: max(1.8, chars/14) + 0.4s transition
    buffer. Logs a warning (does not clamp) if the result exceeds the
    system's 5.5s recommended ceiling -- that's a cue to split the slide's
    content, not to truncate its time on screen."""
    seconds = max(_MIN_SLIDE_SECONDS, char_count / _CHARS_PER_SECOND) + _TRANSITION_BUFFER_SECONDS
    if seconds > _RECOMMENDED_MAX_SECONDS:
        logger.warning(
            "slide_duration: %d characters computes to %.1fs, above the %.1fs "
            "recommended ceiling -- consider splitting this slide's content",
            char_count, seconds, _RECOMMENDED_MAX_SECONDS,
        )
    return seconds


def assemble_reel(
    image_paths: list[str], audio_bytes: bytes, output_path: str,
    durations: list[float] | None = None,
) -> str:
    """Renders a slow zoom/pan (Ken Burns) slideshow of `image_paths`, each
    shown for its entry in `durations` (seconds) and crossfaded into the
    next, backed by `audio_bytes` trimmed and faded to the video's total
    length. `durations` defaults to a flat `_SECONDS_PER_IMAGE` per image
    when unset. Returns `output_path`."""
    if not image_paths:
        raise VideoAssemblyError("at least one image is required to assemble a reel")

    durations = durations if durations is not None else [_SECONDS_PER_IMAGE] * len(image_paths)
    if len(durations) != len(image_paths):
        raise VideoAssemblyError(
            f"durations has {len(durations)} entries for {len(image_paths)} images"
        )

    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    audio_path = out.parent / f"{out.stem}_audio.mp3"
    audio_path.write_bytes(audio_bytes)

    n = len(image_paths)
    # A hard cap keeps the overlap sane if any slide's duration is very
    # short -- the crossfade can never exceed half of the shortest slide.
    xfade_seconds = min(_XFADE_SECONDS, min(durations) / 2)

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
        duration = durations[0]
    else:
        # Chain xfade filters instead of a hard-cut concat: each transition
        # blends the tail of the running stream into the next slide rather
        # than jump-cutting, so slide changes read as a deliberate edit
        # instead of a stutter. offset is the point (in the RUNNING merged
        # stream's own timeline) where each transition starts, so it's
        # tracked cumulatively rather than computed as a closed form.
        label = "v0"
        running_duration = durations[0]
        for i in range(1, n):
            out_label = "vout" if i == n - 1 else f"x{i}"
            offset = running_duration - xfade_seconds
            filter_parts.append(
                f"[{label}][v{i}]xfade=transition={_XFADE_TRANSITION}:"
                f"duration={xfade_seconds}:offset={offset}[{out_label}]"
            )
            running_duration += durations[i] - xfade_seconds
            label = out_label
        vout_label = "vout"
        duration = running_duration
    filter_complex = ";".join(filter_parts)

    audio_input_index = n
    cmd = [imageio_ffmpeg.get_ffmpeg_exe(), "-y"]
    for img, img_duration in zip(image_paths, durations):
        # -framerate must match zoompan's fps below: with d=1 (one output
        # frame per input frame, needed so the zoom expression advances
        # once per real frame instead of zoompan re-multiplying an
        # already-looped input), a framerate mismatch here desyncs each
        # segment's real length from its intended duration.
        cmd += ["-loop", "1", "-framerate", str(_FPS), "-t", str(img_duration), "-i", img]
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
