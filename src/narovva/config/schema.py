"""Channel configuration schema: one validated YAML file per channel."""

from __future__ import annotations

from typing import Literal

from poster_core import BrandKit
from pydantic import BaseModel, Field, field_validator, model_validator


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
    # Voices never to use, whichever provider reads (e.g. a Kokoro fallback voice).
    exclude_voices: list[str] = Field(default_factory=list)
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


_AI_TERMS = [
    "ai", "a.i.", "llm", "llms", "gpt", "chatgpt", "openai", "anthropic", "claude", "gemini", "copilot",
    "cursor", "agent", "agents", "agentic", "model", "models", "hugging face", "huggingface", "llama",
    "mistral", "deepseek", "qwen", "rag", "fine-tuning", "fine tuning", "prompt", "prompts", "inference",
    "transformer", "embedding", "embeddings", "machine learning", "neural", "genai", "generative",
    "codex", "mcp", "nvidia", "gpu", "gpus", "vibe coding", "chatbot", "assistant", "automation",
]
_FOCUS_EXCLUDE = [
    # Money and drama, not something the viewer can use at work.
    "raises", "funding round", "valuation", "ipo", "stock", "shares", "earnings", "lawsuit", "sues",
    "layoffs", "acquires", "acquisition",
]


class VoiceConfig(BaseModel):
    """The channel's voice, given to every writer (hook, cover, caption, storyboard,
    script, editors). `banned_words` is also enforced in code on the hook, the cover
    and the caption."""

    # One specific person, not "creators" or "everyone".
    audience: str = ""
    banned_words: list[str] = Field(default_factory=list)
    house_phrases: list[str] = Field(default_factory=list)
    never_claim: list[str] = Field(default_factory=list)
    format: str = ""


class HooksConfig(BaseModel):
    """Formula hooks with a packaged cover and caption opener (narovva.hooks). Viral
    posts always get one; `enabled` adds them to every regular post too."""

    enabled: bool = False
    # Preferred formula ids from narovva/hooks/formulas.yaml (unset = all of them).
    formulas: list[str] | None = None
    # Hooks scoring below this (0-100, narovva.hooks.score) are rejected.
    min_score: int = 45
    # Options the model writes per post, each from a different formula.
    candidates: int = 5

    @field_validator("formulas")
    @classmethod
    def _known_formulas(cls, v: list[str] | None) -> list[str] | None:
        if v:
            from ..hooks.score import formulas_by_id

            unknown = sorted(set(v) - set(formulas_by_id()))
            if unknown:
                raise ValueError(f"unknown hook formula(s) {unknown}; see narovva/hooks/formulas.yaml")
        return v


class FocusConfig(BaseModel):
    """A temporary editorial focus: while enabled, the channel posts only stories for
    `audience` -- the rotation uses `genres` instead of the channel's own, viral posts
    must match `include_keywords`, and an AI screener ranks articles by how useful they
    are to that audience. Turn it off (enabled: false) to go back to the normal mix."""

    enabled: bool = False
    name: str = "focus"
    audience: str = ""
    # Replaces the channel's genres while the focus is on.
    genres: list[GenreSetting] = Field(default_factory=list)
    # A story must mention at least one of these (whole words/phrases, title or summary).
    include_keywords: list[str] = Field(default_factory=lambda: list(_AI_TERMS))
    exclude_keywords: list[str] = Field(default_factory=lambda: list(_FOCUS_EXCLUDE))
    # Skip articles older than this (feeds such as blogs and changelogs keep old posts).
    max_age_hours: int = 48
    # Rank the fresh articles with the text model by usefulness to `audience`.
    screen_with_llm: bool = True
    # Overrides for the caption while the focus is on (unset = keep the channel's).
    caption_voice: str | None = None
    extra_hashtags: list[str] | None = None


class HudConfig(BaseModel):
    """The header across the top of a motion reel."""

    # case_file: "● REC  CASE FILE: STARLINK ........ 00:00:04:29", progress bar on the top edge.
    # breakdown: "● STARLINK BREAKDOWN ........ 24 OCT 2026", progress line under it.
    # brand: the channel logo and name (the original header). none: no header.
    style: Literal["case_file", "breakdown", "brand", "none"] = "case_file"
    # Header text; unset = the style's own. Placeholders: {subject} (what the story is
    # about in 1-3 words, chosen by the script writer, else the brief's main entity,
    # else the category), {category}, {brand}, {date}. Always shown in capitals.
    label: str | None = None
    # Right-hand side: a running timecode, the story's date, or nothing. Unset = the style's own.
    meta: Literal["timecode", "date", "none"] | None = None
    # The blinking red recording dot before the label.
    rec_dot: bool = True


