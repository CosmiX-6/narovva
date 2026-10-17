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
from poster_core import Platform as RenderPlatform
from poster_core.analysis.llm import GeminiChat, LLMClient, OpenAIChat

from ..captions import generate_caption
from ..config.schema import ChannelConfig, GenreSetting
from ..db.engine import ensure_schema, get_connection
from ..db.repo import Repo
from ..dedup import get_store_for_channel
from ..imagehost import ImageHostError, VercelBlobImageHost
from ..motion import render_motion_reel, slide_specs_from_assets, total_duration
from ..motion.slides import SCENE_OVERLAP_SECONDS, VOICE_LEAD, _trim, motion_duration
from ..narration.script import caption_text
from ..narration import (
    build_provider, choose_voice, default_voices, mix_voice_and_music, style_for_tone,
    synthesize_lines, write_script,
)
from ..music import JamendoError, JamendoMusicClient, MusicTrack, music_tags_for
from ..platforms import PublishPlatform, render_platform_for
from ..publishers import PublishAsset, get_publisher
from ..settings import Settings, get_settings, resolve_env
from ..tokens import InstagramTokenError, check_token, get_valid_token
from ..llm import LLMUnavailable, build_llm_chain
from ..logsafe import redact
from ..video import assemble_reel, make_cover, slide_duration
from ..viral.editor import spoken, write_hook

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
    music_track_id: str | None = None
    narration_voice: str | None = None
    fatal: bool = False  # no text model is left: stop the run rather than fail every article


