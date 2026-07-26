"""Platform -> Publisher lookup. Adding a platform is one entry here."""

from __future__ import annotations

from ..platforms import PublishPlatform
from .base import Publisher
from .instagram import InstagramGraphPublisher

PLATFORM_PUBLISHERS: dict[PublishPlatform, type[Publisher]] = {
    PublishPlatform.INSTAGRAM: InstagramGraphPublisher,
}


def get_publisher(platform: PublishPlatform) -> Publisher:
    try:
        cls = PLATFORM_PUBLISHERS[platform]
    except KeyError:
        raise ValueError(f"no publisher registered for platform {platform.value!r}") from None
    return cls()
