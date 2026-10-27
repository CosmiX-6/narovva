# Operations: running narovva on GitHub Actions

The repository runs itself: GitHub Actions posts every hour, measures posts daily
and renews the Instagram token weekly. This page covers the secrets to add, what
each workflow does, scheduling, costs, and what to do when something breaks.

## Workflows

| Workflow | Trigger | What it does |
|---|---|---|
| **Hourly publish** (`hourly.yml`) | every hour, or manually (optionally forcing a genre or a viral post) | `narovva run-due`: posts for each channel that is due, then sweeps orphaned media. Rendered Reels are kept as a run artifact for 7 days. |
| **Performance metrics** (`metrics.yml`) | daily 02:41 UTC, or manually | Snapshots each recent post's insights into Postgres and writes the performance report to the run's summary page. |
| **Refresh Instagram token** (`refresh-instagram-token.yml`) | Mondays 06:17 UTC, or manually | Renews the 60-day token and stores it, encrypted, in Postgres. |
| **CI** (`ci.yml`) | push to `main`, pull requests | `ruff` and the offline test suite on Python 3.11 and 3.12. No secrets. |
| **Motion reel smoke test** (`motion-smoke.yml`) | changes under `src/narovva/motion/`, or manually | Installs the HyperFrames toolchain on a clean runner, runs the tests including a real render, and uploads a sample Reel. No secrets. |
| **Audition narration voices** (`narration-sample.yml`) | manual | Reads one sample line in every voice of a provider and uploads the MP3s. |
| **Instagram insights probe** / **audio probe** | manual | Read-only checks of what the token can access. |

Only people with write access can start a workflow manually. Pull requests from
forks run CI only, without secrets.

## Secrets

Add these under **Settings → Secrets and variables → Actions → New repository
secret**. Names must match exactly; values are never printed in logs.

| Secret | Needed for | Required |
|---|---|---|
| `IG_ACCESS_TOKEN__EXAMPLE_TECH_IG` | publishing, metrics, token refresh | yes |
| `DATABASE_URL` | post history, dedup, metrics, refreshed token | yes for scheduled runs |
| `TOKEN_ENCRYPTION_KEY` | encrypting the refreshed token in Postgres | yes with `DATABASE_URL` |
| `BLOB_READ_WRITE_TOKEN` | hosting media while Instagram fetches it | yes |
| `GOOGLE_API_KEY` | Gemini text models and Gemini voices | one text-model key is required |
| `OPENAI_API_KEY` | OpenAI text models and voices (paid) | optional |
| `OPENROUTER_API_KEY` | OpenRouter `:free` text models | optional |
| `JAMENDO_CLIENT_ID__EXAMPLE_TECH_IG` | background music | optional |
| `NEWSAPI_KEY` | extra news source | optional |
| `ELEVENLABS_API_KEY` | voice audition only | optional |

The workflow files map each secret to the env var name the channel config
expects (for example `IG_ACCESS_TOKEN__example_tech_ig`). For your own channel,
add secrets with your own names and change the `env:` blocks and the config path in
`hourly.yml`, `metrics.yml` and `refresh-instagram-token.yml`.

The token needs the `instagram_business_basic` and
`instagram_business_content_publish` permissions, plus
`instagram_business_manage_insights` for metrics. Run **Instagram insights probe**
to check the last one.

## Scheduling

GitHub's `schedule:` trigger is best effort: under load, hourly runs start late or
are dropped. For a reliable cadence, have an outside scheduler call the workflow's
dispatch endpoint as well. Overlapping triggers are safe: `hourly.yml` runs one
job at a time and each run posts only what is due.

```bash
# A fine-grained personal access token limited to this repository, with
# "Actions: Read and write" permission, kept in the scheduler's own secret store.
curl -X POST \
  -H "Authorization: Bearer $GH_DISPATCH_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/<owner>/narovva/actions/workflows/hourly.yml/dispatches \
  -d '{"ref":"main"}'
```

Any service that can send a scheduled POST with a header works, such as a
serverless function on a cron, or a hosted cron service.

How often a channel posts is set in its config: `rotation_minutes` (one post per
interval, cycling through genres), the `viral.slots`, and `focus`.

## Costs

narovva can run on free tiers end to end. What uses paid or limited quota:

| Service | Use | Cost notes |
|---|---|---|
| GitHub Actions | everything above | **Free for public repositories.** Private repositories on the Free plan get 2,000 minutes a month; a run that posts takes about 9–10 minutes (rendering) and an hourly check that posts nothing about 1.5 minutes, so an hourly schedule exceeds that. When the minutes run out, runs stop with "recent account payments have failed or your spending limit needs to be increased". |
| Gemini API | text, optional voices | Free tier with per-model daily limits; the [text-model chain](text-models.md) moves to the next model when one is used up. |
| OpenAI API | text, optional voices | Paid per use. |
| OpenRouter | text | `:free` models cost nothing but are rate limited. |
| Kokoro | voice | Free, runs inside the job. Used automatically when the paid voices are out of quota. |
| Postgres (e.g. Neon) | history, metrics | Free tier is plenty. |
| Vercel Blob | media hosting | Free tier; each file is deleted right after publishing. |
| Instagram API, Jamendo, Google Trends | publishing, music, hashtags | Free. |

## The Instagram token

Long-lived tokens last 60 days and can only be renewed while still valid, so the
weekly refresh keeps them alive and stores each new one, encrypted, in Postgres.
narovva prefers the stored token. If Instagram rejects it and accepts the one in
the secret, it uses the secret instead, and the next refresh stores it.

**If a token leaks** (it appeared in a log, a commit, a screenshot):

1. Revoke it: in Instagram, **Settings → Website permissions → Apps and websites**,
   remove your app. This invalidates the tokens issued to it.
2. Create a new one: Meta App Dashboard → your app → **Instagram → API setup with
   Instagram login → Generate access tokens**.
3. Paste it into the `IG_ACCESS_TOKEN__…` secret. Nothing else: the next run uses it
   and the next weekly refresh stores it.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Runs fail within seconds: "recent account payments have failed or your spending limit needs to be increased" | Actions minutes used up (private repositories only). Make the repository public, raise the spending limit, or post less often. |
| "Instagram rejected the access token" | The token expired or was revoked. Generate a new one (steps above). |
| Reels post with music but no voice | Every voice provider failed, usually quota. Check the run log for `narration via … failed`; Kokoro needs the `narration-local` extra. |
| "storyboard reply did not validate; using the slide-based reel" | The model's storyboard failed the fact checks; that post used the simpler slide-based Reel. Occasional is normal. |
| "quota exhausted; skipping it for the rest of the run" | A free-tier model ran out for the day; the next model in `llm_chain` answers. |
| "Nothing due." | Correct: the channel posted recently (`rotation_minutes`). |
| Metrics report says "Nothing to compare yet" | It needs posts measured at 48 hours old, with at least 5 earlier ones. |
