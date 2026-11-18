"""End-to-end orchestration for one channel: fetch -> analyze -> render ->
caption -> host -> publish -> record, gated so a transient failure never
permanently burns an article (mark-seen only fires on success, or once the
per-article retry budget is exhausted)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from info_snipe import NewsAPISource, NewsFetcher, RSSSource
from info_snipe.models import Article as FeedArticle
from poster_core import AssetType, Pipeline, PipelineConfig
from poster_core import Platform as RenderPlatform
from poster_core.analysis.llm import GeminiChat, LLMClient, OpenAIChat

from .. import lessons as lesson_series
from ..captions import generate_caption
from ..config.schema import ChannelConfig, GenreSetting
from ..db.engine import ensure_schema, get_connection
from ..db.repo import Repo
from ..dedup import get_store_for_channel
from ..focus import keep_on_topic, screen
from ..hooks.score import formulas_by_id
from ..hooks.voice import drop_banned_sentences
from ..hooks.writer import HookPackage, write_package
from ..imagehost import ImageHostError, VercelBlobImageHost
from ..language import ENGLISH, Language
from ..llm import LLMUnavailable, build_llm_chain
from ..logsafe import redact
from ..metrics.learn import choose_formulas, formula_stats
from ..motion import render_motion_reel, slide_specs_from_assets, total_duration
from ..motion.slides import SCENE_OVERLAP_SECONDS, _trim, time_parts
from ..motion.storyboard import BEAT_MIN, BEAT_TAIL, beat_specs, hook_board, write_storyboard
from ..motion.style import category_label, deck_ui, direct_scenes, stamp_colors, story_subject
from ..music import JamendoError, JamendoMusicClient, MusicTrack, music_tags_for
from ..narration import (
    VIEWER_STYLE,
    build_provider,
    choose_voice,
    default_voices,
    mix_voice_and_music,
    style_for_tone,
    synthesize_lines,
    with_language,
    write_script,
)
from ..platforms import PublishPlatform, render_platform_for
from ..publishers import PublishAsset, get_publisher
from ..settings import Settings, get_settings, resolve_env
from ..tokens import InstagramTokenError, check_token, get_valid_token
from ..video import assemble_reel, make_cover, slide_duration
from ..viral.editor import spoken

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
    hook: HookPackage | None = None  # the hook package the post opened with
    language: str | None = None      # content language of the post ("en", "hi")


def run_channel(
    channel: ChannelConfig,
    *,
    genres_filter: list[str] | None = None,
    dry_run: bool = False,
    max_posts_per_genre: int | None = None,
    max_posts_total: int | None = None,
    language: str | None = None,
) -> ChannelRunResult:
    """Run one channel's genres. `language` ("en", "hi") overrides the content language for
    this run (else each genre's `language`, else the channel's). `max_posts_per_genre` bounds how many
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
    blocked_domains: set[str] = set()  # sites that refused the article download (403) this run
    hook_stats = load_hook_stats(repo, channel)
    llm_down = False
    recent_music_ids: set[str] = set(repo.recent_music_track_ids(channel.id)) if repo and channel.is_video else set()
    recent_voices: set[str] = set(repo.recent_narration_voices(channel.id)) if repo and channel.narration else set()
    series_cache: dict[str, lesson_series.Series] = {}

    try:
        for genre_setting in genres:
            genres_processed.append(genre_setting.genre)
            series = None
            if genre_setting.series:  # a lesson series: its next unposted lesson, not the news
                if genre_setting.series not in series_cache:
                    series_cache[genre_setting.series] = lesson_series.load_series(genre_setting.series)
                series = series_cache[genre_setting.series]
                articles = lesson_series.pending(series, store, genre_setting.genre, limit=1)
            else:
                articles = fetcher.fetch(
                    genre_setting.genre,
                    country=genre_setting.country,
                    limit=genre_setting.limit,
                    mark_seen=False,
                )
                if channel.focus_on:
                    articles = _focus_articles(channel, articles, llm_cache)
            genre_posted = 0
            for article in articles:
                if max_posts_per_genre is not None and genre_posted >= max_posts_per_genre:
                    break
                if _domain(article.url) in blocked_domains:
                    continue  # this site already refused us in this run; don't burn an attempt
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
                    recent_voices=recent_voices, llm_cache=llm_cache, hook_stats=hook_stats,
                    lesson=series.by_content_id(article.content_id) if series else None,
                    language_override=language,
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
                    if _refused(outcome.error):
                        blocked_domains.add(_domain(article.url))

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
                        language=outcome.language,
                        **hook_fields(outcome.hook),
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


