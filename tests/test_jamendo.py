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


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    # pick_track retries with a real time.sleep backoff between attempts;
    # tests exercise that path deliberately, so keep them fast.
    monkeypatch.setattr(jamendo_module.time, "sleep", lambda s: None)


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

    def fake_get(url, **kwargs):
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


def test_pick_track_retries_a_tag_before_giving_up_on_it(monkeypatch):
    """Jamendo's search index is eventually-consistent -- the same query
    can return zero results on one call and real results on the next."""
    call_count = {"n": 0}

    def fake_get(url, **kwargs):
        if url.endswith("/tracks/"):
            call_count["n"] += 1
            if call_count["n"] < 3:
                return _FakeResponse(json_data={"results": []})
            return _FakeResponse(json_data={
                "results": [{
                    "id": 9, "audiodownload_allowed": True, "audiodownload": "https://x/9.mp3",
                    "name": "Eventually Found", "artist_name": "Artist", "license_ccurl": "https://cc/by/3.0",
                }]
            })
        return _FakeResponse(content=b"bytes")

    monkeypatch.setattr(jamendo_module.httpx, "get", fake_get)

    track = JamendoMusicClient(client_id="fake-id").pick_track(["technology"])
    assert track.name == "Eventually Found"
    assert call_count["n"] == 3


def test_pick_track_falls_back_to_untagged_search_when_all_tags_empty(monkeypatch):
    seen_tags = []

    def fake_get(url, **kwargs):
        if url.endswith("/tracks/"):
            params = kwargs.get("params", {})
            seen_tags.append(params.get("fuzzytags"))
            if params.get("fuzzytags") is None:
                return _FakeResponse(json_data={
                    "results": [{
                        "id": 1, "audiodownload_allowed": True, "audiodownload": "https://x/1.mp3",
                        "name": "Generic Track", "artist_name": "Someone", "license_ccurl": "https://cc/by/3.0",
                    }]
                })
            return _FakeResponse(json_data={"results": []})
        return _FakeResponse(content=b"bytes")

    monkeypatch.setattr(jamendo_module.httpx, "get", fake_get)

    track = JamendoMusicClient(client_id="fake-id").pick_track(["technology", "corporate"])

    assert track.name == "Generic Track"
    assert seen_tags == ["technology", "technology", "technology", "technology",
                          "corporate", "corporate", "corporate", "corporate", None]


def test_pick_track_raises_when_nothing_found_anywhere(monkeypatch):
    def fake_get(url, **kwargs):
        return _FakeResponse(json_data={"results": []})

    monkeypatch.setattr(jamendo_module.httpx, "get", fake_get)

    with pytest.raises(JamendoError):
        JamendoMusicClient(client_id="fake-id").pick_track(["technology"])


def test_pick_track_sends_commercial_and_derivative_safe_filters(monkeypatch):
    captured = []

    def fake_get(url, **kwargs):
        if url.endswith("/tracks/"):
            captured.append(kwargs.get("params", {}))
            return _FakeResponse(json_data={"results": []})
        return _FakeResponse(content=b"")

    monkeypatch.setattr(jamendo_module.httpx, "get", fake_get)

    with pytest.raises(JamendoError):
        JamendoMusicClient(client_id="fake-id").pick_track(["technology"])

    assert all(p["ccnc"] == "false" for p in captured)
    assert all(p["ccnd"] == "false" for p in captured)
    assert captured[0]["fuzzytags"] == "technology"
