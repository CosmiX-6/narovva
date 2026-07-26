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


class CredentialRefs(BaseModel):
    """Names of environment variables holding secrets, never the secrets
    themselves. Resolved at runtime via narovva.settings.resolve_env."""

    instagram_access_token_env: str | None = None
    instagram_app_id_env: str | None = None
    instagram_app_secret_env: str | None = None
    openai_api_key_env: str | None = None
    gemini_api_key_env: str | None = None


class ChannelConfig(BaseModel):
    id: str
    enabled: bool = True
    platform: Literal["instagram", "x", "threads"] = "instagram"
    ig_business_account_id: str | None = None
    ig_page_id: str | None = None
    genres: list[GenreSetting]
    brand: BrandKitConfig
    caption: CaptionTone = Field(default_factory=CaptionTone)
    credentials: CredentialRefs = Field(default_factory=CredentialRefs)
    text_provider: Literal["openai", "gemini"] = "openai"
    image_provider: Literal["openai", "gemini", "none"] = "openai"

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
