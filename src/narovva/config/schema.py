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


class NarrationConfig(BaseModel):
    """Voice-over for motion reels. A different voice is picked for each video
    from `voices` (defaults per provider) and the music ducks under it. Any
    failure falls back to a music-only reel."""

    provider: Literal["openai", "elevenlabs", "gemini"] = "openai"
    model: str | None = None
    # OpenAI/Gemini voice names, or ElevenLabs voice_ids (required for elevenlabs).
    voices: list[str] | None = None


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
