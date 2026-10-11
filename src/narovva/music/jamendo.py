"""Background music selection via the Jamendo API v3
(https://developer.jamendo.com/v3.0) -- searches Jamendo's Creative Commons
catalog for a track matching an article's topic and mood, restricted to
tracks whose license permits commercial use and modification (trimming/
fading to fit a Reel), for genre-and-sentiment-matched royalty-free
soundtracks."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

import httpx

_API_BASE = "https://api.jamendo.com/v3.0"

# One topical tag per info-snipe genre key, for search relevance -- paired
# with a mood tag list below rather than driving the pick on its own, so
# two articles in the same genre don't always reach for the same track.
_TOPIC_TAG_BY_GENRE: dict[str, str] = {
    "tech": "technology",
    "ai": "technology",
    "gaming": "electronic",
    "world": "cinematic",
    "business": "corporate",
    "science": "ambient",
}

# Mood tags per poster_core.models.ContentBrief.tone -- a launch/win reads
# as "celebratory" and gets an upbeat, energetic lift; a disaster/loss
# reads as "sombre" and gets something soft; routine analysis stays
# corporate and unobtrusive so the news itself stays the focus.
_MOOD_TAGS_BY_TONE: dict[str, list[str]] = {
    "urgent": ["cinematic", "intense", "energetic"],
    "celebratory": ["upbeat", "energetic", "uplifting"],
    "sombre": ["ambient", "piano", "melancholic"],
    "analytical": ["corporate", "minimal", "focus"],
    "inspiring": ["inspiring", "uplifting", "cinematic"],
    "neutral": ["corporate", "inspiring"],
}


# Finer sentiment signals from the brief: substring of a ContentBrief.emotions
# entry -> extra mood tags, and StoryCategory value -> extra tags. These come
# after the tone's tags, so the tone still leads and these widen the pool.
_MOOD_TAGS_BY_EMOTION: dict[str, list[str]] = {
    "excit": ["upbeat"], "joy": ["upbeat"], "optim": ["uplifting"], "hope": ["uplifting"],
    "fear": ["dark", "tense"], "anx": ["tense"], "alarm": ["tense", "dark"], "concern": ["tense"],
    "sad": ["melancholic", "piano"], "loss": ["melancholic"], "grief": ["piano"],
    "anger": ["intense"], "outrage": ["intense"],
    "curio": ["inspiring", "ambient"], "wonder": ["ambient", "inspiring"], "surpris": ["cinematic"],
    "skeptic": ["minimal"], "doubt": ["minimal"],
}
_TAGS_BY_CATEGORY: dict[str, list[str]] = {
    "disaster": ["cinematic", "dark"], "breaking": ["cinematic", "intense"],
    "product_launch": ["upbeat", "electronic"], "finance": ["corporate"],
    "science": ["ambient"], "health": ["ambient", "piano"], "sports": ["energetic"],
}


def music_tags_for(
    genre: str, tone: str, emotions: list[str] | tuple[str, ...] = (), category: str | None = None,
) -> list[str]:
    """Topical tag first (for relevance) then the tone's mood tags (for vibe),
    then extras from the brief's emotions and category (wider pool),
    de-duplicated in order."""
    topic = _TOPIC_TAG_BY_GENRE.get(genre)
    mood = _MOOD_TAGS_BY_TONE.get(tone, _MOOD_TAGS_BY_TONE["neutral"])
    extras: list[str] = []
    for emotion in emotions:
        for key, key_tags in _MOOD_TAGS_BY_EMOTION.items():
            if key in emotion.lower():
                extras.extend(key_tags)
    extras.extend(_TAGS_BY_CATEGORY.get(category or "", []))
    tags = ([topic] if topic else []) + mood + extras
    seen: set[str] = set()
    ordered: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            ordered.append(t)
    return ordered


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


_RESULTS_PER_QUERY = 30
_ATTEMPTS_PER_TAG = 4
_RETRY_BACKOFF_SECONDS = 1.0


class JamendoMusicClient:
    def __init__(self, client_id: str, timeout: float = 30.0):
        self._client_id = client_id
        self._timeout = timeout

    def pick_track(self, tags: list[str], exclude_ids: set[str] | frozenset[str] = frozenset()) -> MusicTrack:
        """Picks a track whose id is not in `exclude_ids` (recently used
        ones), so consecutive posts get different music. Only the very last
        untagged fallback may repeat a track, rather than failing the post.

        Tries each tag in turn (Jamendo's own index appears to be
        eventually-consistent -- the exact same query can return zero
        results one call and several the next, so each tag is retried a
        few times before moving on), then falls back to an untagged
        popularity-sorted search rather than failing the whole post."""
        for tag in [*tags, None]:
            track = self._search_and_download(tag, exclude_ids)
            if track is not None:
                return track
        track = self._search_and_download(None, frozenset())
        if track is not None:
            return track
        raise JamendoError(f"no commercially-usable Jamendo track found for tags {tags!r} (or untagged fallback)")

    def _search_and_download(self, tag: str | None, exclude_ids: set[str] | frozenset[str]) -> MusicTrack | None:
        params = {
            "client_id": self._client_id,
            "format": "json",
            "limit": _RESULTS_PER_QUERY,
            "ccnc": "false",  # exclude tracks that forbid commercial use
            "ccnd": "false",  # exclude tracks that forbid derivatives (we trim/fade)
            "audioformat": "mp32",
            "order": "popularity_total",
        }
        if tag:
            params["fuzzytags"] = tag

        for attempt in range(_ATTEMPTS_PER_TAG):
            resp = httpx.get(f"{_API_BASE}/tracks/", params=params, timeout=self._timeout)
            resp.raise_for_status()
            results = resp.json().get("results", [])
            # order=popularity_total makes the query deterministic, so
            # without shuffling the same tag always returns the same track
            # first -- every post in a genre ends up with identical music.
            random.shuffle(results)
            for track in results:
                download_url = track.get("audiodownload")
                if not track.get("audiodownload_allowed", True) or not download_url:
                    continue
                if str(track["id"]) in exclude_ids:
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
            if attempt < _ATTEMPTS_PER_TAG - 1:
                time.sleep(_RETRY_BACKOFF_SECONDS)
        return None
