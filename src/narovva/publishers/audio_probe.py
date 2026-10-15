"""Read-only probe of Instagram's Audio API (GET /ig_audio): can this channel's
token search Instagram's audio library, and what does it return? Posts nothing.

Meta documents audio search/attach for content publishing; whether an Instagram
Login token (graph.instagram.com) is accepted, or only Facebook Login, is exactly
what this finds out. The raw (redacted, truncated) answer is returned so the docs
details we cannot fetch from here show up in a log."""

from __future__ import annotations

import json

import httpx

from ..config.schema import ChannelConfig
from ..logsafe import redact
from ..tokens import get_valid_token

_HOSTS = ("https://graph.instagram.com/v21.0",)
_TIMEOUT = 30.0


def probe_audio_api(channel: ChannelConfig, query: str | None = None) -> list[dict]:
    """One result per (audio_type) call: status, parsed/raw body (redacted, truncated)."""
    token = get_valid_token(channel)
    user_id = channel.ig_business_account_id
    results = []
    for base in _HOSTS:
        for audio_type in ("music", "original_sound"):
            params = {"audio_type": audio_type, "user_id": user_id, "access_token": token}
            if query:
                params["search_query"] = query
            try:
                resp = httpx.get(f"{base}/ig_audio", params=params, timeout=_TIMEOUT)
                status, text = resp.status_code, resp.text
            except httpx.HTTPError as exc:
                status, text = 0, f"request failed: {exc}"
            try:
                body = json.dumps(json.loads(text), indent=1)[:3500]
            except ValueError:
                body = text[:1500]
            results.append({
                "host": base.split("//")[1], "audio_type": audio_type,
                "query": query or "(trending)", "status": status, "body": redact(body),
            })
    return results
