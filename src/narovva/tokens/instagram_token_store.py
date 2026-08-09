"""Instagram long-lived token resolution and refresh.

Resolution order: Postgres (`instagram_tokens`, updated by the most recent
refresh) first, falling back to the seeded env-var token from the channel's
config. Mutating a running function's own env var isn't practical on
Vercel, so a refreshed token's new home is Postgres, with the env var
staying as the disaster-recovery seed.

Tokens here come from Instagram API with Instagram Login (a per-app
"narovva-IG"-style Instagram app, not the Facebook-Page-linked Business
Login flow), so refresh uses Instagram's own ig_refresh_token grant --
no app id/secret involved, just the current token itself.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from cryptography.fernet import Fernet, InvalidToken

from ..config.schema import ChannelConfig
from ..db.engine import get_connection
from ..db.repo import Repo
from ..settings import get_settings, resolve_env

_GRAPH_BASE = "https://graph.instagram.com"


class InstagramTokenError(RuntimeError):
    pass


def _fernet() -> Fernet:
    settings = get_settings()
    if not settings.token_encryption_key:
        raise InstagramTokenError("TOKEN_ENCRYPTION_KEY is not set")
    return Fernet(settings.token_encryption_key.encode())


def get_valid_token(channel: ChannelConfig) -> str:
    settings = get_settings()
    if settings.database_url:
        row = None
        try:
            row = Repo(get_connection()).get_instagram_token(channel.id)
        except Exception:
            row = None  # DB unreachable -- fall through to the env var
        if row and row.get("access_token_encrypted"):
            try:
                return _fernet().decrypt(bytes(row["access_token_encrypted"])).decode()
            except InvalidToken:
                pass

    env_token = resolve_env(channel.credentials.instagram_access_token_env)
    if not env_token:
        raise InstagramTokenError(
            f"no Instagram token available for channel {channel.id!r}: nothing stored in "
            f"instagram_tokens, and {channel.credentials.instagram_access_token_env!r} is unset"
        )
    return env_token


def store_refreshed_token(channel: ChannelConfig, *, access_token: str, expires_in_seconds: int) -> None:
    now = datetime.now(timezone.utc)
    encrypted = _fernet().encrypt(access_token.encode())
    Repo(get_connection()).upsert_instagram_token(
        channel_id=channel.id,
        ig_business_account_id=channel.ig_business_account_id or "",
        page_id=channel.ig_page_id or "",
        access_token_encrypted=encrypted,
        issued_at=now,
        expires_at=now + timedelta(seconds=expires_in_seconds),
    )


def refresh_token(channel: ChannelConfig) -> None:
    """Exchange the current long-lived token for a fresh ~60-day one. Meant
    to be called periodically (e.g. weekly), well before expiry.

    Instagram API with Instagram Login refreshes via its own
    ig_refresh_token grant against graph.instagram.com -- the current
    token itself is the only credential required, no app id/secret.
    """
    current = get_valid_token(channel)

    resp = httpx.get(
        f"{_GRAPH_BASE}/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": current},
        timeout=20.0,
    )
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        try:
            Repo(get_connection()).mark_instagram_token_refresh_failed(channel.id, str(exc))
        except Exception:
            pass
        raise InstagramTokenError(f"token refresh failed for channel {channel.id!r}: {exc}") from exc

    data = resp.json()
    store_refreshed_token(
        channel,
        access_token=data["access_token"],
        expires_in_seconds=int(data.get("expires_in", 60 * 24 * 3600)),
    )
