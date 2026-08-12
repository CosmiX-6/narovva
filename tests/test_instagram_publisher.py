from __future__ import annotations

import httpx
import pytest

from narovva.config.schema import BrandKitConfig, ChannelConfig, CredentialRefs, GenreSetting
from narovva.publishers import instagram as instagram_module
from narovva.publishers.base import PublishAsset
from narovva.publishers.instagram import InstagramGraphPublisher


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


def _channel(**overrides) -> ChannelConfig:
    defaults = dict(
        id="chan",
        ig_business_account_id="ig123",
        genres=[GenreSetting(genre="tech")],
        brand=BrandKitConfig(),
        credentials=CredentialRefs(instagram_access_token_env="IG_TOKEN"),
    )
    defaults.update(overrides)
    return ChannelConfig(**defaults)


def _patch_token(monkeypatch, token="fake-token"):
    monkeypatch.setattr(instagram_module, "get_valid_token", lambda channel: token)


def test_publish_reel_creates_video_container_and_publishes(monkeypatch):
    _patch_token(monkeypatch)
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs.get("data") or kwargs.get("params")))
        if url.endswith("/ig123/media") and kwargs["data"].get("media_type") == "REELS":
            assert kwargs["data"]["video_url"] == "https://blob/reel.mp4"
            assert kwargs["data"]["share_to_feed"] == "true"
            return _FakeResponse(200, {"id": "creation123"})
        if url.endswith("/creation123"):
            return _FakeResponse(200, {"status_code": "FINISHED"})
        if url.endswith("/ig123/media_publish"):
            assert kwargs["data"]["creation_id"] == "creation123"
            return _FakeResponse(200, {"id": "media456"})
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(instagram_module.httpx, "request", fake_request)
    monkeypatch.setattr(instagram_module.time, "sleep", lambda s: None)

    publisher = InstagramGraphPublisher()
    asset = PublishAsset(asset_type="reel", local_path="/tmp/reel.mp4", hosted_url="https://blob/reel.mp4")
    result = publisher.publish([asset], "a caption", _channel())

    assert result.status == "success"
    assert result.platform_post_id == "media456"
    media_type_calls = [c for c in calls if c[1].endswith("/ig123/media") and c[2].get("media_type") == "REELS"]
    assert len(media_type_calls) == 1


def test_publish_reel_fails_when_container_processing_errors(monkeypatch):
    _patch_token(monkeypatch)

    def fake_request(method, url, **kwargs):
        if url.endswith("/ig123/media"):
            return _FakeResponse(200, {"id": "creation123"})
        if url.endswith("/creation123"):
            return _FakeResponse(200, {"status_code": "ERROR"})
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(instagram_module.httpx, "request", fake_request)
    monkeypatch.setattr(instagram_module.time, "sleep", lambda s: None)

    publisher = InstagramGraphPublisher()
    asset = PublishAsset(asset_type="reel", local_path="/tmp/reel.mp4", hosted_url="https://blob/reel.mp4")
    result = publisher.publish([asset], "a caption", _channel())

    assert result.status == "failed"
    assert "creation123" in result.error


def test_publish_single_image_still_uses_image_container_flow(monkeypatch):
    _patch_token(monkeypatch)

    def fake_request(method, url, **kwargs):
        if url.endswith("/ig123/media"):
            assert "image_url" in kwargs["data"]
            assert kwargs["data"].get("media_type") != "REELS"
            return _FakeResponse(200, {"id": "creation999"})
        if url.endswith("/creation999"):
            return _FakeResponse(200, {"status_code": "FINISHED"})
        if url.endswith("/ig123/media_publish"):
            return _FakeResponse(200, {"id": "media999"})
        raise AssertionError(f"unexpected request: {method} {url}")

    monkeypatch.setattr(instagram_module.httpx, "request", fake_request)
    monkeypatch.setattr(instagram_module.time, "sleep", lambda s: None)

    publisher = InstagramGraphPublisher()
    asset = PublishAsset(asset_type="cover", local_path="/tmp/cover.png", hosted_url="https://blob/cover.png")
    result = publisher.publish([asset], "a caption", _channel())

    assert result.status == "success"
    assert result.platform_post_id == "media999"
