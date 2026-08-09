"""End-to-end orchestration for one channel: fetch -> analyze -> render ->
caption -> host -> publish -> record, gated so a transient failure never
permanently burns an article (mark-seen only fires on success, or once the
per-article retry budget is exhausted)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from info_snipe import NewsAPISource, NewsFetcher, RSSSource
from info_snipe.models import Article as FeedArticle
from poster_core import AssetType, Pipeline, PipelineConfig
from poster_core.analysis.llm import GeminiChat, LLMClient, OpenAIChat

from ..captions import generate_caption
from ..config.schema import ChannelConfig, GenreSetting
from ..db.engine import ensure_schema, get_connection
from ..db.repo import Repo
from ..dedup import get_store_for_channel
from ..imagehost import ImageHostError, VercelBlobImageHost
from ..platforms import PublishPlatform, render_platform_for
from ..publishers import PublishAsset, get_publisher
from ..settings import Settings, get_settings, resolve_env

logger = logging.getLogger(__name__)


@dataclass
class ChannelRunResult:
    channel_id: str
    considered: int = 0
    posted: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class _Outcome:
    status: str  # "success" | "failed" | "dry_run"
    caption_text: str
    hashtags: list[str]
    asset_types: list[str]
    platform_post_id: str | None = None
    error: str | None = None


def run_channel(
    channel: ChannelConfig,
    *,
    genres_filter: list[str] | None = None,
    dry_run: bool = False,
    max_posts_per_genre: int | None = None,
) -> ChannelRunResult:
    """Run one channel's genres. `max_posts_per_genre` bounds how many
    successful publishes a single genre can produce in this call -- unset
    (the CLI default) processes every fetched article, which is what you
    want for a manual/testing run; a scheduled/cron run should pass 1 so
    an hourly trigger can't dump a backlog of posts in one invocation."""
    settings = get_settings()
    repo = _open_repo(settings)
    run_id = repo.start_run(channel.id) if repo else None

    result = ChannelRunResult(channel_id=channel.id)
    store = get_store_for_channel(channel.id)
    sources = [RSSSource()]
    if settings.newsapi_key:
        sources.append(NewsAPISource(settings.newsapi_key))
    fetcher = NewsFetcher(sources=sources, store=store)

    genres = [g for g in channel.genres if genres_filter is None or g.genre in genres_filter]
    genres_processed: list[str] = []

    try:
        for genre_setting in genres:
            genres_processed.append(genre_setting.genre)
            articles = fetcher.fetch(
                genre_setting.genre,
                country=genre_setting.country,
                limit=genre_setting.limit,
                mark_seen=False,
            )
            genre_posted = 0
            for article in articles:
                if max_posts_per_genre is not None and genre_posted >= max_posts_per_genre:
                    break
                result.considered += 1

                if repo and repo.attempts_exhausted(
                    channel.id, article.content_id, max_attempts=settings.max_publish_attempts
                ):
                    logger.warning(
                        "channel %s: giving up on %s after %d failed attempts",
                        channel.id, article.url, settings.max_publish_attempts,
                    )
                    store.mark_seen(article)
                    result.skipped += 1
                    continue

                outcome = _process_one(article, genre_setting, channel, dry_run=dry_run)

                if outcome.status == "dry_run":
                    result.skipped += 1
                    continue

                if repo:
                    repo.record_attempt(
                        channel_id=channel.id,
                        genre=genre_setting.genre,
                        content_id=article.content_id,
                        article_url=article.url or "",
                        article_title=article.title,
                        platform=channel.platform,
                        asset_types=outcome.asset_types,
                        caption=outcome.caption_text,
                        hashtags=outcome.hashtags,
                        status=outcome.status,
                        platform_post_id=outcome.platform_post_id,
                        error=outcome.error,
                    )

                if outcome.status == "success":
                    store.mark_seen(article)
                    result.posted += 1
                    genre_posted += 1
                else:
                    result.failed += 1
                    result.errors.append(f"{article.url}: {outcome.error}")
    except Exception as exc:
        if repo and run_id is not None:
            repo.finish_run(
                run_id, status="failed", genres_processed=genres_processed,
                articles_considered=result.considered, articles_posted=result.posted,
                error=str(exc),
            )
        raise
    else:
        if repo and run_id is not None:
            status = "success" if result.failed == 0 else "partial"
            repo.finish_run(
                run_id, status=status, genres_processed=genres_processed,
                articles_considered=result.considered, articles_posted=result.posted,
            )
    return result