def run_channel(
    channel: ChannelConfig,
    *,
    genres_filter: list[str] | None = None,
    dry_run: bool = False,
    max_posts_per_genre: int | None = None,
    max_posts_total: int | None = None,
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
    if not dry_run and channel.platform == "instagram":
        # Fail in seconds, before fetching/rendering, if Instagram would reject the token.
        try:
            _preflight_token(channel)
        except InstagramTokenError as exc:
            logger.error("channel %s: %s", channel.id, exc)
            result.failed += 1
            result.errors.append(str(exc))
            if repo and run_id is not None:
                repo.finish_run(
                    run_id, status="failed", genres_processed=[], articles_considered=0,
                    articles_posted=0, error=redact(str(exc)),
                )
            return result
    store = get_store_for_channel(channel.id)
    sources = [RSSSource()]
    if settings.newsapi_key:
        sources.append(NewsAPISource(settings.newsapi_key))
    fetcher = NewsFetcher(sources=sources, store=store)

    genres = list(channel.genres)
    if genres_filter is not None:
        # Keep the caller's order: for a rotation it is a priority list (due genre first).
        by_name = {g.genre: g for g in channel.genres}
        genres = [by_name[name] for name in genres_filter if name in by_name]
    genres_processed: list[str] = []
    llm_cache: dict = {}  # the text-model chain, built on first use and shared by every article
    llm_down = False
    recent_music_ids: set[str] = set(repo.recent_music_track_ids(channel.id)) if repo and channel.is_video else set()
    recent_voices: set[str] = set(repo.recent_narration_voices(channel.id)) if repo and channel.narration else set()

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
                if max_posts_total is not None and result.posted >= max_posts_total:
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

                outcome = _process_one(
                    article, genre_setting, channel, dry_run=dry_run, recent_music_ids=recent_music_ids,
                    recent_voices=recent_voices, llm_cache=llm_cache,
                )
                if outcome.fatal:
                    # Not the article's fault: leave it unrecorded (no burnt attempt) and stop.
                    logger.error("channel %s: %s; stopping this run", channel.id, outcome.error)
                    result.failed += 1
                    result.errors.append(f"{article.url}: {outcome.error}")
                    llm_down = True
                    break
                if outcome.music_track_id:
                    recent_music_ids.add(outcome.music_track_id)
                if outcome.narration_voice:
                    recent_voices.add(outcome.narration_voice)
                if outcome.status == "failed":
                    logger.warning("channel %s: %s failed: %s", channel.id, article.url, outcome.error)

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
                        music_track_id=outcome.music_track_id,
                        narration_voice=outcome.narration_voice,
                    )

                if outcome.status == "success":
                    store.mark_seen(article)
                    result.posted += 1
                    genre_posted += 1
                else:
                    result.failed += 1
                    result.errors.append(f"{article.url}: {outcome.error}")
            if llm_down:
                break
            if max_posts_total is not None and result.posted >= max_posts_total:
                break
    except Exception as exc:
        if repo and run_id is not None:
            repo.finish_run(
                run_id, status="failed", genres_processed=genres_processed,
                articles_considered=result.considered, articles_posted=result.posted,
                error=redact(str(exc)),
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
    article: FeedArticle, genre_setting: GenreSetting, channel: ChannelConfig, *, dry_run: bool,
    recent_music_ids: set[str] | frozenset[str] = frozenset(),
    recent_voices: set[str] | frozenset[str] = frozenset(),
    llm_cache: dict | None = None,
    hook_style: str | None = None,
) -> _Outcome:
    """`hook_style` (viral posts): write a curiosity/stakes hook and open the reel,
    the cover and the caption with it."""
    is_reel = channel.is_video
    hook: str | None = None
    try:
        # One chain per run, so a model whose quota is spent stays skipped for later articles.
        if llm_cache is not None and "llm" in llm_cache:
            llm = llm_cache["llm"]
        else:
            llm = _build_llm(channel)
            if llm_cache is not None:
                llm_cache["llm"] = llm
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
        # Reels are full-screen 9:16 video, so source frames are rendered at
        # Instagram's story size rather than the 4:5 feed-post size.
        render_platform = (
            RenderPlatform.INSTAGRAM_STORY if is_reel else render_platform_for(PublishPlatform(channel.platform))
        )
        assets = pipeline.run_from_brief(article_full, brief, asset_types=asset_types, platform=render_platform)
        asset_type_values = [a.asset_type.value for a in assets]
        caption = generate_caption(
            brief, publish_platform=PublishPlatform(channel.platform), tone=channel.caption, llm=llm,
        )
        if hook_style:
            hook = write_hook(llm, brief, hook_style)
            if hook and not caption.text.startswith(hook):
                caption.text = f"{hook}\n\n{caption.text}"  # the line shown before "more"
    except Exception as exc:
        # A bad article (unextractable page, transient LLM/network error)
        # must not crash the whole channel run -- record it as a failed
        # attempt and let the caller move on to the next article.
        logger.warning("channel %s: failed to process %s: %s", channel.id, article.url, redact(str(exc)))
        return _Outcome(
            status="failed", caption_text="", hashtags=[], asset_types=[], error=redact(str(exc)),
            fatal=isinstance(exc, LLMUnavailable),
        )

    if dry_run:
        return _Outcome(
            status="dry_run", caption_text=caption.text, hashtags=caption.hashtags,
            asset_types=asset_type_values,
        )

    host = VercelBlobImageHost()
    publish_assets: list[PublishAsset] = []
    hosted = []
    caption_text = caption.text
    music_track_id: str | None = None
    narration_voice: str | None = None
    try:
        if is_reel:
            track = _pick_music_track(channel, genre_setting, brief, recent_music_ids)
            music_track_id = track.id
            caption_text = f"{caption.text}\n\n{track.attribution}"
            image_paths = [path for asset in assets for path in asset.paths]
            durations = [slide_duration(c) for c in _slide_char_counts(assets)]
            reel_path = f"/tmp/narovva/{channel.id}/{article.content_id}_reel.mp4"
            video_path = None
            if channel.publish_format == "motion_reel":
                video_path, narration_voice = _try_motion_reel(
                    channel, assets, brief, track, reel_path.replace("_reel.mp4", "_motion.mp4"),
                    llm=llm, recent_voices=recent_voices, seed=article.content_id, hook=hook,
                )
            if video_path is None:  # plain reel, or motion render failed -> never skip the post
                video_path = assemble_reel(image_paths, track.audio_bytes, reel_path, durations=durations)
            h = host.upload(
                Path(video_path).read_bytes(),
                f"{channel.id}/{article.content_id}/reel.mp4",
                content_type="video/mp4",
            )
            hosted.append(h)
            cover_url = _host_cover(host, hosted, channel, article, brief, assets, hook=hook)
            publish_assets.append(
                PublishAsset(asset_type="reel", local_path=video_path, hosted_url=h.url, cover_url=cover_url)
            )
        else:
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
        post_result = publisher.publish(publish_assets, caption_text, channel)
    except Exception as exc:  # music/network/render/host errors: a failed attempt, never a crashed run
        logger.warning("channel %s: posting %s failed: %s", channel.id, article.url, redact(str(exc)))
        return _Outcome(
            status="failed", caption_text=caption_text, hashtags=caption.hashtags,
            asset_types=asset_type_values, error=redact(str(exc)), music_track_id=music_track_id,
            narration_voice=narration_voice,
        )
    finally:
        for h in hosted:
            _safe_delete(host, h)

    return _Outcome(
        status=post_result.status,
        caption_text=caption_text,
        hashtags=caption.hashtags,
        asset_types=asset_type_values,
        platform_post_id=post_result.platform_post_id,
        error=post_result.error,
        music_track_id=music_track_id,
        narration_voice=narration_voice,
    )


