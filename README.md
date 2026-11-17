# narovva

[![CI](https://github.com/CosmiX-6/narovva/actions/workflows/ci.yml/badge.svg)](https://github.com/CosmiX-6/narovva/actions/workflows/ci.yml)

**News in, Instagram Reels out.** narovva finds the most useful fresh story for a
topic, writes an explainer for it, renders a narrated motion-graphics Reel with
captions and music, writes the caption and hashtags, and publishes it to
Instagram, on a schedule, for as many channels as you configure.

It runs the live account [@contextunfiltered](https://www.instagram.com/contextunfiltered/)
(AI, tech, health and finance news, plus "How AI works" lessons), whose full config is
[`config/channels/example-tech-ig.yaml`](config/channels/example-tech-ig.yaml).

- **Finds stories** per genre from RSS (and optionally NewsAPI) via
  [`info-snipe`](https://github.com/CosmiX-6/info-snipe), never posting the same
  story twice; optional "viral" slots post whatever many outlets are covering right now.
- **Teaches** lesson series between the news ([`config/lessons/`](config/lessons/)):
  one idea per video, told through one metaphor and checked against its reference page.
- **Writes** with a fallback chain of text models (Gemini, OpenAI, OpenRouter free
  models): a scored hook, a storyboard for the video, the voice-over, the caption.
  Every number shown must appear in the article.
- **Renders** animated Reels (HTML + GSAP + three.js rendered by
  [HyperFrames](https://github.com/heygen-com/hyperframes)): one continuous 3D world
  where characters and objects act the story out, burned-in captions and a voice-over
  (OpenAI, Gemini, or free local Kokoro). Any render failure falls back to a simple
  slideshow Reel, so a post is never lost.
- **Publishes** through the official Instagram API, tracks every post in Postgres,
  and measures each post's views and watch time daily to learn which hooks work.

## How it fits together

```
config/channels/*.yaml ──> ChannelConfig (validated)
        │
        ▼
info_snipe: fresh, de-duplicated articles for the genre
        │
        ▼
poster_core: article ──> brief (facts, figures, tone) + cover/slide images
        │
        ├──> narovva.hooks / captions      hook, cover title, caption, hashtags
        ├──> narovva.motion.storyboard     explainer beats ──> scenes
        ├──> narovva.narration             voice-over, timed captions
        └──> narovva.motion (HyperFrames)  the Reel (MP4)
        │
        ▼
Vercel Blob (temporary public URL) ──> Instagram API ──> published Reel
        │
        ▼
Postgres: post history, dedup, metrics, refreshed token
```

`poster-core` ([repo](https://github.com/CosmiX-6/poster-core)) does the article
analysis and still images; narovva adds everything from channel config to the
published post.

## Quick start

### 1. Requirements

- Python 3.11+
- For motion Reels: Node 22+ and FFmpeg
- Optional but recommended: a Postgres database ([Neon](https://neon.tech)'s free tier works).
  Without one narovva runs, but cannot remember what it already posted.
- A text-model key: `GOOGLE_API_KEY` ([free](https://aistudio.google.com/apikey)) or `OPENAI_API_KEY`
- To publish: an Instagram professional (business or creator) account, a Meta app with
  the Instagram API use case ([setup](docs/operations.md#creating-the-meta-app)), its access token, and a Vercel Blob
  store (`BLOB_READ_WRITE_TOKEN`) to host the video while Instagram fetches it

### 2. Install

```bash
git clone https://github.com/CosmiX-6/narovva.git
cd narovva
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev,narration-local]"

# Motion Reels: the pinned HyperFrames CLI and its headless Chrome (~170 MB, once)
npm ci
npx hyperframes browser ensure
```

Extras: `narration-local` adds the free Kokoro voice (no API key; ~350 MB model
downloaded on first use), `trending` adds Google Trends hashtags, `dev` adds pytest and ruff.

### 3. Configure

```bash
cp .env.example .env                 # fill in what you use; every variable is explained there
cp config/channels/example-tech-ig.yaml config/channels/my-channel.yaml
```

In your channel file, set `ig_business_account_id` (your Instagram user id:
`https://graph.instagram.com/v21.0/me?fields=id,username` with your token), the
`brand` block (name, colours, logo, handle), the `genres`, and the names of the
env vars holding your credentials. Delete `config/channels/example-tech-ig.yaml`
(or set `enabled: false` in it) so `run-due` does not try to post as Context
Unfiltered. Every option is commented in that file.

Load `.env` into your shell:

```bash
set -a; source .env; set +a          # Linux/macOS
```

```powershell
# Windows PowerShell
Get-Content .env | Where-Object { $_ -match '^[A-Za-z_][A-Za-z0-9_]*=.' } | ForEach-Object { $k, $v = $_ -split '=', 2; Set-Item "env:$k" $v }
```

### 4. Try it without posting

```bash
narovva run-channel config/channels/my-channel.yaml --dry-run
python -m narovva.motion sample.mp4  # render the built-in sample Reel
```

`--dry-run` fetches, analyses, renders and writes the caption, but never uploads or publishes.

### 5. Post

```bash
narovva run-channel config/channels/my-channel.yaml --genre ai --max-posts-per-genre 1
narovva run-due                      # every channel/genre that is due right now
```

To post automatically every hour, run it on GitHub Actions: see
**[docs/operations.md](docs/operations.md)** for the secrets to add, what each
workflow does, scheduling, costs, and token rotation.

## Commands

| Command | What it does |
|---|---|
| `narovva run-due` | Post for every channel/genre that is due (what the hourly job runs) |
| `narovva run-channel <cfg> [--genre G] [--dry-run]` | Run one channel now |
| `narovva run-viral <cfg> [--force]` / `viral-scan <cfg> --editor` | Post / preview the story going viral right now |
| `narovva refresh-token <cfg>` | Renew the Instagram token (weekly job) |
| `narovva collect-metrics <cfg>` / `performance-report <cfg>` | Snapshot post insights / rank posts against the channel's median |
| `narovva insights-probe <cfg>` / `audio-probe <cfg>` | Read-only checks of what the token can access |
| `narovva sweep-blobs` | Delete hosted media a crashed run left behind |
| `python -m narovva.motion out.mp4` | Render the sample Reel (needs Node toolchain) |
| `python -m narovva.motion.preview out/` | Screenshot every scene with local Chrome (no Node needed) |
| `python -m narovva.narration.demo <provider> out/` | Read a sample line in each voice of a provider |

## Documentation

- [Operations](docs/operations.md): GitHub Actions, secrets, scheduling, costs, token rotation, troubleshooting
- [Motion Reels](docs/motion-reels.md): the storyboard, the scene library, narration, captions, configuring the look
- [Hooks and performance metrics](docs/hooks-and-metrics.md): hook formulas, scoring, the daily report, learning
- [Viral posts and focus mode](docs/viral-and-focus.md)
- [Text models](docs/text-models.md): the fallback chain across Gemini, OpenAI and OpenRouter
- [`.claude/skills/context-unfiltered-storytelling.md`](.claude/skills/context-unfiltered-storytelling.md): the editorial guide the prompts follow

## Development

```bash
pip install -e ".[dev]"
ruff check src tests
pytest                               # offline; no keys or network needed
```

The real video render test runs when the HyperFrames CLI is installed (`npm ci`);
CI also renders a full sample Reel in the "Motion reel smoke test" workflow.

`poster-core` and `info-snipe` are pinned to git commits in `pyproject.toml`. To
work against local checkouts of them, `cp uv.toml.example uv.toml` and `uv sync`.
To bump a pin, push the change to that repo first, then update the commit hash in
`pyproject.toml`.

## Security

API keys and tokens are only ever read from environment variables (Actions
secrets in CI); channel files hold the variable *names*. `narovva.logsafe`
redacts tokens from every log line and stored error. If you find a security
problem, see [SECURITY.md](SECURITY.md).

## License

MIT, see [LICENSE](LICENSE). Vendored fonts, icons and libraries keep their own
licenses: see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The Context
Unfiltered name and logo (`assets/logo/CU.png`) identify the live channel; use your
own brand for your channels.
