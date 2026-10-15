"""Reel cover (thumbnail): the story's photo, the headline, the category and
the channel logo, on the brand navy.

Instagram shows a reel's cover as a 9:16 image on the Reels tab and crops its
centre 4:5 for the profile grid, so everything that matters (headline, logo)
sits inside the central 1080x1350 band. The article photo is optional: without
a usable one the cover is a branded typographic card."""

from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from ..motion.photo import _MIN_HEIGHT, _MIN_WIDTH, _is_flat_graphic

logger = logging.getLogger(__name__)

W, H = 1080, 1920
_NAVY = (10, 14, 26)
_BAND_TOP, _BAND_BOTTOM = 285, 1635  # the part the profile grid keeps
_MARGIN = 72
_FALLBACK_FONT = "assets/fonts/DejaVuSans-Bold.ttf"


def _hex(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _font(path: str | None, size: int) -> ImageFont.FreeTypeFont:
    for candidate in (path, _FALLBACK_FONT):
        try:
            if candidate:
                return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _fit_headline(draw, text: str, font_path: str | None, max_width: int):
    """Largest size (<=104 px) at which the headline fits 4 lines, else 5."""
    text = " ".join(text.split())
    for max_lines, lo in ((4, 60), (5, 52)):
        for size in range(104, lo - 1, -4):
            font = _font(font_path, size)
            lines = _wrap(draw, text, font, max_width)
            if len(lines) <= max_lines:
                return font, lines
    font = _font(font_path, 52)
    lines = _wrap(draw, text, font, max_width)[:5]
    lines[-1] = lines[-1].rstrip(" ,;:-") + "\u2026"
    return font, lines


def _load_photo(path: str | None) -> Image.Image | None:
    if not path:
        return None
    try:
        with Image.open(path) as raw:
            img = ImageOps.exif_transpose(raw).convert("RGB")
    except Exception as exc:
        logger.info("cover photo skipped: cannot open %s (%s)", path, exc)
        return None
    if img.width < _MIN_WIDTH or img.height < _MIN_HEIGHT or _is_flat_graphic(img):
        logger.info("cover photo skipped: too small or a flat graphic")
        return None
    return img


def make_cover(
    out_path: str, *, headline: str, kicker: str, accent: str, handle: str = "",
    logo_path: str | None = None, photo_path: str | None = None, font_path: str | None = None,
    brand: str = "",
) -> str:
    """Render the cover as a JPEG at `out_path` and return it."""
    ac = _hex(accent)
    canvas = Image.new("RGB", (W, H), _NAVY)
    photo = _load_photo(photo_path)

    if photo is not None:
        # Photo fills the upper ~60%; it fades into the navy where the headline sits.
        top = ImageOps.fit(photo, (W, 1180), Image.Resampling.LANCZOS, centering=(0.5, 0.4))
        top = ImageEnhance.Contrast(top).enhance(1.08)
        canvas.paste(top, (0, 120))
        fade = Image.new("L", (W, H), 0)
        fd = ImageDraw.Draw(fade)
        for y in range(H):
            if y < 120:
                a = 255
            elif y < 520:  # darker under the logo row so it stays legible on any photo
                a = int(170 - 110 * (y - 120) / 400)
            elif y < 760:
                a = 60
            elif y < 1300:
                a = int(60 + (255 - 60) * ((y - 760) / 540) ** 1.4)
            else:
                a = 255
            fd.line([(0, y), (W, y)], fill=min(a, 255))
        canvas = Image.composite(Image.new("RGB", (W, H), _NAVY), canvas, fade)
    else:
        # Typographic card: a soft accent glow instead of a photo.
        glow = Image.new("RGB", (W, H), _NAVY)
        gd = ImageDraw.Draw(glow)
        gd.ellipse((-260, 120, 900, 1280), fill=tuple(int(c * 0.35 + n * 0.65) for c, n in zip(ac, _NAVY)))
        glow = glow.filter(ImageFilter.GaussianBlur(220))
        canvas = glow
        if logo_path and Path(logo_path).exists():  # big faint mark so the card is not empty
            try:
                with Image.open(logo_path) as lg:
                    lg = lg.convert("RGB").resize((520, 520), Image.Resampling.LANCZOS)
                m = Image.new("L", lg.size, 0)
                ImageDraw.Draw(m).rounded_rectangle((0, 0, *lg.size), radius=110, fill=70)
                canvas.paste(lg, ((W - 520) // 2, 560), m)
            except Exception as exc:
                logger.info("cover watermark skipped (%s)", exc)

    draw = ImageDraw.Draw(canvas)

    # Logo, top-left of the safe band.
    if logo_path and Path(logo_path).exists():
        try:
            with Image.open(logo_path) as lg:
                lg = lg.convert("RGB").resize((132, 132), Image.Resampling.LANCZOS)
            mask = Image.new("L", lg.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, *lg.size), radius=30, fill=255)
            canvas.paste(lg, (_MARGIN, _BAND_TOP), mask)
        except Exception as exc:
            logger.info("cover logo skipped (%s)", exc)
    if brand:
        draw.text((_MARGIN + 156, _BAND_TOP + 30), brand.upper(), font=_font(font_path, 36), fill=(255, 255, 255))
        if handle:
            draw.text((_MARGIN + 156, _BAND_TOP + 80), f"@{handle}", font=_font(None, 32), fill=(170, 180, 200))

    # Headline block, bottom-anchored in the safe band.
    max_w = W - 2 * _MARGIN
    font, lines = _fit_headline(draw, headline.upper() if len(headline) < 60 else headline, font_path, max_w)
    line_h = int(font.size * 1.12)
    block_h = line_h * len(lines)
    pill_font = _font(font_path, 38)
    kicker = (kicker or "NEWS").upper()
    pill_w = int(draw.textlength(kicker, font=pill_font)) + 56
    bottom = _BAND_BOTTOM - 40
    y = bottom - block_h
    pill_y = y - 44 - 78
    draw.rounded_rectangle((_MARGIN, pill_y, _MARGIN + pill_w, pill_y + 78), radius=39, fill=ac)
    draw.text((_MARGIN + 28, pill_y + 17), kicker, font=pill_font, fill=(10, 14, 26))
    draw.rectangle((_MARGIN, y - 22, _MARGIN + 120, y - 14), fill=ac)
    for line in lines:
        draw.text((_MARGIN + 3, y + 3), line, font=font, fill=(0, 0, 0))  # shadow for legibility over photos
        draw.text((_MARGIN, y), line, font=font, fill=(255, 255, 255))
        y += line_h

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="JPEG", quality=90)
    return out_path
