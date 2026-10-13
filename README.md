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
  deck covering every slide kind, with a synthetic photo and captions.
- Templates live in `src/narovva/motion/templates/reel/`; GSAP and the Archivo
  Black / Inter fonts (OFL) are vendored so renders need no CDN.
- Each Reel records its music track in `post_history.music_track_id` (migration
  `0002`), and later posts avoid recently used tracks. Track tags come from the
  genre, `brief.tone`, `brief.emotions` and `brief.category`.

### What is on screen

- **The article's own photo.** poster-core exposes the photo it sourced
  (`GeneratedAsset.source_image_path`); `narovva.motion.photo` turns it into a sharp
  framed card on the opening scene (most article photos are ~1200x630, so they are
  shown at their real size rather than stretched to fill 1080x1920) and a blurred,
  darkened copy that sits behind every scene. A tall, large photo goes full-bleed
  instead. A photo that is too small, banner-shaped or really a logo is skipped and
  the reel runs on its generative background alone.
- **Charts from the story's numbers.** `narovva.motion.dataviz` parses the stated
  figures: a percentage becomes a ring that fills, figures that share a unit become
  bars on one scale, a comparison becomes two bars with the change between them, and
  the timeline and money trail draw themselves in. Only numbers the article states
  are drawn, and two figures share a scale only when they share a unit.
- **A background that never sits still.** A canvas field of light streaks in the
  category accent (`templates/reel/ambient.js`), seeded per story so no two reels
  match, which flares at each cut and settles while the text is read.
- Everything is a pure function of timeline time (no clocks, no unseeded
  randomness), because HyperFrames renders by seeking to frames in any order.

Work on the template without the Node toolchain: `python -m narovva.motion.preview
out/` screenshots two frames of every scene from a local Chrome and writes a contact
sheet (`--photo PATH|none`, `--no-captions`, `--at 1.5,4`, `--via T` to check a frame
is the same when reached out of order).

### Pacing and narration

- Reels are quick updates: at most 7 scenes (the opener, the CTA and the strongest
  data scenes; prose scenes are dropped first), text lands in ~0.3 s, scenes hold
  1.7-3.6 s (long copy is trimmed on screen; the caption and voice carry the detail),
  spoken lines are 6-12 words and the voice runs ~20% above natural pace. A typical
  reel is 20-30 s. Scenes change with real transitions (push / whip / zoom-through).
- Each reel gets a designed cover (`narovva.video.cover`): the article photo (or a
  branded card), the category, the headline and the logo, kept inside the 4:5 band the
  profile grid shows. If it can't be made, Instagram picks a frame.
- `narration:` in the channel YAML adds a voice-over (`openai`, `gemini` or
  `elevenlabs`). The LLM writes one short spoken line per slide, a voice that was not
  used recently is chosen (`post_history.narration_voice`), each slide lasts as long as
  its line, and the music ducks under the voice (-14 LUFS master). If anything in
  that chain fails the reel still posts, music only.
- With narration on, the spoken line is burned in as captions that light up word by
  word (most people watch with the sound off); the on-screen paragraph gives way to
  it. `narration.captions: false` turns them off.
- Audition voices by ear: run **Actions -> Audition narration voices** (or
  `python -m narovva.narration.demo openai out/`) and listen to the MP3 artifact.

## Logs and secrets

The Instagram Graph API takes the access token as a query parameter, so request URLs
are sensitive. `narovva.logsafe` (installed by the CLI) holds the HTTP client loggers
at WARNING and redacts tokens/keys from every log record, error message and stored
run error. Tokens are never printed; if one was exposed in old logs, regenerate it.

## Text-model fallback chain

Each article costs several LLM calls (analysis, caption, voice-over script). A single
free-tier model runs out of daily quota after a few articles and answers 503 when busy,
so `llm_chain:` in the channel YAML lists models in order (`provider[:model]`; providers
`gemini`, `openai`, `openrouter`). A model whose quota is spent is skipped for the rest of
the run, an overloaded one is retried once and rested for two minutes, and a short
per-minute rate limit is waited out. Free-tier quotas are per model, so each Gemini model
is a separate pool; OpenRouter `:free` models are a separate provider (secret
`OPENROUTER_API_KEY`; entries without a key are skipped). When no model is left the run
stops at once, without recording failed attempts against the articles. Free model names
change often; edit the list, no code change needed.
