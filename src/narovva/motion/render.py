"""Renders a motion-graphics Reel with HyperFrames (HTML + GSAP -> headless
Chrome -> FFmpeg). Stages a throwaway project per render (template copy +
deck.js + logo + faded music), runs `hyperframes render`, and sanity-checks
the MP4. Any failure raises MotionRenderError so the caller can fall back to
the plain Ken-Burns reel (narovva.video.assemble_reel)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg

from .photo import prepare_photo
from .slides import VOICE_LEAD, total_duration

logger = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates" / "reel"
_AUDIO_FADE_SECONDS = 1.5
_RENDER_TIMEOUT_SECONDS = 900
_MIN_OUTPUT_BYTES = 50_000


class MotionRenderError(RuntimeError):
    """Raised when the HyperFrames render can't produce a valid reel."""


def _hyperframes_command() -> list[str]:
    """HYPERFRAMES_BIN override, else a hyperframes on PATH, else the repo's
    own node_modules (installed by `npm ci`) via npx without network fetch."""
    override = os.environ.get("HYPERFRAMES_BIN")
    if override:
        return override.split()
    found = shutil.which("hyperframes")
    if found:
        return [found]
    npx = shutil.which("npx")
    if not npx:
        raise MotionRenderError("neither hyperframes nor npx found on PATH (is Node 22 installed?)")
    return [npx, "--no-install", "hyperframes"]


def _prepare_audio(audio_bytes: bytes, total: float, dest: Path) -> None:
    """Trim to the reel length and fade out, so HyperFrames mixes a ready bed."""
    src = dest.with_suffix(".src")
    src.write_bytes(audio_bytes)
    try:
        cmd = [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(src), "-t", f"{total:.3f}",
            "-af", f"afade=t=out:st={max(total - _AUDIO_FADE_SECONDS, 0):.3f}:d={_AUDIO_FADE_SECONDS}",
            "-c:a", "libmp3lame", "-q:a", "3", str(dest),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    finally:
        src.unlink(missing_ok=True)
    if result.returncode != 0:
        raise MotionRenderError(f"audio prep failed: {result.stderr[-800:]}")


def _stage_photo(photo_path: str | None, credit: str | None, assets_dir: Path) -> dict | None:
    """The article photo is a bonus, never a requirement: anything wrong with
    it just means the reel renders without one."""
    if not photo_path:
        return None
    try:
        photo = prepare_photo(photo_path, assets_dir)
    except Exception as exc:
        logger.warning("motion photo skipped: %s", exc)
        return None
    if photo:
        photo["credit"] = credit or ""
    return photo


def stage_project(
    stage_dir: Path, slides: list[dict], *, accent: str, handle: str, brand: str,
    logo_path: str, audio_bytes: bytes | None,
    photo_path: str | None = None, photo_credit: str | None = None, seed: str = "",
    ui: dict | None = None,
) -> float:
    """Populate `stage_dir` with a renderable HyperFrames project; returns the
    total reel duration in seconds. `seed` (e.g. the article id) fixes the
    generative background and transition order, so a story always renders
    the same way but no two stories look alike. `ui` is the look from
    narovva.motion.style.deck_ui; without it the reel keeps the original
    brand header, bottom progress bar and plain captions."""
    if not slides:
        raise MotionRenderError("no slides to render")
    if not Path(logo_path).is_file():
        raise MotionRenderError(f"logo not found: {logo_path}")
    shutil.copytree(_TEMPLATE_DIR, stage_dir, dirs_exist_ok=True)
    (stage_dir / "assets").mkdir(exist_ok=True)
    shutil.copyfile(logo_path, stage_dir / "assets" / "logo.png")

    total = total_duration([s["duration"] for s in slides])
    deck = {
        "slides": slides, "accent": accent, "handle": handle, "brand": brand,
        "photo": _stage_photo(photo_path, photo_credit, stage_dir / "assets"),
        "seed": int(hashlib.sha256((seed or slides[0].get("heading") or "").encode()).hexdigest()[:8], 16),
        "captions": any(part.get("caption") for s in slides for part in s.get("parts") or []),
        "voice_lead": VOICE_LEAD,
        "ui": ui or {},
    }
    # </script> in article text must not terminate the inline-free deck.js
    # either way, but escape '<' so the file is also safe if ever inlined.
    (stage_dir / "deck.js").write_text(
        "window.CU_DECK = " + json.dumps(deck, ensure_ascii=False).replace("<", "\\u003c") + ";\n",
        encoding="utf-8",
    )

    audio_tag = ""
    if audio_bytes:
        _prepare_audio(audio_bytes, total, stage_dir / "assets" / "music.mp3")
        audio_tag = (
            f'<audio id="music" src="assets/music.mp3" data-start="0" data-duration="{total:.3f}" '
            'data-track-index="2" data-volume="1"></audio>'
        )
    html = (stage_dir / "index.html").read_text(encoding="utf-8")
    html = html.replace("{{TOTAL}}", f"{total:.3f}").replace("<!--HF_AUDIO-->", audio_tag)
    (stage_dir / "index.html").write_text(html, encoding="utf-8")
    return total


def _probe_duration(path: str) -> float | None:
    result = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-i", path], capture_output=True, text=True, timeout=60
    )
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", result.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else None


def render_motion_reel(
    slides: list[dict], audio_bytes: bytes | None, output_path: str, *,
    accent: str, handle: str, brand: str, logo_path: str,
    photo_path: str | None = None, photo_credit: str | None = None, seed: str = "",
    ui: dict | None = None, stage_dir: str | None = None,
) -> str:
    """Render `slides` (see narovva.motion.slides) to an MP4 at `output_path`
    (1080x1920, 30fps). `photo_path` is the article's own photo, if it has
    one. Raises MotionRenderError on any failure."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="narovva-motion-") as tmp:
        stage = Path(stage_dir) if stage_dir else Path(tmp) / "project"
        total = stage_project(
            stage, slides, accent=accent, handle=handle, brand=brand,
            logo_path=logo_path, audio_bytes=audio_bytes,
            photo_path=photo_path, photo_credit=photo_credit, seed=seed, ui=ui,
        )
        cmd = [*_hyperframes_command(), "render", str(stage), "--quality", "looks", "--fps", "30",
               "--output", str(out)]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=_RENDER_TIMEOUT_SECONDS,
                env={**os.environ, "CI": "1"},
            )
        except subprocess.TimeoutExpired as exc:
            raise MotionRenderError(f"hyperframes render timed out after {_RENDER_TIMEOUT_SECONDS}s") from exc
        except OSError as exc:
            raise MotionRenderError(f"could not launch hyperframes: {exc}") from exc
    if result.returncode != 0:
        tail = (result.stdout + result.stderr)[-1500:]
        raise MotionRenderError(f"hyperframes render failed (exit {result.returncode}): {tail}")
    if not out.is_file() or out.stat().st_size < _MIN_OUTPUT_BYTES:
        raise MotionRenderError("hyperframes render produced no usable output file")
    duration = _probe_duration(str(out))
    if duration is None or abs(duration - total) > 1.0:
        raise MotionRenderError(f"rendered duration {duration} does not match expected {total:.2f}s")
    return str(out)
