"""Channel configuration schema: one validated YAML file per channel."""

from __future__ import annotations

from typing import Literal

from poster_core import BrandKit
from pydantic import BaseModel, Field, field_validator


class BrandKitConfig(BaseModel):
    """Mirrors poster_core.BrandKit, plus the bold/regular font overrides
    narovva needs since Vercel has no system fonts to fall back to."""

    name: str = ""
    accent_color: str = "#E4572E"
    background_color: str = "#12161C"
    text_color: str = "#FFFFFF"
    logo_path: str | None = None
    font_path: str | None = None
    font_path_bold: str | None = None
    font_path_regular: str | None = None
    footer: str | None = None
    # StoryCategory value (e.g. "ai", "science") -> hex. Overrides that
    # category's accent; falls back to poster_core's built-in per-category
    # accent for any category not listed here.
    category_accents: dict[str, str] = Field(default_factory=dict)
    # "@handle"-style social handle, without the "@", used by the deck's
    # closing CTA slide ("Follow @handle for daily breakdowns").
    social_handle: str | None = None

    def to_poster_core(self) -> BrandKit:
        return BrandKit(**self.model_dump())


class CaptionTone(BaseModel):
    voice: str = "informative, concise, no clickbait"
    emoji: bool = True
    max_hashtags: int = 8
    hashtag_style: Literal["footer", "inline", "none"] = "footer"
    extra_hashtags: list[str] = Field(default_factory=list)


class GenreSetting(BaseModel):
    genre: str
    country: str | None = None
    limit: int = 10
    asset_types: list[str] | None = None
    cadence_minutes: int = 720
    # Jamendo search tags used to pick background music for this genre's
    # posts when the channel's publish_format is "reel" (e.g. ["technology",
    # "corporate", "inspiring"]). Falls back to a genre-keyed default in
    # narovva.music.jamendo if unset.
    music_tags: list[str] | None = None


class CredentialRefs(BaseModel):
    """Names of environment variables holding secrets, never the secrets
    themselves. Resolved at runtime via narovva.settings.resolve_env."""

    instagram_access_token_env: str | None = None
    instagram_app_id_env: str | None = None
    instagram_app_secret_env: str | None = None
    openai_api_key_env: str | None = None
    gemini_api_key_env: str | None = None
    jamendo_client_id_env: str | None = None
    elevenlabs_api_key_env: str | None = None
    openrouter_api_key_env: str | None = None


class NarrationConfig(BaseModel):
    """Voice-over for motion reels. A different voice is picked for each video
    from `voices` (defaults per provider) and the music ducks under it. Any
    failure falls back to a music-only reel."""

    provider: Literal["openai", "elevenlabs", "gemini", "kokoro"] = "openai"
    model: str | None = None
    # OpenAI/Gemini voice names, or ElevenLabs voice_ids (required for elevenlabs).
    voices: list[str] | None = None
    # Tried in order if the primary provider fails (each uses its own default voices).
    fallback_providers: list[Literal["openai", "elevenlabs", "gemini", "kokoro"]] = Field(default_factory=list)
    # Burn the spoken line into the picture, word by word, so the reel still
    # reads with the sound off.
    captions: bool = True


_DEFAULT_VIRAL_EXCLUDE = [
    # Not "informative": results, previews, gossip, luck. Matched as whole words in the headline.
    "vs", "v", "score", "scores", "highlights", "prediction", "predictions", "odds", "betting",
    "lottery", "jackpot", "horoscope", "nfl", "nba", "wnba", "mlb", "nhl", "ufc", "ipl",
    "premier league", "serie a", "la liga", "champions league", "box office", "dating",
    "red carpet", "net worth", "live stream", "watch live", "recap",
]