def _focus_articles(channel: ChannelConfig, articles: list, llm_cache: dict) -> list:
    """Fresh, on-topic articles for the focus audience, most useful first."""
    kept = keep_on_topic(articles, channel.focus)
    logger.info("channel %s: focus %r keeps %d of %d fetched", channel.id, channel.focus.name, len(kept), len(articles))
    if not kept or not channel.focus.screen_with_llm:
        return kept
    if "llm" not in llm_cache:
        llm_cache["llm"] = _build_llm(channel)
    return screen(llm_cache["llm"], kept, channel.audience)


def _process_one(
    article: FeedArticle, genre_setting: GenreSetting, channel: ChannelConfig, *, dry_run: bool,
    recent_music_ids: set[str] | frozenset[str] = frozenset(),
    recent_voices: set[str] | frozenset[str] = frozenset(),
    llm_cache: dict | None = None,
    hook_style: str | None = None,
    hook_stats: dict | None = None,
    lesson: lesson_series.Lesson | None = None,
    language_override: str | None = None,
) -> _Outcome:
    """`language_override` (run flag) beats the genre's and the channel's content language: with
    Hindi the voice speaks Hindi, the on-screen text stays English and the caption is Hinglish.
    `hook_style` (viral posts, or every post when channel.hooks.enabled): write a
    formula hook with its cover text and caption opener (narovva.hooks), open the
    reel with the hook, title the cover with the cover text, lead the caption with
    the opener. A `lesson` is written from its reference page instead of the
    article, and opens on its own hook."""
    is_reel = channel.is_video
    hook: str | None = None
    package: HookPackage | None = None
    lang = channel.language_for(genre_setting, language_override)
    if hook_style is None and channel.hooks.enabled and lesson is None:
        hook_style = "auto"
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
        article_full, brief = pipeline.analyze(lesson_series.reference_source(lesson) if lesson else article.url)
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
            language=lang,
        )
        banned = channel.banned_words
        if banned:
            caption.text = drop_banned_sentences(caption.text, banned)
        if lesson is not None:  # its own hook leads; the reference page gets its credit
            hook = lesson.hook or None
            if hook and not lang.translated:  # (the Hinglish caption already opens in its own words)
                caption.text = f"{hook}\n\n{caption.text}"
            caption.text = f"{caption.text}\n\n{lesson_series.caption_reference(lesson)}"
        elif hook_style:
            formulas = channel.hooks.formulas
            if hook_stats:
                formulas = choose_formulas(formulas or list(formulas_by_id()), hook_stats,
                                           seed=article.content_id, min_posts=channel.hooks.learn_min_posts)
            package = write_package(
                llm, brief, formulas=formulas, style=hook_style, audience=channel.audience,
                banned=banned, min_score=channel.hooks.min_score, candidates=channel.hooks.candidates,
                language=lang,
            )
            hook = package.hook if package else None
            # An English hook must not lead a Hinglish caption: without an opener, the caption stands alone.
            lead = (package.opener or (None if lang.translated else package.hook)) if package else None
            if lead and not caption.text.startswith(lead):
                caption.text = f"{lead}\n\n{caption.text}"  # the line shown before "more"
    except Exception as exc:
        # A bad article (unextractable page, transient LLM/network error)
        # must not crash the whole channel run -- record it as a failed
        # attempt and let the caller move on to the next article.
        logger.warning("channel %s: failed to process %s: %s", channel.id, article.url, redact(str(exc)))
        return _Outcome(
            status="failed", caption_text="", hashtags=[], asset_types=[], error=redact(str(exc)),
            fatal=isinstance(exc, LLMUnavailable), language=lang.code,
        )

    if dry_run:
        return _Outcome(
            status="dry_run", caption_text=caption.text, hashtags=caption.hashtags,
            asset_types=asset_type_values, hook=package, language=lang.code,
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
                    llm=writer_llm(channel, llm, lesson, llm_cache), recent_voices=recent_voices,
                    seed=article.content_id, hook=hook, when=article.published_at, article=article_full,
                    trending=genre_setting.genre == "viral", lesson=lesson, language=lang,
                    hook_said=package.spoken if package else None,
                )
            if video_path is None:  # plain reel, or motion render failed -> never skip the post
                video_path = assemble_reel(image_paths, track.audio_bytes, reel_path, durations=durations)
            h = host.upload(
                Path(video_path).read_bytes(),
                f"{channel.id}/{article.content_id}/reel.mp4",
                content_type="video/mp4",
            )
            hosted.append(h)
            cover_url = _host_cover(
                host, hosted, channel, article, brief, assets, hook=hook,
                cover_text=(lesson.cover or lesson.title) if lesson else package.cover if package else None,
                trending=genre_setting.genre == "viral", kicker=lesson.series if lesson else None,
            )
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
            narration_voice=narration_voice, language=lang.code,
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
        hook=package,
        language=lang.code,
    )


