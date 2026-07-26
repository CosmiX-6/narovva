"""Publisher abstraction: every platform implements the same shape, so
adding X/Threads later means a new module + one registry entry, no changes
to orchestration or this interface."""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from ..config.schema import ChannelConfig
from ..platforms import PublishPlatform


class PublishAsset(BaseModel):
    asset_type: str  # poster_core.AssetType.value
    local_path: str
    hosted_url: str | None = None


class PostResult(BaseModel):
    status: Literal["success", "failed"]
    platform_post_id: str | None = None
    error: str | None = None
    raw_response: dict | None = None


@runtime_checkable
class Publisher(Protocol):
    platform: PublishPlatform

    def publish(
        self, assets: list[PublishAsset], caption: str, channel: ChannelConfig
    ) -> PostResult: ...
