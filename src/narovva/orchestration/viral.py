"""One viral post: find the story the internet is talking about right now (any
genre), let the editor pick an informative one, and post it with a hook."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from info_snipe import get_genre
from info_snipe.content_id import make_content_id
from info_snipe.models import Article as FeedArticle

from ..config.schema import ChannelConfig, GenreSetting
from ..dedup import get_store_for_channel
from ..llm import LLMUnavailable
from ..logsafe import redact
from ..settings import get_settings
from ..focus import on_topic
from ..viral.detect import Story, find_stories
from ..viral.editor import editor_pick
from ..viral.schedule import local_day_start, slot_status
from ..viral.sources import DEFAULT_FEEDS, fetch_headlines, fetch_trends
from .due import VIRAL_GENRE
from .run_channel import ChannelRunResult, _build_llm, _open_repo, _preflight_token, _process_one

logger = logging.getLogger(__name__)

# Renders take ~3 minutes; three tries (other outlets' copies of a story whose
# page refuses us, then the next story) stay well inside the 30-minute job.
_MAX_TRIES = 3


def viral_feeds(channel: ChannelConfig) -> list[str]:
    cfg = channel.viral
    feeds = (list(cfg.feeds) if cfg.feeds is not None else list(DEFAULT_FEEDS)) + list(cfg.extra_feeds)
    # With a focus on, the focus genres' feeds always count; stories are then kept only
    # if on topic (an AI story the general press also carries is the strongest signal).
    if cfg.include_genre_feeds or channel.focus_on:
        for g in channel.genres:
            try:
                gc = get_genre(g.genre)
            except KeyError:
                continue
            feeds += gc.rss_feeds + gc.rss_feeds_by_country.get(g.country or "", [])
    return list(dict.fromkeys(feeds))


def viral_due(channel: ChannelConfig, now: datetime | None = None, repo=None) -> tuple[bool, str]:
    """Whether a viral slot is open now (see narovva.viral.schedule)."""
    cfg = channel.viral
    if not cfg or not cfg.enabled:
        return False, "viral posts are off"
    now = now or datetime.now(timezone.utc)
    posted = 0
    if repo is not None:
        posted = repo.count_successful_posts_since(channel.id, VIRAL_GENRE, local_day_start(cfg, now))
        last = repo.last_post_at(channel.id)
        if last and now - last < timedelta(minutes=cfg.min_gap_minutes):
            return False, f"last post was {int((now - last).total_seconds() // 60)} min ago"
    return slot_status(cfg, now, posted)


def scan(channel: ChannelConfig, *, now: datetime | None = None, repo=None, store=None) -> list[Story]:
    """Viral stories right now, best first, minus anything already posted."""
    cfg = channel.viral
    now = now or datetime.now(timezone.utc)
    headlines = fetch_headlines(viral_feeds(channel))
    trends = fetch_trends(cfg.trends_geos) if cfg.trends_geos else []
    recent = repo.recent_post_titles(channel.id, now - timedelta(hours=48)) if repo else []
    stories = find_stories(
        headlines, trends, now=now, max_age_minutes=cfg.max_age_minutes, min_sources=cfg.min_sources,
        exclude_keywords=cfg.exclude_keywords, skip_titles=recent,
    )
    if channel.focus_on:
        stories = [s for s in stories
                   if any(on_topic(h.title, h.summary, channel.focus) for h in s.headlines)]
    if store is not None and stories:
        # Any outlet's link to the story already posted (e.g. by the genre rotation) rules it out.
        ids = {make_content_id(url=h.url, title=h.title, source_name=h.source): s
               for s in stories for h in s.headlines}
        unseen = store.filter_unseen(ids.keys())
        posted = {id(s) for cid, s in ids.items() if cid not in unseen}
        stories = [s for s in stories if id(s) not in posted]
    for s in stories[:8]:
        logger.info(
            "viral: %.2f  %d outlets  %3.0f min  %s%s", s.score, len(s.sources), s.age_minutes(now),
            s.title[:90], f"  [search: {s.trend.query}]" if s.trend else "",
        )
    return stories


def _articles(story: Story) -> list[FeedArticle]:
    """The story's reports, newest first."""
    heads = sorted(story.headlines, key=lambda h: h.published_at, reverse=True)
    out = []
    for h in heads:
        out.append(FeedArticle(
            content_id=make_content_id(url=h.url, title=h.title, source_name=h.source),
            title=h.title, url=h.url, source_name=h.source, genre=VIRAL_GENRE,
            description=h.summary or None, published_at=h.published_at, image_url=h.image_url,
        ))
    return out


