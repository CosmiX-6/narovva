"""Data-access layer over the narovva Postgres schema (post_history,
channel_run_log, instagram_tokens). See db/migrations/0001_init.sql."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import psycopg


class Repo:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    # -- run log --------------------------------------------------------

    def start_run(self, channel_id: str) -> int:
        row = self.conn.execute(
            "INSERT INTO channel_run_log (channel_id) VALUES (%s) RETURNING id",
            (channel_id,),
        ).fetchone()
        return row[0]

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        genres_processed: list[str],
        articles_considered: int,
        articles_posted: int,
        error: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            UPDATE channel_run_log
            SET finished_at = now(), status = %s, genres_processed = %s,
                articles_considered = %s, articles_posted = %s, error = %s
            WHERE id = %s
            """,
            (status, genres_processed, articles_considered, articles_posted, error, run_id),
        )

    def last_successful_post_at(self, channel_id: str, genre: str) -> Optional[datetime]:
        row = self.conn.execute(
            """
            SELECT max(published_at) FROM post_history
            WHERE channel_id = %s AND genre = %s AND status = 'success'
            """,
            (channel_id, genre),
        ).fetchone()
        return row[0] if row else None

    # -- post history -----------------------------------------------------

    def get_attempt_count(self, channel_id: str, content_id: str) -> int:
        row = self.conn.execute(
            "SELECT attempt_count FROM post_history WHERE channel_id = %s AND content_id = %s",
            (channel_id, content_id),
        ).fetchone()
        return row[0] if row else 0

    def attempts_exhausted(self, channel_id: str, content_id: str, *, max_attempts: int) -> bool:
        return self.get_attempt_count(channel_id, content_id) >= max_attempts

    def record_attempt(
        self,
        *,
        channel_id: str,
        genre: str,
        content_id: str,
        article_url: str,
        article_title: str,
        platform: str,
        asset_types: list[str],
        caption: str | None,
        hashtags: list[str],
        status: str,
        platform_post_id: str | None = None,
        error: str | None = None,
    ) -> None:
        """Upsert one post_history row keyed on (channel_id, content_id).

        First attempt inserts with attempt_count=1; subsequent attempts for
        the same (channel, article) increment attempt_count. published_at is
        only ever set the moment status becomes 'success'.
        """
        self.conn.execute(
            """
            INSERT INTO post_history (
                channel_id, genre, content_id, article_url, article_title, platform,
                asset_types, caption, hashtags, status, platform_post_id, attempt_count,
                last_error, published_at
            ) VALUES (
                %(channel_id)s, %(genre)s, %(content_id)s, %(article_url)s, %(article_title)s,
                %(platform)s, %(asset_types)s, %(caption)s, %(hashtags)s, %(status)s,
                %(platform_post_id)s, 1, %(error)s,
                CASE WHEN %(status)s = 'success' THEN now() ELSE NULL END
            )
            ON CONFLICT (channel_id, content_id) DO UPDATE SET
                status = EXCLUDED.status,
                platform_post_id = COALESCE(EXCLUDED.platform_post_id, post_history.platform_post_id),
                attempt_count = post_history.attempt_count + 1,
                last_error = EXCLUDED.last_error,
                caption = EXCLUDED.caption,
                hashtags = EXCLUDED.hashtags,
                asset_types = EXCLUDED.asset_types,
                updated_at = now(),
                published_at = CASE
                    WHEN EXCLUDED.status = 'success' THEN now()
                    ELSE post_history.published_at
                END
            """,
            {
                "channel_id": channel_id,
                "genre": genre,
                "content_id": content_id,
                "article_url": article_url,
                "article_title": article_title,
                "platform": platform,
                "asset_types": asset_types,
                "caption": caption,
                "hashtags": hashtags,
                "status": status,
                "platform_post_id": platform_post_id,
                "error": error,
            },
        )

    # -- instagram tokens ---------------------------------------------------

    def get_instagram_token(self, channel_id: str) -> Optional[dict]:
        row = self.conn.execute(
            """
            SELECT ig_business_account_id, page_id, access_token_encrypted, expires_at, refresh_status
            FROM instagram_tokens WHERE channel_id = %s
            """,
            (channel_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "ig_business_account_id": row[0],
            "page_id": row[1],
            "access_token_encrypted": row[2],
            "expires_at": row[3],
            "refresh_status": row[4],
        }

    def upsert_instagram_token(
        self,
        *,
        channel_id: str,
        ig_business_account_id: str,
        page_id: str,
        access_token_encrypted: bytes,
        issued_at: datetime,
        expires_at: datetime,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO instagram_tokens (
                channel_id, ig_business_account_id, page_id, access_token_encrypted,
                issued_at, expires_at, last_refreshed_at, refresh_status
            ) VALUES (%s, %s, %s, %s, %s, %s, now(), 'ok')
            ON CONFLICT (channel_id) DO UPDATE SET
                ig_business_account_id = EXCLUDED.ig_business_account_id,
                page_id = EXCLUDED.page_id,
                access_token_encrypted = EXCLUDED.access_token_encrypted,
                issued_at = EXCLUDED.issued_at,
                expires_at = EXCLUDED.expires_at,
                last_refreshed_at = now(),
                refresh_status = 'ok',
                last_refresh_error = NULL,
                updated_at = now()
            """,
            (channel_id, ig_business_account_id, page_id, access_token_encrypted, issued_at, expires_at),
        )

    def mark_instagram_token_refresh_failed(self, channel_id: str, error: str) -> None:
        self.conn.execute(
            """
            UPDATE instagram_tokens
            SET refresh_status = 'failed', last_refresh_error = %s, updated_at = now()
            WHERE channel_id = %s
            """,
            (error, channel_id),
        )
