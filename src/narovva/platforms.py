"""Publishing-platform identity, distinct from poster_core's image-size Platform enum.

poster_core.Platform (instagram_post / instagram_story / linkedin / x /
youtube_thumbnail) picks a render *size*. PublishPlatform picks a social
*account type* to post to. One publish platform can map to more than one
render size depending on the asset; today each maps to a single default.
"""

from __future__ import annotations

from enum import Enum

from poster_core import Platform as RenderPlatform


class PublishPlatform(str, Enum):
    INSTAGRAM = "instagram"
    X = "x"
    THREADS = "threads"


_RENDER_PLATFORM_FOR: dict[PublishPlatform, RenderPlatform] = {
    PublishPlatform.INSTAGRAM: RenderPlatform.INSTAGRAM_POST,
    PublishPlatform.X: RenderPlatform.X,
    # poster-core has no bespoke Threads size yet; Instagram's post size
    # (4:5) is a reasonable default until one is added upstream.
    PublishPlatform.THREADS: RenderPlatform.INSTAGRAM_POST,
}


def render_platform_for(publish_platform: PublishPlatform) -> RenderPlatform:
    return _RENDER_PLATFORM_FOR[publish_platform]
