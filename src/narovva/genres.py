"""Genres narovva adds to info-snipe's built-in ones. Imported by the config
loader, so any channel can list them like a built-in genre."""

from __future__ import annotations

from info_snipe.genres import GenreConfig, register_genre

# What people who build with AI, or work with it every day, actually use: model and
# tool releases, changelogs, how-tos. Labs' own blogs first, then practitioners and
# the trade press. All checked reachable (RSS/Atom) 2026-10.
AI_PRACTITIONER_FEEDS = [
    "https://openai.com/news/rss.xml",
    "https://blog.google/technology/ai/rss/",
    "https://huggingface.co/blog/feed.xml",
    "https://github.blog/changelog/feed/",
    "https://github.blog/ai-and-ml/feed/",
    "https://aws.amazon.com/blogs/machine-learning/feed/",
    "https://developer.nvidia.com/blog/feed/",
    "https://cursor.com/changelog/rss.xml",
    "https://simonwillison.net/atom/everything/",
    "https://www.latent.space/feed",
    "https://www.interconnects.ai/feed",
    "https://www.oneusefulthing.org/feed",
    "https://the-decoder.com/feed/",
    # marktechpost.com dropped: its feed works but every article page answers 403.
    "https://thenewstack.io/ai/feed/",
    "https://stackoverflow.blog/feed/",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://arstechnica.com/ai/feed/",
    "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    "https://hnrss.org/frontpage?points=150",
]

register_genre(
    GenreConfig(
        key="ai_practitioner",
        label="AI for practitioners",
        newsapi_query=(
            '("AI model" OR LLM OR "AI agent" OR "coding assistant" OR Copilot OR ChatGPT OR Claude '
            'OR Gemini OR "open-source model" OR "API") AND (developers OR engineers OR release OR launch)'
        ),
        rss_feeds=AI_PRACTITIONER_FEEDS,
    ),
    overwrite=True,
)

# Health: medical research, public health, health policy. Checked reachable (RSS, and
# the article pages open without a login) 2026-11.
HEALTH_FEEDS = [
    "https://www.statnews.com/feed/",
    "https://medicalxpress.com/rss-feed/",
    "https://www.sciencedaily.com/rss/health_medicine.xml",
    "https://feeds.bbci.co.uk/news/health/rss.xml",
    "https://www.theguardian.com/society/health/rss",
]

register_genre(
    GenreConfig(
        key="health",
        label="Health",
        newsapi_query='(health OR medicine OR medical OR disease OR vaccine OR drug OR FDA OR WHO) AND (study OR trial OR approval OR outbreak OR research)',
        rss_feeds=HEALTH_FEEDS,
    ),
    overwrite=True,
)

# Finance: markets, companies, the economy, personal money. Checked reachable 2026-11.
FINANCE_FEEDS = [
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
]

register_genre(
    GenreConfig(
        key="finance",
        label="Finance",
        newsapi_query='(markets OR stocks OR economy OR inflation OR "interest rates" OR earnings OR "central bank") AND (rise OR fall OR report OR cut OR record)',
        rss_feeds=FINANCE_FEEDS,
    ),
    overwrite=True,
)
