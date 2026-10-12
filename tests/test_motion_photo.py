from __future__ import annotations

import random

from PIL import Image

from narovva.motion.photo import prepare_photo
from narovva.motion.sample import write_sample_photo


def _noise(path, size):
    """A stand-in for a real photograph: plenty of tonal variety."""
    rnd = random.Random(3)
    small = Image.new("RGB", (48, 48))
    small.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(48 * 48)])
    small.resize(size, Image.Resampling.BICUBIC).save(path, format="JPEG")
    return path


def test_landscape_photo_becomes_a_card_plus_atmosphere(tmp_path):
    photo = prepare_photo(write_sample_photo(tmp_path / "in.jpg"), tmp_path / "assets")
    assert photo["mode"] == "card" and photo["src"] == "assets/photo.jpg" and photo["bg"] == "assets/photo_bg.jpg"
    with Image.open(tmp_path / "assets" / "photo.jpg") as sharp:
        assert sharp.width <= 1200                      # never upscaled past the source
        assert abs(sharp.width / sharp.height - 858 / photo["card_height"]) < 0.02
    with Image.open(tmp_path / "assets" / "photo_bg.jpg") as atmo:
        assert abs(atmo.width / atmo.height - 9 / 16) < 0.01


def test_card_is_never_taller_than_the_headline_can_spare(tmp_path):
    photo = prepare_photo(_noise(tmp_path / "sq.jpg", (900, 900)), tmp_path / "assets")
    assert photo["mode"] == "card" and photo["card_height"] <= 592


def test_large_portrait_photo_goes_full_bleed(tmp_path):
    photo = prepare_photo(_noise(tmp_path / "tall.jpg", (1400, 2400)), tmp_path / "assets")
    assert photo["mode"] == "full" and photo["card_height"] is None
    with Image.open(tmp_path / "assets" / "photo.jpg") as sharp:
        assert sharp.size == (1188, 2112)


def test_unusable_photos_are_rejected(tmp_path):
    assets = tmp_path / "assets"
    assert prepare_photo(_noise(tmp_path / "tiny.jpg", (320, 180)), assets) is None       # too small
    assert prepare_photo(_noise(tmp_path / "strip.jpg", (2400, 400)), assets) is None     # banner-shaped
    logo = Image.new("RGB", (1200, 630), "white")
    logo.paste(Image.new("RGB", (220, 120), (200, 30, 30)), (490, 255))
    logo.save(tmp_path / "logo.png")
    assert prepare_photo(tmp_path / "logo.png", assets) is None                           # a logo on a flat field
    (tmp_path / "broken.jpg").write_bytes(b"not an image")
    assert prepare_photo(tmp_path / "broken.jpg", assets) is None
    assert prepare_photo(tmp_path / "missing.jpg", assets) is None
    assert not assets.exists()                                                            # nothing half-written


def test_atmosphere_is_dark_enough_for_type_even_from_a_bright_photo(tmp_path):
    from PIL import ImageStat

    bright = Image.new("RGB", (1200, 630), (250, 250, 250))             # a product shot on white
    bright.paste(Image.new("RGB", (520, 400), (40, 90, 200)), (340, 115))
    bright.save(tmp_path / "bright.jpg")
    assert prepare_photo(tmp_path / "bright.jpg", tmp_path / "assets")["mode"] == "card"
    with Image.open(tmp_path / "assets" / "photo_bg.jpg") as atmo:
        assert ImageStat.Stat(atmo.convert("L")).mean[0] <= 60
