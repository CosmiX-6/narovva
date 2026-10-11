# narovva

A configurable pipeline that finds the best news for a genre, turns it into a
rendered social-media image plus a caption, and publishes it, per channel
(one account on one platform, with one or more genres each). Built on top of
two sibling packages instead of reimplementing them:

- [`info-snipe`](https://github.com/CosmiX-6/info-snipe) fetches
  de-duplicated news by genre.
- [`poster-core`](https://github.com/CosmiX-6/poster-core) turns one article
  into rendered PNG social assets.

narovva adds: channel/genre configuration, caption generation, ephemeral
image hosting, a social publisher (Instagram Graph API first), post-history
tracking, and the orchestration that ties it all together.

## How it fits together

```
config/channels/*.yaml  -->  ChannelConfig (pydantic)
        |
        v
info_snipe.NewsFetcher.fetch(genre, ..., mark_seen=False)  -->  candidate articles
        |
        v
poster_core.Pipeline.analyze(article.url)  -->  ContentBrief
        |
        +--> poster_core.Pipeline.run_from_brief(...)  -->  rendered PNGs
        |
        +--> narovva.captions.generate_caption(brief, ...)  -->  caption + hashtags
        |
        v
narovva.imagehost (Vercel Blob, ephemeral)  -->  public image URL(s)
        |
        v
narovva.publishers (Instagram Graph API)  -->  published post
        |
        v
Postgres: post_history / channel_run_log  (mark-seen in the dedup store only on success)
```

A render or publish failure never permanently burns an article: `fetch()` is
always called with `mark_seen=False`, and the dedup store is only told an
article was seen once its own attempt actually succeeds, or after
`max_publish_attempts` failed tries.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # fill in what you have; see below
```

### Local development against live sibling checkouts

By default `pyproject.toml`/`requirements.txt` pin `poster-core` and
`info-snipe` to specific git commits (required for Vercel's build, which has
no sibling checkout to install from). For local development against your
live checkouts of those repos instead:

```bash
cp uv.toml.example uv.toml   # git-ignored
uv sync
```

Bumping a pin: commit and push the change in `poster-core` or `info-snipe`
first (their own repo, their own commit), copy the resulting SHA, then
update it in both `pyproject.toml` and `requirements.txt` here.

### Environment variables

See `.env.example` for the full list and where each one is used:
`DATABASE_URL` (Postgres, for post history / run log / refreshed Instagram
tokens), `BLOB_READ_WRITE_TOKEN` (Vercel Blob), `CRON_SECRET`,
`TOKEN_ENCRYPTION_KEY`, `OPENAI_API_KEY` / `GOOGLE_API_KEY`, `NEWSAPI_KEY`
(optional), and per-channel `IG_ACCESS_TOKEN__<channel_id>` /
`IG_APP_ID__<channel_id>` / `IG_APP_SECRET__<channel_id>`.

Without `DATABASE_URL` set, narovva still runs -- it just skips
post-history/run-log persistence (a warning is logged), which is useful for
a first smoke test before Postgres is wired up.

## Configuring a channel

Copy `config/channels/example-tech-ig.yaml`, rename it, and fill in your
Instagram Business Account id, brand kit, genres, and caption tone. The
filename (minus `.yaml`) becomes the channel id unless you set `id`
explicitly. Genres reference `info_snipe` genre keys (`ai`, `tech`, `world`,
`business`, `science` are built in); a channel wanting a genre info-snipe
doesn't ship yet can register one at startup via `info_snipe.register_genre`.

## Running it

```bash
# Fetch, analyze, render and caption -- no images hosted, nothing published
narovva run-channel config/channels/example-tech-ig.yaml --dry-run

# The real thing: hosts images on Vercel Blob, publishes to Instagram
narovva run-channel config/channels/example-tech-ig.yaml

# Only the "ai" genre this run
narovva run-channel config/channels/example-tech-ig.yaml --genre ai

# Every channel/genre currently due, per each genre's cadence_minutes
narovva run-due
```

## Fonts

Vercel's Python runtime has no system fonts. Set `brand.font_path_bold` /
`brand.font_path_regular` in a channel's config to a `.ttf` bundled in
`assets/fonts/` (poster-core falls back to system font paths only when these
are unset, which won't resolve on Vercel).

## Status

Phase 1 (this state): the full chain runs locally via the CLI end to end
against real Instagram/Vercel Blob APIs. Phase 2 adds the Vercel `api/`
cron entrypoints and switches dedup to a Postgres-backed store so it works
across serverless invocations with no local disk. Phase 3 adds X and
Threads publishers. See the project's plan doc for the full breakdown.

## Tests

```bash
pytest
```

Offline: config loading/validation and caption rules run with no network
calls or API keys. Exercising the real pipeline (`run-channel` without
`--dry-run`) needs a configured channel, a Postgres `DATABASE_URL`, a
`BLOB_READ_WRITE_TOKEN`, an LLM API key, and real Instagram credentials.

## Motion reels (HyperFrames)

`publish_format: motion_reel` builds the Reel from HTML/CSS/GSAP motion graphics
rendered by [HyperFrames](https://github.com/heygen-com/hyperframes) (headless
Chrome + FFmpeg) instead of a Ken-Burns slideshow of the PNG slides. One scene
per slide, with a per-kind animation (hook, text, evidence, stats, timeline,
money_flow, comparison, quote, conclusion, cta), the channel's brand colours
and logo, and the music mixed in. If the motion render fails for any reason the
post falls back to the plain `reel` format, so nothing is skipped.

- Needs Node 22+, FFmpeg and `npm ci` (pins `hyperframes`); first run also needs
  `npx hyperframes browser ensure` (Chrome Headless Shell). `HYPERFRAMES_BIN`
  overrides the CLI location.
- Preview everything locally: `python -m narovva.motion out.mp4` renders a sample
  deck covering every slide kind (~2 min for 43 s of video).
- Templates live in `src/narovva/motion/templates/reel/`; GSAP and the Archivo
  Black / Inter fonts (OFL) are vendored so renders need no CDN.
- Each Reel records its music track in `post_history.music_track_id` (migration
  `0002`), and later posts avoid recently used tracks. Track tags come from the
  genre, `brief.tone`, `brief.emotions` and `brief.category`.

### Pacing and narration

- Reels are cut fast: text lands in ~0.3 s, slides hold 2-4 s (long copy is trimmed
  on screen; the caption and voice carry the detail), and scenes change with real
  transitions (push / whip / zoom-through) instead of fades.
- `narration:` in the channel YAML adds a voice-over (`openai`, `gemini` or
  `elevenlabs`). The LLM writes one short spoken line per slide, a voice that was not
  used recently is chosen (`post_history.narration_voice`), each slide lasts as long as
  its line, and the music ducks under the voice (-14 LUFS master). If anything in
  that chain fails the reel still posts, music only.
- Audition voices by ear: run **Actions -> Audition narration voices** (or
  `python -m narovva.narration.demo openai out/`) and listen to the MP3 artifact.
