"""Instagram Graph API publisher: single-image and carousel flows.

https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/content-publishing
"""

from __future__ import annotations

import time

import httpx

from ..config.schema import ChannelConfig
from ..platforms import PublishPlatform
from ..tokens.instagram_token_store import get_valid_token
from .base import PostResult, PublishAsset

_GRAPH_BASE = "https://graph.facebook.com/v21.0"
_POLL_INTERVAL_SECONDS = 2.0
_POLL_MAX_ATTEMPTS = 15
_REQUEST_RETRY_ATTEMPTS = 3
_RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}


class _GraphAPIError(RuntimeError):
    def __init__(self, message: str, response: dict | None = None):
        super().__init__(message)
        self.response = response


class InstagramGraphPublisher:
    platform = PublishPlatform.INSTAGRAM

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout

    def publish(self, assets: list[PublishAsset], caption: str, channel: ChannelConfig) -> PostResult:
        if not channel.ig_business_account_id:
            return PostResult(
                status="failed",
                error=f"channel {channel.id!r} has no ig_business_account_id configured",
            )
        hosted = [a for a in assets if a.hosted_url]
        if not hosted:
            return PostResult(status="failed", error="no hosted image URLs to publish")

        try:
            token = get_valid_token(channel)
        except Exception as exc:
            return PostResult(status="failed", error=str(exc))

        ig_user_id = channel.ig_business_account_id
        try:
            if len(hosted) == 1:
                creation_id = self._create_single_container(ig_user_id, hosted[0].hosted_url, caption, token)
            else:
                creation_id = self._create_carousel_container(ig_user_id, hosted, caption, token)
            self._wait_until_finished(creation_id, token)
            media_id = self._publish_container(ig_user_id, creation_id, token)
        except _GraphAPIError as exc:
            return PostResult(status="failed", error=str(exc), raw_response=exc.response)
        return PostResult(status="success", platform_post_id=media_id)

    # -- Graph API calls ----------------------------------------------------

    def _create_single_container(self, ig_user_id: str, image_url: str, caption: str, token: str) -> str:
        data = self._post(
            f"/{ig_user_id}/media",
            {"image_url": image_url, "caption": caption, "access_token": token},
        )
        return data["id"]

    def _create_carousel_container(self, ig_user_id: str, hosted: list[PublishAsset], caption: str, token: str) -> str:
        child_ids = []
        for asset in hosted:
            data = self._post(
                f"/{ig_user_id}/media",
                {"image_url": asset.hosted_url, "is_carousel_item": "true", "access_token": token},
            )
            child_ids.append(data["id"])
        data = self._post(
            f"/{ig_user_id}/media",
            {
                "media_type": "CAROUSEL",
                "children": ",".join(child_ids),
                "caption": caption,
                "access_token": token,
            },
        )
        return data["id"]

    def _wait_until_finished(self, creation_id: str, token: str) -> None:
        for _ in range(_POLL_MAX_ATTEMPTS):
            data = self._get(f"/{creation_id}", {"fields": "status_code", "access_token": token})
            status = data.get("status_code")
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise _GraphAPIError(f"media container {creation_id} failed to process: {data}", data)
            time.sleep(_POLL_INTERVAL_SECONDS)
        # Give up polling and attempt publish anyway -- Instagram sometimes
        # finishes processing between the last poll and the publish call,
        # and media_publish itself returns a clear error if it truly isn't
        # ready yet.

    def _publish_container(self, ig_user_id: str, creation_id: str, token: str) -> str:
        data = self._post(f"/{ig_user_id}/media_publish", {"creation_id": creation_id, "access_token": token})
        return data["id"]

    def _post(self, path: str, params: dict) -> dict:
        return self._request("POST", path, params)

    def _get(self, path: str, params: dict) -> dict:
        return self._request("GET", path, params)

    def _request(self, method: str, path: str, params: dict) -> dict:
        kwargs = {"params": params} if method == "GET" else {"data": params}
        last_exc: Exception | None = None
        for attempt in range(_REQUEST_RETRY_ATTEMPTS):
            try:
                resp = httpx.request(method, f"{_GRAPH_BASE}{path}", timeout=self._timeout, **kwargs)
            except httpx.HTTPError as exc:
                last_exc = _GraphAPIError(f"{method} {path} failed: {exc}")
                time.sleep(2**attempt)
                continue

            if resp.status_code in _RETRYABLE_HTTP_STATUS:
                last_exc = _GraphAPIError(f"{method} {path} returned {resp.status_code}", _safe_json(resp))
                time.sleep(2**attempt)
                continue

            body = _safe_json(resp)
            if resp.status_code >= 400:
                message = ((body or {}).get("error") or {}).get("message", resp.text)
                raise _GraphAPIError(f"{method} {path} failed: {message}", body)
            return body or {}

        raise last_exc if last_exc else _GraphAPIError(f"{method} {path} failed after retries")


def _safe_json(resp: httpx.Response) -> dict | None:
    try:
        return resp.json()
    except ValueError:
        return None