def run_viral(channel: ChannelConfig, *, dry_run: bool = False, force: bool = False) -> ChannelRunResult:
    """Post one viral story if a slot is open (or `force`). Never raises for a
    bad story: a failed try moves on to the next copy or the next story."""
    settings = get_settings()
    result = ChannelRunResult(channel_id=channel.id)
    cfg = channel.viral
    if cfg is None:
        result.errors.append("channel has no 'viral' section")
        result.failed += 1
        return result
    repo = _open_repo(settings)
    now = datetime.now(timezone.utc)
    if not force:
        due, why = viral_due(channel, now, repo)
        logger.info("channel %s: viral %s: %s", channel.id, "due" if due else "not due", why)
        if not due:
            return result
    if not dry_run and channel.platform == "instagram":
        try:
            _preflight_token(channel)
        except Exception as exc:
            result.failed += 1
            result.errors.append(redact(str(exc)))
            return result

    run_id = repo.start_run(channel.id) if repo else None
    store = get_store_for_channel(channel.id)
    llm_cache = {"llm": _build_llm(channel)}
    recent_music = set(repo.recent_music_track_ids(channel.id)) if repo and channel.is_video else set()
    recent_voices = set(repo.recent_narration_voices(channel.id)) if repo and channel.narration else set()
    genre = GenreSetting(genre=VIRAL_GENRE, asset_types=cfg.asset_types, music_tags=cfg.music_tags)

    try:
        stories = scan(channel, now=now, repo=repo, store=store)
        picks = editor_pick(llm_cache["llm"], stories, now=now, limit=cfg.editor_candidates, audience=channel.audience)
        if not picks:
            logger.info("channel %s: no informative viral story right now; the slot stays open", channel.id)
        tries = 0
        for story in picks:
            for article in _articles(story)[:2]:
                if tries >= _MAX_TRIES or result.posted:
                    break
                if repo and repo.attempts_exhausted(channel.id, article.content_id,
                                                    max_attempts=settings.max_publish_attempts):
                    continue
                tries += 1
                result.considered += 1
                logger.info("channel %s: viral try %d: %s (%s)", channel.id, tries, article.title, article.url)
                outcome = _process_one(
                    article, genre, channel, dry_run=dry_run, recent_music_ids=recent_music,
                    recent_voices=recent_voices, llm_cache=llm_cache, hook_style=cfg.hook_style,
                )
                if outcome.status == "dry_run":
                    result.skipped += 1
                    logger.info("channel %s: dry run, would post: %s", channel.id, outcome.caption_text[:200])
                    return _finish(repo, run_id, result)
                if repo and not outcome.fatal:
                    repo.record_attempt(
                        channel_id=channel.id, genre=VIRAL_GENRE, content_id=article.content_id,
                        article_url=article.url or "", article_title=article.title, platform=channel.platform,
                        asset_types=outcome.asset_types, caption=outcome.caption_text, hashtags=outcome.hashtags,
                        status=outcome.status, platform_post_id=outcome.platform_post_id, error=outcome.error,
                        music_track_id=outcome.music_track_id, narration_voice=outcome.narration_voice,
                    )
                if outcome.status == "success":
                    # Every outlet's copy, so the rotation does not post the same story again.
                    for a in _articles(story):
                        store.mark_seen(a)
                    result.posted += 1
                    break
                result.failed += 1
                result.errors.append(f"{article.url}: {outcome.error}")
                if outcome.fatal:
                    raise LLMUnavailable(outcome.error or "no text model available")
            if result.posted or tries >= _MAX_TRIES:
                break
    except LLMUnavailable as exc:
        logger.error("channel %s: viral run stopped: %s", channel.id, exc)
        if not result.errors:
            result.failed += 1
            result.errors.append(str(exc))
    return _finish(repo, run_id, result)


def _finish(repo, run_id, result: ChannelRunResult) -> ChannelRunResult:
    if repo and run_id is not None:
        repo.finish_run(
            run_id, status="success" if result.failed == 0 else ("partial" if result.posted else "failed"),
            genres_processed=[VIRAL_GENRE], articles_considered=result.considered,
            articles_posted=result.posted, error=redact("; ".join(result.errors))[:2000] or None,
        )
    return result