def _slide_char_counts(assets: list) -> list[int]:
    """Visible-text character count per rendered image path, in the same
    order as `[path for asset in assets for path in asset.paths]` -- the
    Reel's per-slide timing formula reads text volume, not just image
    count, so a dense slide holds on screen longer than a sparse one."""
    counts: list[int] = []
    for asset in assets:
        if asset.asset_type is AssetType.CAROUSEL:
            for slide, _ in zip(asset.plan.slides, asset.paths):
                counts.append(_deck_slide_char_count(slide))
        elif asset.asset_type is AssetType.INFOGRAPHIC:
            char_count = sum(len(fact) for fact in asset.plan.facts)
            counts.extend([char_count] * len(asset.paths))
        else:  # COVER / THUMBNAIL: one path, headline + subheadline
            char_count = len(asset.plan.headline) + len(asset.plan.subheadline or "")
            counts.extend([char_count] * len(asset.paths))
    return counts


def _deck_slide_char_count(slide) -> int:
    """Visible on-image text for one poster_core.DeckSlide, across every
    field a slide renderer might actually draw -- not just kicker/heading/
    body, since STATS/TIMELINE/MONEY_FLOW/COMPARISON/QUOTE slides carry
    their real content in structured fields instead of those three."""
    count = len(slide.kicker or "") + len(slide.heading or "") + len(slide.body or "")
    count += sum(len(fact) for fact in slide.facts)
    count += sum(len(event.when) + len(event.what) for event in slide.timeline)
    count += sum(
        len(step.actor) + len(step.amount or "") + len(step.detail or "")
        for step in slide.money_trail
    )
    if slide.comparison:
        c = slide.comparison
        count += len(c.label_a) + len(c.value_a) + len(c.label_b) + len(c.value_b) + len(c.title or "")
    if slide.quote:
        count += len(slide.quote.text) + len(slide.quote.attribution or "")
    return count


def _preflight_token(channel: ChannelConfig) -> None:
    check_token(get_valid_token(channel))


def _narrate(channel, brief, specs, track, *, llm, recent_voices, seed, hook=None):
    """Voice-over: script -> TTS (a voice not used recently) -> durations that
    follow the speech -> music ducked under the voice. Tries the configured
    provider, then each fallback. Returns (mixed_audio, voice)."""
    cfg = channel.narration
    env_names = {
        "openai": channel.credentials.openai_api_key_env,
        "gemini": channel.credentials.gemini_api_key_env,
        "elevenlabs": channel.credentials.elevenlabs_api_key_env,
        "kokoro": None,  # local voice, no key
    }
    lines = write_script(llm, brief, specs, brand=channel.brand.name, hook=spoken(hook) if hook else None)
    style = style_for_tone(brief.tone)
    failures: list[str] = []
    for n, name in enumerate([cfg.provider, *cfg.fallback_providers]):
        try:
            provider = build_provider(name, resolve_env(env_names[name]) or "", cfg.model if n == 0 else None)
            pool = (cfg.voices if n == 0 and cfg.voices else None) or default_voices(name)
            voice = choose_voice(pool, recent_voices, seed)
            clips = synthesize_lines(provider, lines, voice=voice, style=style)
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            logger.warning("channel %s: narration via %s failed (%s)", channel.id, name, exc)
            continue
        for spec, clip, line in zip(specs, clips, lines):
            spec["duration"] = motion_duration(0, spec["kind"], clip.seconds)
            if cfg.captions:  # burned-in: most viewers watch with the sound off
                spec["caption"], spec["voice"] = caption_text(line), round(clip.seconds, 3)
        starts, t = [], 0.0
        for spec in specs:
            starts.append(t + VOICE_LEAD)  # the picture leads the voice slightly
            t += spec["duration"] - SCENE_OVERLAP_SECONDS
        total = total_duration([s["duration"] for s in specs])
        audio = mix_voice_and_music(clips, starts, track.audio_bytes, total)
        logger.info("channel %s: narrated with %s voice %r (%.0fs reel)", channel.id, name, voice, total)
        return audio, voice
    raise RuntimeError("; ".join(failures) or "no narration provider configured")