class ViralConfig(BaseModel):
    """Extra posts for the story the internet is talking about right now, whatever
    its genre. Slots are local times in `timezone`; each slot is one post, and a
    missed slot is made up in the next one, so the channel gets at least
    len(slots) viral posts a day when fresh stories exist."""

    enabled: bool = False
    timezone: str = "UTC"
    slots: list[str] = Field(default_factory=lambda: ["09:00", "13:00", "19:00", "21:30"])
    # A slot can fire this long after its start (the hourly scheduler is often late).
    slot_window_minutes: int = 120
    # "Fresh": every counted report of the story is at most this old.
    max_age_minutes: int = 240
    # A story counts as viral when at least this many different outlets carry it.
    min_sources: int = 2
    # Google Trends "trending now" regions; a story matching a hot search gets a boost.
    trends_geos: list[str] = Field(default_factory=lambda: ["US"])
    # News feeds scanned for coverage bursts. Unset = narovva's built-in pool.
    feeds: list[str] | None = None
    extra_feeds: list[str] = Field(default_factory=list)
    # Also scan the feeds behind this channel's own genres.
    include_genre_feeds: bool = True
    exclude_keywords: list[str] = Field(default_factory=lambda: list(_DEFAULT_VIRAL_EXCLUDE))
    # How many top-scored stories the AI editor chooses from.
    editor_candidates: int = 12
    # The opening line: "curiosity" opens a question only the story answers, "stakes"
    # says what is at risk for the viewer, "auto" lets the model pick per story.
    hook_style: Literal["auto", "curiosity", "stakes"] = "auto"
    asset_types: list[str] | None = Field(default_factory=lambda: ["cover", "carousel"])
    music_tags: list[str] | None = None
    # Separate posts by at least this long (a viral post right after a rotation post).
    min_gap_minutes: int = 45

    @field_validator("slots")
    @classmethod
    def _valid_slots(cls, v: list[str]) -> list[str]:
        out = []
        for s in v:
            hh, _, mm = str(s).partition(":")
            if not (hh.isdigit() and mm.isdigit() and 0 <= int(hh) < 24 and 0 <= int(mm) < 60):
                raise ValueError(f"viral slot must be HH:MM, got {s!r}")
            out.append(f"{int(hh):02d}:{int(mm):02d}")
        return sorted(set(out))

    @field_validator("timezone")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {v!r}") from exc
        return v


class ChannelConfig(BaseModel):
    id: str
    enabled: bool = True
    platform: Literal["instagram", "x", "threads"] = "instagram"
    ig_business_account_id: str | None = None
    ig_page_id: str | None = None
    # When set, overrides each genre's own cadence_minutes: the channel
    # posts at most one item every rotation_minutes, cycling through
    # `genres` in order so consecutive posts alternate genres.
    rotation_minutes: int | None = None
    genres: list[GenreSetting]
    brand: BrandKitConfig
    caption: CaptionTone = Field(default_factory=CaptionTone)
    credentials: CredentialRefs = Field(default_factory=CredentialRefs)
    text_provider: Literal["openai", "gemini"] = "openai"
    # Text-model fallback chain, tried in order ("provider[:model]"; providers
    # gemini, openai, openrouter). Unset = just `text_provider`. Free-tier quotas
    # are per model, so listing several Gemini models gives several pools.
    llm_chain: list[str] | None = None
    image_provider: Literal["openai", "gemini", "none"] = "openai"
    # "carousel" (default): post poster-core's rendered images directly.
    # "reel": assemble those same images into a short Ken-Burns video with
    # a genre-matched royalty-free music track and publish as a Reel.
    # "motion_reel": like "reel", but the slides are re-built as HyperFrames
    # motion graphics (narovva.motion). Falls back to the plain "reel" if the
    # motion render fails, so a post is never skipped.
    publish_format: Literal["carousel", "reel", "motion_reel"] = "carousel"
    # Voice-over for "motion_reel" (ignored by other formats). Unset = music only.
    narration: NarrationConfig | None = None
    # Peak-hour posts of whatever story is going viral right now (any genre).
    viral: ViralConfig | None = None

    @property
    def is_video(self) -> bool:
        """True for any format published as a Reel (needs music + video)."""
        return self.publish_format in ("reel", "motion_reel")

    @field_validator("genres")
    @classmethod
    def _require_at_least_one_genre(cls, v: list[GenreSetting]) -> list[GenreSetting]:
        if not v:
            raise ValueError("a channel needs at least one genre")
        return v

    @field_validator("id")
    @classmethod
    def _slug_id(cls, v: str) -> str:
        if not v or not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError(f"channel id must be a slug (letters/digits/-/_), got {v!r}")
        return v