def _domain(url: str | None) -> str:
    from urllib.parse import urlparse

    host = urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def _refused(error: str | None) -> bool:
    """The site refused the article download (not a transient or model error)."""
    return bool(error) and ("403 Forbidden" in error or "401 Unauthorized" in error) and "Failed to fetch" in error


def load_hook_stats(repo, channel: ChannelConfig) -> dict | None:
    """Per-formula results for hooks.learn (None when off, no DB, or on any error)."""
    if repo is None or not channel.hooks.learn:
        return None
    try:
        return formula_stats(repo, channel.id) or None
    except Exception as exc:  # learning is optional; never block a post on it
        logger.warning("channel %s: hook stats unavailable (%s)", channel.id, exc)
        return None


def hook_fields(package: HookPackage | None) -> dict:
    """post_history columns for a hook package (all None without one)."""
    if package is None:
        return {}
    return {"hook_text": package.hook, "hook_formula": package.formula,
            "hook_score": package.score, "cover_text": package.cover}


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


def _narrate(channel, brief, specs, track, *, recent_voices, seed, language: Language = ENGLISH, **timing):
    """Voice-over for specs that carry `lines` (one to three spoken lines
    each): one TTS clip per scene in a voice not used recently (a scene's
    lines read as one passage, which sounds natural and keeps requests to
    one per scene) -> each line's share of the clip by length -> every scene
    timed to its speech (`time_parts`, so captions and builds follow the
    voice) -> music ducked under the voice. Tries the configured provider,
    then each fallback. Returns (mixed_audio, voice). `language`: the voice's (Hindi uses the
    Hindi voices and tells the engine to speak Hindi)."""
    cfg = channel.narration
    env_names = {
        "openai": channel.credentials.openai_api_key_env,
        "gemini": channel.credentials.gemini_api_key_env,
        "elevenlabs": channel.credentials.elevenlabs_api_key_env,
        "kokoro": None,  # local voice, no key
    }
    passages = [" ".join(spec["lines"]) for spec in specs]
    style = style_for_tone(brief.tone, language)
    failures: list[str] = []
    for attempt, name in enumerate([cfg.provider, *cfg.fallback_providers]):
        try:
            provider = build_provider(name, resolve_env(env_names[name]) or "", cfg.model if attempt == 0 else None)
            own = cfg.voices_by_language.get(language.code) or (None if language.translated else cfg.voices)
            pool = (own if attempt == 0 and own else None) or default_voices(name, language)
            pool = [v for v in pool if v not in cfg.exclude_voices]  # all excluded: skip to the next provider
            voice = choose_voice(pool, recent_voices, seed)
            clips = _speak(provider, passages, specs, pool, voice, style, seed, language)
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            logger.warning("channel %s: narration via %s failed (%s)", channel.id, name, exc)
            continue
        starts, t = [], 0.0
        for spec, clip in zip(specs, clips):
            share = [len(line) + 1 for line in spec["lines"]]
            time_parts(spec, [clip.seconds * n / sum(share) for n in share], gap=0.0, **timing)
            starts.append(t + spec["parts"][0]["at"])  # the picture leads the voice slightly
            if not cfg.captions:  # the timing still drives the scene's builds
                for part in spec["parts"]:
                    part.pop("caption", None)
            t += spec["duration"] - SCENE_OVERLAP_SECONDS
        total = total_duration([s["duration"] for s in specs])
        audio = mix_voice_and_music(clips, starts, track.audio_bytes, total)
        logger.info("channel %s: narrated with %s voice %r (%.0fs reel)", channel.id, name, voice, total)
        return audio, voice
    raise RuntimeError("; ".join(failures) or "no narration provider configured")


