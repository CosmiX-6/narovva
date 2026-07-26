"""Per-platform caption constraints. Adding a platform is one dict entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..platforms import PublishPlatform

HashtagStyle = Literal["footer", "inline", "none"]


@dataclass(frozen=True)
class PlatformCaptionRules:
    max_chars: int
    max_hashtags: int
    hashtag_style: HashtagStyle
    allow_emoji: bool = True


PLATFORM_CAPTION_RULES: dict[PublishPlatform, PlatformCaptionRules] = {
    PublishPlatform.INSTAGRAM: PlatformCaptionRules(max_chars=2200, max_hashtags=8, hashtag_style="footer"),
    PublishPlatform.X: PlatformCaptionRules(max_chars=280, max_hashtags=3, hashtag_style="inline"),
    PublishPlatform.THREADS: PlatformCaptionRules(max_chars=500, max_hashtags=5, hashtag_style="footer"),
}