def _process_one(
    article: FeedArticle, genre_setting: GenreSetting, channel: ChannelConfig, *, dry_run: bool
) -> _Outcome:
    try:
        llm = _build_llm(channel)
        pipeline = Pipeline(
            PipelineConfig(
                text_provider=channel.text_provider,
                image_provider=channel.image_provider,
                output_dir=f"/tmp/narovva/{channel.id}",
                brand=channel.brand.to_poster_core(),
            ),
            llm=llm,
        )
        article_full, brief = pipeline.analyze(article.url)
        asset_types = [AssetType(t) for t in genre_setting.asset_types] if genre_setting.asset_types else None
        assets = pipeline.run_from_brief(
            article_full, brief,
            asset_types=asset_types,
            platform=render_platform_for(PublishPlatform(channel.platform)),
        )
        asset_type_values = [a.asset_type.value for a in assets]
        caption = generate_caption(
            brief, publish_platform=PublishPlatform(channel.platform), tone=channel.caption, llm=llm,
        )
    except Exception as exc:
        # A bad article (unextractable page, transient LLM/network error)
        # must not crash the whole channel run -- record it as a failed
        # attempt and let the caller move on to the next article.
        logger.warning("channel %s: failed to process %s: %s", channel.id, article.url, exc)
        return _Outcome(status="failed", caption_text="", hashtags=[], asset_types=[], error=str(exc))

    if dry_run:
        return _Outcome(
            status="dry_run", caption_text=caption.text, hashtags=caption.hashtags,
            asset_types=asset_type_values,
        )

    host = VercelBlobImageHost()
    publish_assets: list[PublishAsset] = []
    hosted = []
    try:
        for asset in assets:
            for path in asset.paths:
                h = host.upload(
                    Path(path).read_bytes(),
                    f"{channel.id}/{article.content_id}/{Path(path).name}",
                )
                hosted.append(h)
                publish_assets.append(
                    PublishAsset(asset_type=asset.asset_type.value, local_path=path, hosted_url=h.url)
                )
        publisher = get_publisher(PublishPlatform(channel.platform))
        post_result = publisher.publish(publish_assets, caption.text, channel)
    except ImageHostError as exc:
        return _Outcome(
            status="failed", caption_text=caption.text, hashtags=caption.hashtags,
            asset_types=asset_type_values, error=str(exc),
        )
    finally:
        for h in hosted:
            _safe_delete(host, h)

    return _Outcome(
        status=post_result.status,
        caption_text=caption.text,
        hashtags=caption.hashtags,
        asset_types=asset_type_values,
        platform_post_id=post_result.platform_post_id,
        error=post_result.error,
    )


def _build_llm(channel: ChannelConfig) -> LLMClient:
    if channel.text_provider == "gemini":
        return GeminiChat(api_key=resolve_env(channel.credentials.gemini_api_key_env))
    return OpenAIChat(api_key=resolve_env(channel.credentials.openai_api_key_env))


def _open_repo(settings: Settings) -> Repo | None:
    if not settings.database_url:
        logger.warning("DATABASE_URL not set; skipping run-log/post-history persistence")
        return None
    conn = get_connection()
    ensure_schema(conn)
    return Repo(conn)


def _safe_delete(host: VercelBlobImageHost, hosted) -> None:
    try:
        host.delete(hosted)
    except ImageHostError:
        logger.exception("failed to delete hosted image %s (will be swept later)", hosted.url)
