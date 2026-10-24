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

    def last_successful_post(
        self, channel_id: str, *, exclude_genres: tuple[str, ...] = (),
    ) -> Optional[tuple[str, datetime]]:
        """Most recent successful post for the channel, across all genres except
        `exclude_genres` -- used to drive rotation scheduling (narovva.orchestration.due)."""
        row = self.conn.execute(
            """
            SELECT genre, published_at FROM post_history
            WHERE channel_id = %s AND status = 'success' AND NOT (genre = ANY(%s::text[]))
            ORDER BY published_at DESC LIMIT 1
            """,
            (channel_id, list(exclude_genres)),
        ).fetchone()
        return (row[0], row[1]) if row else None

    def count_successful_posts_since(self, channel_id: str, genre: str, since: datetime) -> int:
        row = self.conn.execute(
            """
            SELECT count(*) FROM post_history
            WHERE channel_id = %s AND genre = %s AND status = 'success' AND published_at >= %s
            """,
            (channel_id, genre, since),
        ).fetchone()
        return int(row[0]) if row else 0

    def last_post_at(self, channel_id: str) -> Optional[datetime]:
        """When the channel last posted anything."""
        row = self.conn.execute(
            "SELECT max(published_at) FROM post_history WHERE channel_id = %s AND status = 'success'",
            (channel_id,),
        ).fetchone()
        return row[0] if row else None

    def recent_post_titles(self, channel_id: str, since: datetime, *, limit: int = 200) -> list[str]:
        """Titles of articles posted (or tried) since `since`, so the same story
        is not posted again from another outlet's link."""
        rows = self.conn.execute(
            """
            SELECT article_title FROM post_history
            WHERE channel_id = %s AND updated_at >= %s AND article_title IS NOT NULL
            ORDER BY updated_at DESC LIMIT %s
            """,
            (channel_id, since, limit),
        ).fetchall()
        return [r[0] for r in rows]

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
        music_track_id: str | None = None,
        narration_voice: str | None = None,
        hook_text: str | None = None,
        hook_formula: str | None = None,
        hook_score: int | None = None,
        cover_text: str | None = None,
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
                last_error, published_at, music_track_id, narration_voice,
                hook_text, hook_formula, hook_score, cover_text
            ) VALUES (
                %(channel_id)s, %(genre)s, %(content_id)s, %(article_url)s, %(article_title)s,
                %(platform)s, %(asset_types)s, %(caption)s, %(hashtags)s, %(status)s,
                %(platform_post_id)s, 1, %(error)s,
                CASE WHEN %(status)s = 'success' THEN now() ELSE NULL END,
                %(music_track_id)s, %(narration_voice)s,
                %(hook_text)s, %(hook_formula)s, %(hook_score)s, %(cover_text)s
            )
            ON CONFLICT (channel_id, content_id) DO UPDATE SET
                status = EXCLUDED.status,
                platform_post_id = COALESCE(EXCLUDED.platform_post_id, post_history.platform_post_id),
                attempt_count = post_history.attempt_count + 1,
                last_error = EXCLUDED.last_error,
                caption = EXCLUDED.caption,
                hashtags = EXCLUDED.hashtags,
                asset_types = EXCLUDED.asset_types,
                music_track_id = COALESCE(EXCLUDED.music_track_id, post_history.music_track_id),
                narration_voice = COALESCE(EXCLUDED.narration_voice, post_history.narration_voice),
                hook_text = COALESCE(EXCLUDED.hook_text, post_history.hook_text),
                hook_formula = COALESCE(EXCLUDED.hook_formula, post_history.hook_formula),
                hook_score = COALESCE(EXCLUDED.hook_score, post_history.hook_score),
                cover_text = COALESCE(EXCLUDED.cover_text, post_history.cover_text),
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
                "music_track_id": music_track_id,
                "narration_voice": narration_voice,
                "hook_text": hook_text,
                "hook_formula": hook_formula,
                "hook_score": hook_score,
                "cover_text": cover_text,
            },
        )

    def recent_music_track_ids(self, channel_id: str, *, limit: int = 60) -> set[str]:
        """Music track ids used by this channel's most recent Reels, so the
        next pick can avoid repeating them."""
        rows = self.conn.execute(
            """
            SELECT music_track_id FROM post_history
            WHERE channel_id = %s AND music_track_id IS NOT NULL
            ORDER BY updated_at DESC LIMIT %s
            """,
            (channel_id, limit),
        ).fetchall()
        return {r[0] for r in rows}

    def recent_narration_voices(self, channel_id: str, *, limit: int = 4) -> set[str]:
        """Voices used by this channel's most recent narrated Reels."""
        rows = self.conn.execute(
            """
            SELECT narration_voice FROM post_history
            WHERE channel_id = %s AND narration_voice IS NOT NULL
            ORDER BY updated_at DESC LIMIT %s
            """,
            (channel_id, limit),
        ).fetchall()
        return {r[0] for r in rows}

    # -- instagram tokens ---------------------------------------------------

    # -- performance metrics ---------------------------------------------

    def published_posts(self, channel_id: str, since: datetime) -> list[dict]:
        """Successful posts with a platform id published since `since`, oldest first."""
        rows = self.conn.execute(
            """
            SELECT platform_post_id, published_at, genre, article_title,
                   hook_text, hook_formula, hook_score, cover_text
            FROM post_history
            WHERE channel_id = %s AND status = 'success' AND platform_post_id IS NOT NULL
              AND published_at >= %s
            ORDER BY published_at
            """,
            (channel_id, since),
        ).fetchall()
        keys = ("platform_post_id", "published_at", "genre", "article_title",
                "hook_text", "hook_formula", "hook_score", "cover_text")
        return [dict(zip(keys, r)) for r in rows]

    def has_metrics_snapshot(self, channel_id: str, platform_post_id: str, day) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM post_metrics WHERE channel_id = %s AND platform_post_id = %s AND snapshot_date = %s",
            (channel_id, platform_post_id, day),
        ).fetchone()
        return row is not None

    def upsert_metrics(self, channel_id: str, platform_post_id: str, day, metrics: dict) -> None:
        cols = ("views", "reach", "likes", "comments", "saved", "shares", "total_interactions",
                "avg_watch_ms", "total_watch_ms")
        values = {c: metrics.get(c) for c in cols}
        self.conn.execute(
            f"""
            INSERT INTO post_metrics (channel_id, platform_post_id, snapshot_date, {", ".join(cols)})
            VALUES (%(channel_id)s, %(pid)s, %(day)s, {", ".join(f"%({c})s" for c in cols)})
            ON CONFLICT (channel_id, platform_post_id, snapshot_date) DO UPDATE SET
                fetched_at = now(), {", ".join(f"{c} = EXCLUDED.{c}" for c in cols)}
            """,
            {"channel_id": channel_id, "pid": platform_post_id, "day": day, **values},
        )

    def metrics_snapshots(self, channel_id: str, since: datetime) -> list[dict]:
        """Every snapshot for posts published since `since`, with when it was fetched."""
        rows = self.conn.execute(
            """
            SELECT m.platform_post_id, m.fetched_at, m.views, m.reach, m.likes, m.comments, m.saved,
                   m.shares, m.total_interactions, m.avg_watch_ms, m.total_watch_ms
            FROM post_metrics m
            JOIN post_history p ON p.channel_id = m.channel_id AND p.platform_post_id = m.platform_post_id
            WHERE m.channel_id = %s AND p.published_at >= %s
            ORDER BY m.fetched_at
            """,
            (channel_id, since),
        ).fetchall()
        keys = ("platform_post_id", "fetched_at", "views", "reach", "likes", "comments", "saved",
                "shares", "total_interactions", "avg_watch_ms", "total_watch_ms")
        return [dict(zip(keys, r)) for r in rows]

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
