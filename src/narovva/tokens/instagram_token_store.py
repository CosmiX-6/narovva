"""Instagram long-lived token resolution and refresh.

Two places can hold a channel's token: Postgres (`instagram_tokens`, written by
the weekly refresh, encrypted with TOKEN_ENCRYPTION_KEY) and the env var named
in the channel's config (the seed you paste in, e.g. a GitHub Actions secret).
The stored one is preferred because it is the freshest. When the two differ and
Instagram rejects the stored one -- e.g. after you revoked a leaked token and
pasted a new one into the secret -- the env var is used instead, and the next
refresh writes it back to Postgres. No manual database edit is needed.

Tokens here come from Instagram API with Instagram Login (an Instagram app, not
the Facebook-Page-linked Business Login flow), so refresh uses Instagram's own
ig_refresh_token grant -- no app id/secret involved, just the current token.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from cryptography.fernet import Fernet, InvalidToken

from ..config.schema import ChannelConfig
from ..db.engine import get_connection
from ..db.repo import Repo
from ..logsafe import redact
from ..settings import get_settings, resolve_env

_GRAPH_BASE = "https://graph.instagram.com"


class InstagramTokenError(RuntimeError):
    def __init__(self, message: str = ""):
        super().__init__(redact(message))


def _fernet() -> Fernet:
    settings = get_settings()
    if not settings.token_encryption_key:
        raise InstagramTokenError("TOKEN_ENCRYPTION_KEY is not set")
    return Fernet(settings.token_encryption_key.encode())


def _stored_token(channel: ChannelConfig) -> str | None:
    if not get_settings().database_url:
        return None
    try:
        row = Repo(get_connection()).get_instagram_token(channel.id)
    except Exception:
        return None  # DB unreachable -- fall through to the env var
    if row and row.get("access_token_encrypted"):
        try:
            return _fernet().decrypt(bytes(row["access_token_encrypted"])).decode()
        except (InvalidToken, InstagramTokenError):
            return None
    return None


def _accepted(token: str) -> bool:
    try:
        check_token(token)
    except InstagramTokenError:
        return False
    return True


# (stored, env) -> chosen token, so one process asks Instagram at most once.
_chosen: dict[tuple[str | None, str | None], str] = {}


def get_valid_token(channel: ChannelConfig) -> str:
    stored = _stored_token(channel)
    env_token = resolve_env(channel.credentials.instagram_access_token_env)
    if not stored and not env_token:
        raise InstagramTokenError(
            f"no Instagram token available for channel {channel.id!r}: nothing stored in "
            f"instagram_tokens, and {channel.credentials.instagram_access_token_env!r} is unset"
        )
    if not stored or not env_token or stored == env_token:
        return stored or env_token
    key = (stored, env_token)
    if key not in _chosen:
        # The stored token wins unless Instagram rejects it and accepts the env one.
        _chosen[key] = env_token if not _accepted(stored) and _accepted(env_token) else stored
    return _chosen[key]


def check_token(token: str) -> None:
    """Cheap call that proves the token is accepted by Instagram right now
    (raises InstagramTokenError with Instagram's own message otherwise), so a
    dead token is caught in seconds instead of after a multi-minute render."""
    try:
        resp = httpx.get(
            f"{_GRAPH_BASE}/v21.0/me", params={"fields": "id", "access_token": token}, timeout=20.0,
        )
    except httpx.HTTPError:
        # Network trouble isn't proof the token is bad; let the real publish decide.
        return
    if resp.status_code >= 400:
        try:
            message = resp.json().get("error", {}).get("message", resp.text)
        except ValueError:
            message = resp.text
        raise InstagramTokenError(f"Instagram rejected the access token: {message}")


def store_refreshed_token(channel: ChannelConfig, *, access_token: str, expires_in_seconds: int) -> None:
    now = datetime.now(UTC)
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
            Repo(get_connection()).mark_instagram_token_refresh_failed(channel.id, redact(str(exc)))  # the URL carries the token
        except Exception:
            pass
        raise InstagramTokenError(f"token refresh failed for channel {channel.id!r}: {exc}") from exc

    data = resp.json()
    store_refreshed_token(
        channel,
        access_token=data["access_token"],
        expires_in_seconds=int(data.get("expires_in", 60 * 24 * 3600)),
    )