class MotionCaptionStyle(BaseModel):
    """How the burned-in voice-over captions look (switched on/off by narration.captions)."""

    # karaoke: a few words at a time in bold capitals, the word being spoken lit in `highlight`.
    # pill: the whole line, words appearing as they are said, the key phrase on a `highlight` pill.
    # brighten: the whole line, each word brightening as it is said.
    style: Literal["karaoke", "pill", "brighten"] = "karaoke"
    highlight: str = "#FACC15"
    # karaoke only: most words on screen at once (a chunk also ends at punctuation).
    chunk_words: int = Field(3, ge=1, le=6)


class StampConfig(BaseModel):
    """Verdict stamps ("BLOCKED", "FALSE", "-20%") slammed onto the evidence. The
    script writer proposes them only where a slide's own data supports one, and
    any number in a stamp must appear in that slide's data."""

    enabled: bool = True
    max_per_reel: int = Field(3, ge=0, le=8)
    negative_color: str = "#F43F5E"
    positive_color: str = "#22C55E"
    neutral_color: str = "#FACC15"


class StoryConfig(BaseModel):
    """How the motion reel tells the story."""

    # storyboard: the script writer directs a purpose-built explainer -- beats of date
    # tracks, cause-and-effect chains, grids, numbers and quotes that build in sync with
    # the voice (hook, context, what happened, fallout, verdict, follow). Falls back to
    # "slides" when its reply doesn't validate.
    # slides: re-animate poster-core's carousel slides, one spoken line each.
    mode: Literal["storyboard", "slides"] = "storyboard"
    max_beats: int = Field(10, ge=5, le=14)
    # Length the writer aims for (Instagram accepts much longer Reels).
    target_seconds: int = Field(45, ge=20, le=90)
    # A full-frame accent wash behind headline numbers, for rhythm between dark scenes.
    flood: bool = True


class MotionStyleConfig(BaseModel):
    """Look of the motion reel ("motion_reel" format); every part can be switched off."""

    story: StoryConfig = Field(default_factory=StoryConfig)
    hud: HudConfig = Field(default_factory=HudConfig)
    # Story progress: on the top edge, under the header, above the footer, or hidden.
    # auto = top for case_file, hud for breakdown, bottom otherwise.
    progress: Literal["auto", "top", "hud", "bottom", "none"] = "auto"
    captions: MotionCaptionStyle = Field(default_factory=MotionCaptionStyle)
    stamps: StampConfig = Field(default_factory=StampConfig)
    # cards: dated evidence cards that build up one by one (newest lit, earlier ones dimmed).
    # spine: a vertical line with a travelling dot.
    timeline: Literal["cards", "spine"] = "cards"
    # Colour the key word(s) of each headline (chosen by the script writer); figures always are.
    heading_marks: bool = True
    grid: bool = True
    show_handle: bool = True

    @property
    def wants_direction(self) -> bool:
        """True if the look needs the script writer's direction even without a voice-over."""
        label = self.hud.label or ""
        return (self.stamps.enabled and self.stamps.max_per_reel > 0) or self.heading_marks or (
            self.hud.style in ("case_file", "breakdown") and (not label or "{subject}" in label)
        )


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
    # Temporary editorial focus (e.g. "AI for practitioners"); see FocusConfig.
    focus: FocusConfig | None = None
    # The channel's voice (audience, banned words, claims we never make).
    voice: VoiceConfig | None = None
    # Formula hooks + packaged cover/caption opener; see HooksConfig.
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    # Look of "motion_reel": header, captions, stamps, evidence cards (ignored by other formats).
    motion: MotionStyleConfig = Field(default_factory=MotionStyleConfig)

    @property
    def focus_on(self) -> bool:
        return bool(self.focus and self.focus.enabled)

    @property
    def audience(self) -> str:
        """Who the posts are for (a focus overrides the voice's audience) plus the
        voice's house rules, as one block every writer gets."""
        from ..hooks.voice import voice_brief

        who = (self.focus.audience if self.focus_on and self.focus.audience else "") or (
            self.voice.audience if self.voice else "")
        return voice_brief(who, self.voice)

    @property
    def banned_words(self) -> list[str]:
        return list(self.voice.banned_words) if self.voice else []

    @model_validator(mode="after")
    def _apply_focus(self) -> "ChannelConfig":
        if self.focus_on:
            if self.focus.genres:
                self.genres = list(self.focus.genres)
            if self.focus.caption_voice:
                self.caption = self.caption.model_copy(update={"voice": self.focus.caption_voice})
            if self.focus.extra_hashtags is not None:
                self.caption = self.caption.model_copy(update={"extra_hashtags": list(self.focus.extra_hashtags)})
        # After the focus overrides, so a focus caption voice keeps the house rules.
        if self.voice and (self.voice.banned_words or self.voice.never_claim):
            rules = []
            if self.voice.banned_words:
                rules.append("never use: " + ", ".join(self.voice.banned_words))
            if self.voice.never_claim:
                rules.append("never claim: " + "; ".join(self.voice.never_claim))
            if "never use:" not in self.caption.voice:
                self.caption = self.caption.model_copy(
                    update={"voice": f"{self.caption.voice}; " + "; ".join(rules)})
        return self

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