def _try_motion_reel(
    channel, assets, brief, track: MusicTrack, output_path: str, *,
    llm=None, recent_voices=frozenset(), seed: str = "", hook: str | None = None,
) -> tuple[str | None, str | None]:
    """Render the HyperFrames motion reel (optionally narrated). Returns
    (mp4 path, narration voice); path is None (after logging why) so the
    caller falls back to the Ken-Burns reel. A narration failure only drops the voice."""
    try:
        category = getattr(brief.category, "value", str(brief.category))
        accent = channel.brand.category_accents.get(category) or channel.brand.accent_color
        specs = apply_hook(slide_specs_from_assets(assets), hook, brief.headline)
        audio, voice = track.audio_bytes, None
        if channel.narration and llm is not None:
            try:
                audio, voice = _narrate(
                    channel, brief, specs, track, llm=llm, recent_voices=recent_voices, seed=seed, hook=hook,
                )
            except Exception as exc:  # no voice is better than no post
                logger.warning("channel %s: narration failed (%s); posting music-only", channel.id, exc)
                specs = apply_hook(slide_specs_from_assets(assets), hook, brief.headline)
                audio, voice = track.audio_bytes, None
        # The article's own photo, when poster-core found one (it is optional:
        # the reel renders on its generative background without it).
        photo = next((a for a in assets if getattr(a, "source_image_path", None)), None)
        path = render_motion_reel(
            specs, audio, output_path,
            accent=accent,
            handle=channel.brand.social_handle or "",
            brand=channel.brand.name,
            logo_path=channel.brand.logo_path or "",
            photo_path=photo.source_image_path if photo else None,
            photo_credit=photo.credit if photo else None,
            seed=seed,
        )
        return path, voice
    except Exception as exc:  # any failure (render, staging, bad data) must degrade, not skip the post
        logger.warning("channel %s: motion reel failed (%s); falling back to plain reel", channel.id, exc)
        return None, None


def apply_hook(specs: list[dict], hook: str | None, headline: str) -> list[dict]:
    """Open the reel on the hook: it becomes the first scene's headline (with the
    story's own headline underneath) under a TRENDING NOW label."""
    if hook and specs and specs[0].get("kind") in ("hook", "hero"):
        specs[0] = dict(specs[0], kicker="TRENDING NOW", heading=hook, body=_trim(headline, 105))
    return specs


def _host_cover(host, hosted: list, channel, article, brief, assets, hook: str | None = None) -> str | None:
    """Designed thumbnail (photo + headline + logo) for the reel. Optional:
    any failure just leaves Instagram to pick a frame from the video."""
    try:
        category = getattr(brief.category, "value", str(brief.category))
        photo = next((a for a in assets if getattr(a, "source_image_path", None)), None)
        out = f"/tmp/narovva/{channel.id}/{article.content_id}_cover.jpg"
        make_cover(
            out, headline=hook or brief.headline, kicker="trending now" if hook else category.replace("_", " "),
            accent=channel.brand.category_accents.get(category) or channel.brand.accent_color,
            handle=channel.brand.social_handle or "", logo_path=channel.brand.logo_path,
            photo_path=photo.source_image_path if photo else None,
            font_path=channel.brand.font_path_bold, brand=channel.brand.name,
        )
        h = host.upload(Path(out).read_bytes(), f"{channel.id}/{article.content_id}/cover.jpg", content_type="image/jpeg")
        hosted.append(h)
        return h.url
    except Exception as exc:
        logger.warning("channel %s: cover image skipped (%s)", channel.id, exc)
        return None


def _pick_music_track(
    channel: ChannelConfig, genre_setting: GenreSetting, brief, recent_music_ids=frozenset(),
) -> MusicTrack:
    client_id = resolve_env(channel.credentials.jamendo_client_id_env)
    if not client_id:
        raise JamendoError(
            f"channel {channel.id!r} has publish_format='reel' but credentials.jamendo_client_id_env "
            "is unset (or the env var it names has no value)"
        )
    tags = genre_setting.music_tags or music_tags_for(
        genre_setting.genre, brief.tone, brief.emotions, getattr(brief.category, "value", None),
    )
    return JamendoMusicClient(client_id).pick_track(tags, exclude_ids=recent_music_ids)


def _build_llm(channel: ChannelConfig) -> LLMClient:
    if channel.llm_chain:
        creds = channel.credentials
        return build_llm_chain(channel.llm_chain, {
            "gemini": resolve_env(creds.gemini_api_key_env),
            "openai": resolve_env(creds.openai_api_key_env),
            "openrouter": resolve_env(creds.openrouter_api_key_env),
        })
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
