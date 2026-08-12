"""Background music selection via the Jamendo API v3
(https://developer.jamendo.com/v3.0) -- searches Jamendo's Creative Commons
catalog for a track matching a genre's mood tags, restricted to tracks whose
license permits commercial use and modification (trimming/fading to fit a
Reel), for genre-matched royalty-free soundtracks."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

_API_BASE = "https://api.jamendo.com/v3.0"

# Default Jamendo search tags per info-snipe genre key, used when a
# channel's GenreSetting doesn't set its own music_tags.
_DEFAULT_TAGS_BY_GENRE: dict[str, list[str]] = {
    "tech": ["technology", "corporate", "inspiring"],
    "ai": ["technology", "electronic", "inspiring"],
    "gaming": ["electronic", "energetic"],
    "world": ["cinematic", "ambient"],
    "business": ["corporate", "inspiring"],
    "science": ["ambient", "inspiring"],
}
_FALLBACK_TAGS = ["corporate", "inspiring"]


def music_tags_for_genre(genre: str) -> list[str]:
    return _DEFAULT_TAGS_BY_GENRE.get(genre, _FALLBACK_TAGS)


@dataclass
class MusicTrack:
    id: str
    name: str
    artist_name: str
    license_ccurl: str
    audio_bytes: bytes

    @property
    def attribution(self) -> str:
        return f"\U0001f3b5 \"{self.name}\" by {self.artist_name} (Jamendo, {self.license_ccurl})"


class JamendoError(RuntimeError):
    """Raised when no eligible track can be found or downloaded."""


class JamendoMusicClient:
    def __init__(self, client_id: str, timeout: float = 30.0):
        self._client_id = client_id
        self._timeout = timeout

    def pick_track(self, tags: list[str]) -> MusicTrack:
        params = {
            "client_id": self._client_id,
            "format": "json",
            "limit": 10,
            "tags": "+".join(tags),
            "ccnc": "false",  # exclude tracks that forbid commercial use
            "ccnd": "false",  # exclude tracks that forbid derivatives (we trim/fade)
            "audioformat": "mp32",
            "order": "popularity_total",
        }
        resp = httpx.get(f"{_API_BASE}/tracks/", params=params, timeout=self._timeout)
        resp.raise_for_status()
        results = resp.json().get("results", [])

        for track in results:
            download_url = track.get("audiodownload")
            if not track.get("audiodownload_allowed", True) or not download_url:
                continue
            audio_resp = httpx.get(download_url, timeout=self._timeout, follow_redirects=True)
            audio_resp.raise_for_status()
            return MusicTrack(
                id=str(track["id"]),
                name=track.get("name") or "Untitled",
                artist_name=track.get("artist_name") or "Unknown artist",
                license_ccurl=track.get("license_ccurl") or "",
                audio_bytes=audio_resp.content,
            )
        raise JamendoError(f"no commercially-usable Jamendo track found for tags {tags!r}")
