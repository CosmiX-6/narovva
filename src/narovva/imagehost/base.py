"""Ephemeral public image hosting: upload just long enough for a publisher's
API to fetch it, then delete. Never a permanent archive."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class HostedImage(BaseModel):
    url: str
    pathname: str


@runtime_checkable
class ImageHost(Protocol):
    def upload(self, data: bytes, filename: str, content_type: str = "image/png") -> HostedImage: ...
    def delete(self, hosted: HostedImage | str) -> None: ...
