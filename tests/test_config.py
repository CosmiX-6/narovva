from __future__ import annotations

import pytest
from pydantic import ValidationError

from narovva.config import load_all_channels, load_channel
from narovva.config.schema import ChannelConfig


def test_load_example_channel():
    channel = load_channel("config/channels/example-tech-ig.yaml")
    assert channel.id == "example-tech-ig"
    assert channel.platform == "instagram"
    assert [g.genre for g in channel.genres] == ["tech", "ai"]
    assert channel.brand.name == "Example Tech Daily"


def test_id_defaults_to_filename_stem(tmp_path):
    path = tmp_path / "my-channel.yaml"
    path.write_text(
        "platform: instagram\n"
        "genres:\n  - genre: tech\n"
        "brand:\n  name: Test\n"
    )
    channel = load_channel(path)
    assert channel.id == "my-channel"


def test_requires_at_least_one_genre(tmp_path):
    path = tmp_path / "empty-genres.yaml"
    path.write_text("platform: instagram\ngenres: []\nbrand:\n  name: Test\n")
    with pytest.raises(ValidationError):
        load_channel(path)


def test_rejects_non_slug_id(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "id: 'not a slug!'\nplatform: instagram\n"
        "genres:\n  - genre: tech\n"
        "brand:\n  name: Test\n"
    )
    with pytest.raises(ValidationError):
        load_channel(path)


def test_load_all_channels_rejects_duplicate_ids(tmp_path):
    for name in ("a.yaml", "b.yaml"):
        (tmp_path / name).write_text(
            "id: dup\nplatform: instagram\n"
            "genres:\n  - genre: tech\n"
            "brand:\n  name: Test\n"
        )
    with pytest.raises(ValueError, match="duplicate channel id"):
        load_all_channels(tmp_path)


def test_load_all_channels_empty_dir_returns_empty_list(tmp_path):
    assert load_all_channels(tmp_path / "does-not-exist") == []


def test_brand_kit_maps_to_poster_core():
    channel = load_channel("config/channels/example-tech-ig.yaml")
    brand = channel.brand.to_poster_core()
    assert brand.accent_color == channel.brand.accent_color
    assert brand.font_path_bold == channel.brand.font_path_bold
