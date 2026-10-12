import logging

from PIL import Image

from narovva.logsafe import RedactFilter, redact
from narovva.video import make_cover

TOKEN = "IGAAO6DSRfh6RBZAGFJQ05hUDBMSlZAkRVAwZA1ZAoZA0k1S3dpZA2FJd0pKODdlUHpSZAzNEa3o2bjM1X01XZA2F2ZAGw4eWZALR1EzODlTeDJuajhZAZAExKZATNqajNyQkxDTzVWY3NHWko5Q1VhVDJxc0JyMTc5ZAUVB"


def test_redact_removes_tokens_from_urls_headers_and_bare_strings():
    url = f"GET https://graph.instagram.com/v21.0/me?fields=id&access_token={TOKEN} 200"
    assert TOKEN not in redact(url) and "fields=id" in redact(url)
    assert "sk-" not in redact("key sk-abcdefghijklmnopqrstuvwxyz0123456789") .replace("sk-***", "")
    assert "abcdef" not in redact("Authorization: Bearer abcdefghijklmnop1234")
    assert TOKEN not in redact(f"failed with {TOKEN} inside")
    assert redact("nothing secret here") == "nothing secret here"


def test_log_filter_redacts_formatted_records():
    rec = logging.LogRecord("x", logging.INFO, "f", 1, "GET %s", (f"https://g/?access_token={TOKEN}",), None)
    assert RedactFilter().filter(rec)
    assert TOKEN not in rec.getMessage()


def test_make_cover_with_and_without_photo(tmp_path):
    photo = tmp_path / "p.jpg"
    img = Image.effect_noise((1200, 630), 80).convert("RGB")
    img.save(photo)
    for src in (str(photo), None):
        out = make_cover(
            str(tmp_path / f"c{bool(src)}.jpg"), headline="A fairly long headline about moon cities and drones",
            kicker="technology", accent="#EC4899", handle="contextunfiltered",
            logo_path="assets/logo/CU.png", photo_path=src, font_path="assets/fonts/DejaVuSans-Bold.ttf",
            brand="CONTEXT UNFILTERED",
        )
        with Image.open(out) as c:
            assert c.size == (1080, 1920)
