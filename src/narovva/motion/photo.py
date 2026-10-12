"""Prepares the article's own photo for the motion reel.

Most article photos are ~1200x630 landscape. Filling a 1080x1920 frame with
one is a 3x upscale and looks soft, so the reel shows it two ways instead:

- sharp, in a framed card on the opening scene (downscaled, never upscaled),
  or full-bleed when the photo is tall and large enough to cover the frame;
- blurred, darkened and tinted as atmosphere behind every scene, where
  softness is the point.

The blur is baked here rather than left to CSS: a blur filter recomputed on
every captured frame is slow to render. A photo that is too small, oddly
shaped, or really a logo on a flat background is rejected, and the reel
runs on its generative background alone."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat

logger = logging.getLogger(__name__)

FRAME = (1080, 1920)
_OVERSCAN = 1.1                  # room for the slow push-in without showing an edge
_CARD_WIDTH = 858                # the content column in templates/reel/index.html
_CARD_ASPECT = (1.45, 16 / 9)    # card width / height; taller than this leaves no room for the headline
_MIN_WIDTH, _MIN_HEIGHT = 600, 340
_MAX_ASPECT = 3.0
_MIN_CONTRAST = 18.0             # luminance std-dev; below this it's a flat graphic
_MAX_FLAT_SHARE = 0.8            # share of pixels in the single commonest tone (a product shot on white is ~0.6)
_ATMO_MAX_LUMA = 58.0            # mean brightness the atmosphere may reach: text sits on top of it
_FULL_BLEED_MAX_UPSCALE = 1.15
_NAVY = (10, 14, 26)


def _cover(img: Image.Image, size: tuple[int, int], focus_y: float = 0.5) -> Image.Image:
    """Scale and crop to fill `size`; `focus_y` biases the vertical crop."""
    return ImageOps.fit(img, size, Image.Resampling.LANCZOS, centering=(0.5, focus_y))


def _is_flat_graphic(img: Image.Image) -> bool:
    grey = img.convert("L").resize((160, 160))
    if ImageStat.Stat(grey).stddev[0] < _MIN_CONTRAST:
        return True
    histogram = grey.histogram()
    # Widen the commonest tone a little so JPEG noise on a flat fill still counts.
    peak = max(range(256), key=histogram.__getitem__)
    share = sum(histogram[max(peak - 6, 0): peak + 7]) / (160 * 160)
    return share > _MAX_FLAT_SHARE


def prepare_photo(src_path: str | Path, assets_dir: Path) -> dict | None:
    """Write `photo.jpg` (sharp) and `photo_bg.jpg` (atmosphere) into
    `assets_dir` and describe them for the template. Returns None, with the
    reason logged, when the photo should not be used."""
    try:
        with Image.open(src_path) as raw:
            img = ImageOps.exif_transpose(raw).convert("RGB")
    except Exception as exc:
        logger.info("motion photo skipped: cannot open %s (%s)", src_path, exc)
        return None

    w, h = img.size
    aspect = w / h
    if w < _MIN_WIDTH or h < _MIN_HEIGHT:
        logger.info("motion photo skipped: %dx%d is too small", w, h)
        return None
    if aspect > _MAX_ASPECT or aspect < 1 / _MAX_ASPECT:
        logger.info("motion photo skipped: aspect %.2f is too extreme", aspect)
        return None
    if _is_flat_graphic(img):
        logger.info("motion photo skipped: looks like a logo or flat graphic")
        return None

    assets_dir.mkdir(parents=True, exist_ok=True)
    upscale = max(FRAME[0] / w, FRAME[1] / h)
    if upscale <= _FULL_BLEED_MAX_UPSCALE:
        mode = "full"
        sharp = _cover(img, (round(FRAME[0] * _OVERSCAN), round(FRAME[1] * _OVERSCAN)), focus_y=0.4)
        card_height = None
    else:
        mode = "card"
        card_aspect = min(max(aspect, _CARD_ASPECT[0]), _CARD_ASPECT[1])
        card_height = round(_CARD_WIDTH / card_aspect)
        # Up to 1.5x the on-screen card (for the push-in), but never larger than the source.
        out_w = min(round(_CARD_WIDTH * 1.5), w)
        sharp = _cover(img, (out_w, round(out_w / card_aspect)), focus_y=0.4)
    sharp.save(assets_dir / "photo.jpg", format="JPEG", quality=88)

    # Atmosphere: half-resolution is plenty once blurred (the template scales it up).
    atmo = _cover(img, (round(FRAME[0] * _OVERSCAN / 2), round(FRAME[1] * _OVERSCAN / 2)), focus_y=0.4)
    atmo = atmo.filter(ImageFilter.GaussianBlur(14))
    atmo = ImageEnhance.Color(atmo).enhance(0.75)
    atmo = Image.blend(atmo, Image.new("RGB", atmo.size, _NAVY), 0.5)
    # A bright photo (a product on white, a daytime sky) must still end up dark
    # enough to carry white type, whatever it started as.
    luma = ImageStat.Stat(atmo.convert("L")).mean[0]
    if luma > _ATMO_MAX_LUMA:
        atmo = ImageEnhance.Brightness(atmo).enhance(_ATMO_MAX_LUMA / luma)
    atmo.save(assets_dir / "photo_bg.jpg", format="JPEG", quality=80)

    return {
        "mode": mode,
        "src": "assets/photo.jpg",
        "bg": "assets/photo_bg.jpg",
        "card_height": card_height,
    }
