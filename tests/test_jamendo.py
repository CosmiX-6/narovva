from __future__ import annotations

import pytest

from narovva.music import jamendo as jamendo_module
from narovva.music.jamendo import JamendoError, JamendoMusicClient, music_tags_for


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


def test_music_tags_for_combines_topic_and_mood():
    assert music_tags_for("tech", "neutral") == ["technology", "corporate", "inspiring"]
    assert music_tags_for("tech", "celebratory") == ["technology", "upbeat", "energetic", "uplifting"]
    assert music_tags_for("tech", "sombre") == ["technology", "ambient", "piano", "melancholic"]


def test_music_tags_for_unknown_genre_and_tone_fall_back():
    assert music_tags_for("some-unregistered-genre", "unknown-tone") == ["corporate", "inspiring"]


def test_music_tags_for_dedupes_overlapping_topic_and_mood_tags():
    # "science" genre's topic tag ("ambient") also appears in the "sombre"
    # mood list -- it should only appear once, not be duplicated.
    tags = music_tags_for("science", "sombre")
    assert tags == ["ambient", "piano", "melancholic"]


def test_pick_track_varies_across_calls_instead_of_always_the_top_result(monkeypatch):
    """order=popularity_total makes Jamendo's own ranking deterministic;
    without client-side shuffling every post in a genre would reach for
    the exact same track."""
    search_results = {
        "results": [
            {
                "id": i, "audiodownload_allowed": True, "audiodownload": f"https://x/{i}.mp3",
                "name": f"Track {i}", "artist_name": "Artist", "license_ccurl": "https://cc/by/3.0",
            }
            for i in range(1, 11)
        ]
    }

    def fake_get(url, **kwargs):
        if url.endswith("/tracks/"):
            return _FakeResponse(json_data=search_results)
        return _FakeResponse(content=b"bytes")

    monkeypatch.setattr(jamendo_module.httpx, "get", fake_get)

    names = {JamendoMusicClient(client_id="fake-id").pick_track(["technology"]).name for _ in range(20)}
    assert len(names) > 1, "expected varied track picks across repeated calls, got the same one every time"


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


def test_music_tags_for_adds_emotion_and_category_extras_after_tone():
    tags = music_tags_for("tech", "urgent", ["Anxiety about layoffs"], "disaster")
    assert tags[:4] == ["technology", "cinematic", "intense", "energetic"]
    assert "tense" in tags and "dark" in tags
    assert len(tags) == len(set(tags))
    # unchanged when no extras are given
    assert music_tags_for("tech", "neutral") == ["technology", "corporate", "inspiring"]


def test_pick_track_skips_recently_used_tracks(monkeypatch):
    results = [
        {"id": 1, "name": "Old", "artist_name": "A", "license_ccurl": "u", "audiodownload": "http://x/1"},
        {"id": 2, "name": "Fresh", "artist_name": "B", "license_ccurl": "u", "audiodownload": "http://x/2"},
    ]

    def fake_get(url, **kw):
        if url.endswith("/tracks/"):
            return _FakeResponse(json_data={"results": list(results)})
        return _FakeResponse(content=b"mp3")

    monkeypatch.setattr(jamendo_module.httpx, "get", fake_get)
    for _ in range(10):  # shuffled order must never matter
        track = JamendoMusicClient("cid").pick_track(["technology"], exclude_ids={"1"})
        assert track.id == "2"


def test_pick_track_repeats_only_as_last_resort(monkeypatch):
    only = [{"id": 1, "name": "Only", "artist_name": "A", "license_ccurl": "u", "audiodownload": "http://x/1"}]

    def fake_get(url, **kw):
        if url.endswith("/tracks/"):
            return _FakeResponse(json_data={"results": list(only)})
        return _FakeResponse(content=b"mp3")

    monkeypatch.setattr(jamendo_module.httpx, "get", fake_get)
    assert JamendoMusicClient("cid").pick_track(["technology"], exclude_ids={"1"}).id == "1"
