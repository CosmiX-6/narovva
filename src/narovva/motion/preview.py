"""Still frames of the motion reel, straight from a local Chrome -- for
working on the template without the HyperFrames toolchain (Node 22):

    python -m narovva.motion.preview out_dir [--at 0.4,2.5,6] [--photo PATH|none]
                                             [--no-captions] [--via 9.0]
                                             [--hud case_file|breakdown|brand|none]
                                             [--captions-style karaoke|pill|brighten]
                                             [--timeline cards|spine] [--no-stamps]
                                             [--story storyboard|slides]

Stages the sample deck, then for each timestamp loads the composition in
headless Chrome, seeks its timeline there and saves a 1080x1920 PNG, plus a
`sheet.png` contact sheet of them all. `--via T` seeks to T first, to check
a frame looks the same when it is reached out of order (as it is when
HyperFrames renders in parallel).

This previews layout and motion states. It is not the renderer: the real
MP4 still comes from `python -m narovva.motion` / HyperFrames."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

from ..config.schema import MotionStyleConfig
from .render import stage_project
from .sample import SAMPLE_SUBJECT, sample_deck, sample_story, write_sample_photo
from .slides import SCENE_OVERLAP_SECONDS, total_duration
from .style import deck_ui

_CHROME_NAMES = ("chrome", "google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "msedge")
_CHROME_PATHS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)

# Stands in for the HyperFrames runtime: provide the timeline registry, then
# seek the registered timeline to ?t= (after ?via=, if given).
_SHIM_HEAD = "<script>window.__timelines = {};</script>"
_SHIM_TAIL = """<script>
(function wait() {
  const tl = window.__timelines["cu-reel"];
  if (!tl) { setTimeout(wait, 20); return; }
  const q = new URLSearchParams(location.search);
  if (q.get("via")) { tl.seek(parseFloat(q.get("via")), false); gsap.ticker.tick(); }
  tl.seek(parseFloat(q.get("t") || "0"), false);
  gsap.ticker.tick();
})();
</script>"""


def find_chrome() -> str:
    override = os.environ.get("CHROME_BIN")
    if override:
        return override
    for name in _CHROME_NAMES:
        found = shutil.which(name)
        if found:
            return found
    for path in _CHROME_PATHS:
        if Path(path).is_file():
            return path
    raise RuntimeError("no Chrome found; set CHROME_BIN to a Chrome/Chromium executable")


def scene_times(slides: list[dict]) -> list[float]:
    """Looks at every scene: mid-entrance, once into each later spoken line
    (where a storyboard scene builds), and settled."""
    times, start = [], 0.0
    for slide in slides:
        times.append(round(start + 0.45, 2))
        times += [round(start + part["at"] + 0.8, 2) for part in (slide.get("parts") or [])[1:]]
        times.append(round(start + slide["duration"] - SCENE_OVERLAP_SECONDS - 0.15, 2))
        start += slide["duration"] - SCENE_OVERLAP_SECONDS
    return times


def snapshot(project: Path, t: float, out_png: Path, via: float | None = None) -> None:
    url = (project / "preview.html").resolve().as_uri() + f"?t={t}" + (f"&via={via}" if via is not None else "")
    cmd = [
        find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
        "--window-size=1080,1920", "--allow-file-access-from-files", "--virtual-time-budget=8000",
        f"--screenshot={out_png.resolve()}", url,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if not out_png.is_file():
        raise RuntimeError(f"Chrome produced no screenshot for t={t}: {result.stderr[-600:]}")


def contact_sheet(frames: list[tuple[float, Path]], out_png: Path, columns: int = 5) -> None:
    from PIL import Image, ImageDraw

    tw, th, pad = 324, 576, 8
    rows = -(-len(frames) // columns)
    sheet = Image.new("RGB", (columns * (tw + pad) + pad, rows * (th + pad + 22) + pad), (30, 30, 34))
    draw = ImageDraw.Draw(sheet)
    for n, (t, path) in enumerate(frames):
        x, y = pad + (n % columns) * (tw + pad), pad + (n // columns) * (th + pad + 22)
        with Image.open(path) as frame:
            sheet.paste(frame.convert("RGB").resize((tw, th)), (x, y + 20))
        draw.text((x + 2, y + 2), f"t = {t:.2f}s", fill=(230, 230, 235))
    sheet.save(out_png)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m narovva.motion.preview", description=__doc__.split("\n\n")[0])
    parser.add_argument("out_dir")
    parser.add_argument("--at", help="comma-separated seconds (default: two frames per scene)")
    parser.add_argument("--photo", help="article photo to use, or 'none' (default: a synthetic one)")
    parser.add_argument("--no-captions", action="store_true")
    parser.add_argument("--via", type=float, help="seek here first, then to each timestamp")
    parser.add_argument("--logo", default="assets/logo/CU.png")
    parser.add_argument("--accent", default="#3B82F6")
    parser.add_argument("--hud", choices=["case_file", "breakdown", "brand", "none"])
    parser.add_argument("--captions-style", choices=["karaoke", "pill", "brighten"])
    parser.add_argument("--timeline", choices=["cards", "spine"])
    parser.add_argument("--no-stamps", action="store_true")
    parser.add_argument("--story", choices=["storyboard", "slides"], default="storyboard",
                        help="the explainer storyboard sample, or the slide-based reel")
    args = parser.parse_args(argv)
    look = MotionStyleConfig()
    if args.hud:
        look.hud.style = args.hud
    if args.captions_style:
        look.captions.style = args.captions_style
    if args.timeline:
        look.timeline = args.timeline
    look.stamps.enabled = not args.no_stamps

    out = Path(args.out_dir)
    project = out / "project"
    if project.exists():
        shutil.rmtree(project)
    out.mkdir(parents=True, exist_ok=True)
    if args.story == "storyboard":
        slides, subject = sample_story(captions=not args.no_captions, look=look)
    else:
        slides, subject = sample_deck(captions=not args.no_captions, look=look), SAMPLE_SUBJECT
    photo = None if args.photo == "none" else args.photo or write_sample_photo(out / "sample-photo.jpg")
    ui = deck_ui(look, subject=subject, category="AI", brand="CONTEXT UNFILTERED")
    stage_project(
        project, slides, accent=args.accent, handle="contextunfiltered", brand="CONTEXT UNFILTERED",
        logo_path=args.logo, audio_bytes=None, photo_path=photo, photo_credit="Image: sample", seed="sample", ui=ui,
    )
    html = (project / "index.html").read_text(encoding="utf-8")
    html = html.replace("<script src=\"vendor/gsap.min.js\">", _SHIM_HEAD + "\n    <script src=\"vendor/gsap.min.js\">", 1)
    (project / "preview.html").write_text(html.replace("</body>", _SHIM_TAIL + "\n  </body>"), encoding="utf-8")

    times = [float(x) for x in args.at.split(",")] if args.at else scene_times(slides)
    frames: list[tuple[float, Path]] = []
    for t in times:
        png = out / f"frame_{t:06.2f}.png"
        snapshot(project, t, png, via=args.via)
        frames.append((t, png))
        print(png)
    contact_sheet(frames, out / "sheet.png")
    print(out / "sheet.png", f"({total_duration([s['duration'] for s in slides]):.1f}s reel)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
