from __future__ import annotations

import pytest

from narovva.music import jamendo as jamendo_module
from narovva.music.jamendo import JamendoError, JamendoMusicClient, music_tags_for_genre


class _FakeResponse:
    def __init__(self, json_data=None, content=b""):
        self._json_data = json_data
        self.content = content

    def raise_for_status(self):
        pass

    def json(self):
        return self._json_data


def test_music_tags_for_genre_known_and_fallback():
    assert music_tags_for_genre("tech") == ["technology", "corporate", "inspiring"]
    assert music_tags_for_genre("some-unregistered-genre") == ["corporate", "inspiring"]


def test_pick_track_skips_tracks_without_download_permission(monkeypatch):
    search_results = {
        "results": [
            {"id": 1, "audiodownload_allowed": False, "audiodownload": "https://x/1.mp3"},
            {
                "id": 2, "audiodownload_allowed": True, "audiodownload": "https://x/2.mp3",
                "name": "Track Two", "artist_name": "Artist Two", "license_ccurl": "https://cc/by/3.0",
            },
        ]
    }

    calls = []

    def fake_get(url, **kwargs):
        calls.append(url)
        if url.endswith("/tracks/"):
            return _FakeResponse(json_data=search_results)
        return _FakeResponse(content=b"fake-mp3-bytes")

    monkeypatch.setattr(jamendo_module.httpx, "get", fake_get)

    client = JamendoMusicClient(client_id="fake-id")
    track = client.pick_track(["technology"])

    assert track.id == "2"
    assert track.name == "Track Two"
    assert track.artist_name == "Artist Two"
    assert track.audio_bytes == b"fake-mp3-bytes"
    assert "Track Two" in track.attribution
    assert "Artist Two" in track.attribution


def test_pick_track_raises_when_no_eligible_track(monkeypatch):
    def fake_get(url, **kwargs):
        return _FakeResponse(json_data={"results": []})

    monkeypatch.setattr(jamendo_module.httpx, "get", fake_get)

    client = JamendoMusicClient(client_id="fake-id")
    with pytest.raises(JamendoError):
        client.pick_track(["technology"])


def test_pick_track_sends_commercial_and_derivative_safe_filters(monkeypatch):
    captured_params = {}

    def fake_get(url, **kwargs):
        if url.endswith("/tracks/"):
            captured_params.update(kwargs.get("params", {}))
            return _FakeResponse(json_data={"results": []})
        return _FakeResponse(content=b"")

    monkeypatch.setattr(jamendo_module.httpx, "get", fake_get)

    client = JamendoMusicClient(client_id="fake-id")
    with pytest.raises(JamendoError):
        client.pick_track(["technology", "corporate"])

    assert captured_params["ccnc"] == "false"
    assert captured_params["ccnd"] == "false"
    assert captured_params["tags"] == "technology+corporate"
