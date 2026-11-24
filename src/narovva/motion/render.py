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
from .slides import SCENE_OVERLAP_SECONDS, VOICE_LEAD, total_duration

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


_FREE = 'data-layout-allow-overflow data-layout-allow-overlap data-layout-allow-occlusion'


def _stage_media(slides: list[dict], assets: Path) -> tuple[list[dict], str, str]:
    """Copy each beat's b-roll (narovva.motion.broll) into the project and write its element: backdrops (photos and
    clips) go in the background layer, cut-outs and logo badges in front of it, under the scene graphics. Each gets
    its exact window -- from the spoken line that names its subject to the end of the beat -- which the template
    animates and HyperFrames uses to play a clip in step with the timeline."""
    out, back, front, t = [], [], [], 0.0
    for i, s in enumerate(slides):
        start = t
        t += s["duration"] - SCENE_OVERLAP_SECONDS
        m = s.get("media")
        src = Path(m["path"]) if m and m.get("path") else None
        if not m or not src or not src.is_file():
            out.append({k: v for k, v in s.items() if k != "media"})
            continue
        name = f"m{i}{src.suffix.lower()}"
        shutil.copyfile(src, assets / name)
        parts = s.get("parts") or []
        line = min(int(m.get("line") or 0), max(len(parts) - 1, 0))
        t0 = start + (parts[line]["at"] if parts else 0.0) - 0.12
        t0 = max(start, round(t0, 3))
        t1 = round(start + s["duration"], 3)
        if m.get("type") == "video":
            t1 = min(t1, round(t0 + float(m.get("seconds") or 0), 3))
        if t1 - t0 < 1.0:
            out.append({k: v for k, v in s.items() if k != "media"})
            continue
        mid = f"m{i}"
        use = m.get("use") or "backdrop"
        if m.get("type") == "video":
            inner = (f'<video src="assets/{name}" muted playsinline data-start="{t0:.3f}" '
                     f'data-duration="{t1 - t0:.3f}" data-track-index="3"></video>')
        else:
            inner = f'<img src="assets/{name}" alt="" />'
        if use == "backdrop":
            back.append(f'<div class="broll" id="{mid}" {_FREE}>{inner}</div>')
        else:
            side = "left" if m.get("side") == "left" else "right"
            front.append(f'<div class="{use} {side}" id="{mid}" {_FREE}>{inner}</div>')
        media = {"id": mid, "use": use, "move": m.get("move") or "in", "t0": t0, "t1": t1}
        out.append(dict(s, media=media))
    return out, "\n        ".join(back), "\n      ".join(front)


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
    slides, broll_tags, cutout_tags = _stage_media(slides, stage_dir / "assets")
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
    html = html.replace("<!--HF_BROLL-->", broll_tags).replace("<!--HF_CUTOUTS-->", cutout_tags)
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
    ui: dict | None = None, stage_dir: str | None = None, heal=None, report: dict | None = None,
) -> str:
    """Render `slides` (see narovva.motion.slides) to an MP4 at `output_path`
    (1080x1920, 30fps). `photo_path` is the article's own photo, if it has
    one. Raises MotionRenderError on any failure."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="narovva-motion-") as tmp:
        stage = Path(stage_dir) if stage_dir else Path(tmp) / "project"
        kw = dict(accent=accent, handle=handle, brand=brand, logo_path=logo_path, audio_bytes=audio_bytes,
                  photo_path=photo_path, photo_credit=photo_credit, seed=seed, ui=ui)
        total = stage_project(stage, slides, **kw)
        # Gate 3: measure every scene before rendering; `heal(slides, issues)` may replace the scenes that fail,
        # once, and the page is measured again. The result goes into `report` (quality.layout).
        issues = layout_audit(stage) if heal is not None or report is not None else None
        if issues and heal is not None:
            logger.warning("layout audit: %d scene(s) fail (%s); replacing them", len(issues),
                           "; ".join(f"{i}: {v[0]}" for i, v in issues.items()))
            healed = heal(slides, issues)
            if healed is not None:
                slides = healed
                shutil.rmtree(stage, ignore_errors=True)
                total = stage_project(stage, slides, **kw)
                issues = layout_audit(stage)
        if report is not None:
            report["layout"] = {"ok": issues is not None and not issues,
                                "issues": [f"scene {i}: {v[0]}" for i, v in (issues or {}).items()],
                                "notes": [] if issues is not None else ["not audited (no Chrome)"],
                                "metrics": {"scenes": len(slides)}}
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
    if report is not None and audio_bytes:
        from .quality import loudness_review

        try:   # gate 4: what the viewer hears
            report["loudness"] = loudness_review(str(out))
        except Exception as exc:  # measuring must never cost the post
            logger.warning("loudness check skipped (%s)", exc)
    return str(out)


# -- gate 3: layout audit ---------------------------------------------------------------------------------------------
# Every scene is seeked to its settled moment in headless Chrome and its text measured: anything clipped out of the
# scene window or the frame, two labels on top of each other, or type too small to read on a phone. Runs on the staged
# project before the (slow) HyperFrames render, so a bad scene can be replaced first.

_AUDIT_JS = r"""<script>
(function wait() {
  const tl = window.__timelines && window.__timelines["cu-reel"];
  if (!tl) { setTimeout(wait, 20); return; }
  const OV = 0.3, slides = window.CU_DECK.slides, scenes = [...document.querySelectorAll("#scenes > .scene")];
  const win = document.getElementById("scenes").getBoundingClientRect();
  const out = {}, measured = [];
  let t = 0;
  const vis = (e) => { let o = 1; for (let n = e; n && n !== document.body; n = n.parentElement) {
    const cs = getComputedStyle(n); if (cs.display === "none" || cs.visibility === "hidden") return 0; o *= parseFloat(cs.opacity); } return o; };
  const text = (e) => [...e.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
  const exempt = (e) => e.closest(".stamp, [data-layout-allow-occlusion], .cvs, .kicker");
  slides.forEach((s, i) => {
    const at = t + s.duration - OV - 0.2;
    t += s.duration - OV;
    tl.seek(at, false); gsap.ticker.tick();
    const sc = scenes[i]; if (!sc) return;
    const items = [...sc.querySelectorAll("*")].filter((e) => text(e) && vis(e) > 0.4)
      .map((e) => ({ e, r: e.getBoundingClientRect(), txt: e.textContent.trim().slice(0, 30) }))
      .filter((o) => o.r.width > 2 && o.r.height > 2);
    const issues = [];
    measured.push(items.length);
    items.forEach((o) => {
      const r = o.r;
      if (r.left < win.left - 2 || r.right > win.right + 2 || r.top < win.top - 2 || r.bottom > win.bottom + 2)
        issues.push("clipped: " + o.txt);
      const fs = parseFloat(getComputedStyle(o.e).fontSize) * (o.e.offsetHeight ? r.height / o.e.offsetHeight : 1);
      if (fs < 22) issues.push("too small (" + Math.round(fs) + "px): " + o.txt);
    });
    for (let a = 0; a < items.length; a++) for (let b = a + 1; b < items.length; b++) {
      const A = items[a], B = items[b];
      if (A.e.contains(B.e) || B.e.contains(A.e) || exempt(A.e) || exempt(B.e)) continue;
      const w = Math.min(A.r.right, B.r.right) - Math.max(A.r.left, B.r.left);
      const h = Math.min(A.r.bottom, B.r.bottom) - Math.max(A.r.top, B.r.top);
      if (w <= 6 || h <= 6) continue;   // touching is fine; text on text is not
      const small = Math.min(A.r.width * A.r.height, B.r.width * B.r.height);
      if ((w * h) / small > 0.05) issues.push("overlap: " + A.txt + " / " + B.txt);
    }
    if (issues.length) out[i] = [...new Set(issues)].slice(0, 6);
  });
  const pre = document.createElement("pre"); pre.id = "qa-out"; pre.textContent = JSON.stringify({ issues: out, measured });
  document.body.appendChild(pre);
})();
</script>"""


def layout_audit(project: Path) -> dict[int, list[str]] | None:
    """{scene index: [issues]} for a staged project (empty when every scene is clean); None when Chrome is not
    available or the page could not be measured (the render then goes ahead unaudited)."""
    from .preview import _SHIM_HEAD, find_chrome

    try:
        chrome = find_chrome()
    except RuntimeError:
        logger.info("layout audit skipped: no Chrome")
        return None
    html = (project / "index.html").read_text(encoding="utf-8")
    html = html.replace('<script src="vendor/gsap.min.js">', _SHIM_HEAD + '\n    <script src="vendor/gsap.min.js">', 1)
    qa = project / "qa.html"
    qa.write_text(html.replace("</body>", _AUDIT_JS + "\n  </body>"), encoding="utf-8")
    try:
        proc = subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
             "--window-size=1080,1920", "--allow-file-access-from-files", "--virtual-time-budget=20000",
             "--dump-dom", qa.resolve().as_uri()],
            capture_output=True, text=True, encoding="utf-8", timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("layout audit could not run (%s)", exc)
        return None
    finally:
        qa.unlink(missing_ok=True)
    m = re.search(r'<pre id="qa-out">(.*?)</pre>', proc.stdout or "", re.S)
    if not m:
        logger.warning("layout audit: the page gave no result")
        return None
    import html as _html

    data = json.loads(_html.unescape(m.group(1)))
    measured = data.get("measured") or []
    if not measured or not any(measured):
        logger.warning("layout audit: nothing was measured (the page did not build); skipping")
        return None
    logger.info("layout audit: %d text items measured across %d scenes", sum(measured), len(measured))
    return {int(k): v for k, v in (data.get("issues") or {}).items()}
