"""Safety net for blobs orphaned by a crashed/timed-out invocation before it
reached its own delete() call. Run on a low-frequency cron, independent of
the main publish path."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import vercel_blob

from .vercel_blob_host import PREFIX, ImageHostError


def sweep_orphaned_blobs(max_age_minutes: int = 30) -> int:
    """Delete every blob under the narovva/ prefix older than max_age_minutes.
    Returns the number of blobs deleted."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    deleted = 0
    cursor = None
    while True:
        options = {"prefix": f"{PREFIX}/"}
        if cursor:
            options["cursor"] = cursor
        try:
            resp = vercel_blob.list(options)
        except Exception as exc:
            raise ImageHostError(f"failed to list blobs for cleanup: {exc}") from exc

        stale_urls = [
            blob["url"]
            for blob in resp.get("blobs", [])
            if _uploaded_before(blob, cutoff)
        ]
        if stale_urls:
            vercel_blob.delete(stale_urls)
            deleted += len(stale_urls)

        cursor = resp.get("cursor")
        if not resp.get("hasMore") or not cursor:
            break
    return deleted


def _uploaded_before(blob: dict, cutoff: datetime) -> bool:
    raw = blob.get("uploadedAt")
    if not raw:
        return False
    try:
        uploaded_at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    return uploaded_at < cutoff