def _speak(provider, passages: list[str], specs: list[dict], pool: list[str], voice: str, style, seed: str,
           language: Language = ENGLISH) -> list:
    """One clip per scene: the narrator's voice, except the viewer's questions
    (storyboard "ask" beats), which a second voice from the pool reads, curious."""
    asks = {i for i, spec in enumerate(specs) if spec.get("speaker") == "viewer"}
    clips: list = [None] * len(passages)
    jobs = [([i for i in range(len(passages)) if i not in asks], voice, style)]
    if asks:
        other = choose_voice([v for v in pool if v != voice] or pool, frozenset(), seed + ":viewer")
        jobs.append((sorted(asks), other, with_language(VIEWER_STYLE, language)))
    for idx, v, st in jobs:
        if idx:
            for i, clip in zip(idx, synthesize_lines(provider, [passages[i] for i in idx], voice=v, style=st,
                                                     lang=language)):
                clips[i] = clip
    return clips


def _try_motion_reel(
    channel, assets, brief, track: MusicTrack, output_path: str, *,
    llm=None, recent_voices=frozenset(), seed: str = "", hook: str | None = None,
    when: datetime | None = None, article=None, trending: bool = False, lesson=None,
    language: Language = ENGLISH, hook_said: str | None = None,
) -> tuple[str | None, str | None]:
    """Render the HyperFrames motion reel (optionally narrated). Returns
    (mp4 path, narration voice); path is None (after logging why) so the
    caller falls back to the Ken-Burns reel.

    The story comes from the explainer storyboard (motion.story.mode
    "storyboard"), else from poster-core's carousel slides with a one-line-
    per-slide script. A narration failure only drops the voice; the story,
    stamps and emphasis stay."""
    try:
        category = getattr(brief.category, "value", str(brief.category))
        accent = channel.brand.category_accents.get(category) or channel.brand.accent_color
        look = channel.motion
        stamps = look.stamps.max_per_reel if look.stamps.enabled else 0
        brand = channel.brand.name.title() if channel.brand.name.isupper() else channel.brand.name
        # The hook as the voice says it: English is spelled for the ear; a Hindi voice says its own
        # Hindi version (None when the model gave none: the writer then says the hook in Hindi itself).
        said = (hook_said if language.translated else spoken(hook)) if hook else None
        spoken_brand = channel.narration.spoken_names.get(language.code) if channel.narration else None
        if language.translated and channel.narration and not spoken_brand:
            logger.warning("channel %s: narration.spoken_names.%s is not set, so the voice reads the channel "
                           "name in Latin letters (badly); give its %s spelling", channel.id, language.code,
                           language.name)
        board = None
        if llm is not None and (look.story.mode in ("storyboard", "animated") or lesson is not None):
            board = write_storyboard(  # a lesson runs as long as its explanation needs (its own budget)
                llm, brief, article, brand=brand, max_beats=lesson.max_beats if lesson else look.story.max_beats,
                target_seconds=lesson.target_seconds if lesson else look.story.target_seconds, max_stamps=stamps,
                when=(when or datetime.now()).strftime("%d %b %Y"), hook=hook, audience=channel.audience,
                max_asks=look.story.viewer_questions, mode=look.story.mode, lesson=lesson,
                said=said, language=language, spoken_brand=spoken_brand,
            )
        if board is not None:
            hook_board(board, hook, said, brief.headline, trending=trending)
            build = lambda: beat_specs(board, stamp_colors=stamp_colors(look), heading_marks=look.heading_marks)
            subject, timing = board.subject, {"min_hold": BEAT_MIN, "tail": BEAT_TAIL}
        else:
            slides = lambda: apply_hook(slide_specs_from_assets(assets), hook, brief.headline, trending=trending)
            script = None
            if llm is not None and (channel.narration or look.wants_direction):
                script = write_script(
                    llm, brief, slides(), brand=channel.brand.name, max_stamps=stamps,
                    hook=said, hook_screen=hook, audience=channel.audience,
                    language=language, spoken_brand=spoken_brand,
                )
            build = lambda: direct_scenes(slides(), script, look) if script else slides()
            subject, timing = (script.subject if script else None), {}
        specs = build()
        audio, voice = track.audio_bytes, None
        if channel.narration and all(spec.get("lines") for spec in specs):
            try:
                audio, voice = _narrate(channel, brief, specs, track, recent_voices=recent_voices, seed=seed,
                                        language=language, **timing)
            except Exception as exc:  # no voice is better than no post
                logger.warning("channel %s: narration failed (%s); posting music-only", channel.id, exc)
                specs = build()
                audio, voice = track.audio_bytes, None
        ui = deck_ui(
            look, subject=story_subject(subject, brief),
            category=category_label(category), brand=channel.brand.name, when=when,
        )
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
            ui=ui,
        )
        return path, voice
    except Exception as exc:  # any failure (render, staging, bad data) must degrade, not skip the post
        logger.warning("channel %s: motion reel failed (%s); falling back to plain reel", channel.id, exc)
        return None, None


