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
