"""Read-only Instagram insights for the channel's own posts (Instagram API with
Instagram Login, graph.instagram.com). Needs the token to carry the
instagram_business_manage_insights permission; `probe` tells whether it does."""

from __future__ import annotations

import json
import logging

import httpx

from ..logsafe import redact

logger = logging.getLogger(__name__)

GRAPH = "https://graph.instagram.com/v21.0"
_TIMEOUT = 30.0
# Reels metrics, best first. Instagram fails the whole request if any one name is not
# supported for this media/account, so fetch() falls back to smaller sets.
REEL_METRICS = ["views", "reach", "likes", "comments", "saved", "shares", "total_interactions",
                "ig_reels_avg_watch_time", "ig_reels_video_view_total_time"]
_SAFE_METRICS = ["reach", "likes", "comments", "saved", "shares"]


class InsightsError(RuntimeError):
    pass


def _get(path: str, token: str, **params) -> dict:
    try:
        resp = httpx.get(f"{GRAPH}/{path}", params={**params, "access_token": token}, timeout=_TIMEOUT)
    except httpx.HTTPError as exc:
        raise InsightsError(redact(f"request failed: {exc}")) from None
    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text[:500]}
    if resp.status_code >= 400 or "error" in body:
        err = body.get("error", body) if isinstance(body, dict) else body
        raise InsightsError(redact(f"HTTP {resp.status_code}: {json.dumps(err)[:600]}"))
    return body


def recent_media(user_id: str, token: str, limit: int = 25) -> list[dict]:
    """The account's latest posts, newest first."""
    body = _get(f"{user_id}/media", token, limit=limit,
                fields="id,media_type,media_product_type,timestamp,permalink,caption")
    return body.get("data", [])


def parse_insights(body: dict) -> dict[str, int]:
    """{"data": [{"name": "reach", "values": [{"value": 12}]}, ...]} -> {"reach": 12}."""
    out = {}
    for item in body.get("data", []):
        name = item.get("name")
        value = item.get("total_value", {}).get("value") if "total_value" in item else None
        if value is None and item.get("values"):
            value = item["values"][0].get("value")
        if name and isinstance(value, (int, float)):
            out[name] = int(value)
    return out


def media_insights(media_id: str, token: str, metrics: list[str] | None = None) -> dict[str, int]:
    """Lifetime metrics for one post. Tries the full Reels set, then the safe set, then
    each metric alone, so one unsupported name does not lose the rest."""
    wanted = list(metrics or REEL_METRICS)
    for attempt in (wanted, [m for m in _SAFE_METRICS if m in wanted]):
        if not attempt:
            continue
        try:
            return parse_insights(_get(f"{media_id}/insights", token, metric=",".join(attempt)))
        except InsightsError as exc:
            logger.info("insights %s for %s failed (%s)", ",".join(attempt), media_id, exc)
            last = exc
    out: dict[str, int] = {}
    for m in wanted:
        try:
            out.update(parse_insights(_get(f"{media_id}/insights", token, metric=m)))
        except InsightsError:
            continue
    if not out:
        raise last
    return out


def probe(user_id: str, token: str) -> list[str]:
    """Human-readable lines: can this token list posts and read a reel's insights?"""
    lines = []
    try:
        media = recent_media(user_id, token, limit=10)
    except InsightsError as exc:
        return [f"list posts: FAILED -- {exc}"]
    reels = [m for m in media if m.get("media_product_type") == "REELS"]
    lines.append(f"list posts: OK ({len(media)} recent, {len(reels)} reels)")
    if not reels:
        return lines + ["no reel to test insights on"]
    reel = reels[0]
    lines.append(f"testing reel {reel.get('id')} from {reel.get('timestamp')} ({reel.get('permalink')})")
    for metric in REEL_METRICS:
        try:
            got = parse_insights(_get(f"{reel['id']}/insights", token, metric=metric))
            lines.append(f"  {metric}: OK {got.get(metric)}")
        except InsightsError as exc:
            lines.append(f"  {metric}: FAILED -- {exc}")
    ok = sum(": OK" in ln for ln in lines[2:])
    lines.append("verdict: insights work" if ok else
                 "verdict: no insights -- the token probably lacks instagram_business_manage_insights")
    return lines