def apply_hook(specs: list[dict], hook: str | None, headline: str, trending: bool = True) -> list[dict]:
    """Open the reel on the hook: it becomes the first scene's headline (with the
    story's own headline underneath), under a TRENDING NOW label for viral posts."""
    if hook and specs and specs[0].get("kind") in ("hook", "hero"):
        extra = {"kicker": "TRENDING NOW"} if trending else {}
        specs[0] = dict(specs[0], heading=hook, body=_trim(headline, 105), **extra)
    return specs


def _host_cover(
    host, hosted: list, channel, article, brief, assets, hook: str | None = None,
    cover_text: str | None = None, trending: bool = False, kicker: str | None = None,
) -> str | None:
    """Designed thumbnail (photo + title + logo) for the reel. The title is the
    package's short cover text when there is one (so cover and hook say different
    things), else the hook, else the headline. Optional: any failure just leaves
    Instagram to pick a frame from the video."""
    try:
        category = getattr(brief.category, "value", str(brief.category))
        photo = next((a for a in assets if getattr(a, "source_image_path", None)), None)
        out = f"/tmp/narovva/{channel.id}/{article.content_id}_cover.jpg"
        make_cover(
            out, headline=cover_text or hook or brief.headline,
            kicker=kicker or ("trending now" if trending else category.replace("_", " ")),
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


def _llm_keys(channel: ChannelConfig) -> dict:
    creds = channel.credentials
    return {
        "gemini": resolve_env(creds.gemini_api_key_env),
        "openai": resolve_env(creds.openai_api_key_env),
        "openrouter": resolve_env(creds.openrouter_api_key_env),
    }


def writer_llm(channel: ChannelConfig, llm: LLMClient, lesson=None, llm_cache: dict | None = None) -> LLMClient:
    """The model chain for the storyboard writer: channel.writer.chain first (for lessons, or
    every post), then llm_chain as the fallback. Built once per run; `llm` when unset."""
    w = channel.writer
    if not w.chain or (w.use_for == "lessons" and lesson is None):
        return llm
    if llm_cache is not None and "writer" in llm_cache:
        return llm_cache["writer"]
    try:
        writer = build_llm_chain(list(dict.fromkeys([*w.chain, *(channel.llm_chain or [])])), _llm_keys(channel))
    except LLMUnavailable as exc:  # no key for any writer model: the normal chain writes
        logger.warning("channel %s: writer chain unavailable (%s); using llm_chain", channel.id, exc)
        writer = llm
    if llm_cache is not None:
        llm_cache["writer"] = writer
    return writer


def _build_llm(channel: ChannelConfig) -> LLMClient:
    if channel.llm_chain:
        return build_llm_chain(channel.llm_chain, _llm_keys(channel))
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
