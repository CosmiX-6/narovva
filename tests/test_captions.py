from __future__ import annotations

from poster_core import ContentBrief, StoryCategory

from narovva.captions import PLATFORM_CAPTION_RULES, generate_caption
from narovva.config.schema import CaptionTone
from narovva.platforms import PublishPlatform


class FakeLLM:
    def __init__(self, caption: str, hashtags: list[str]):
        self.caption = caption
        self.hashtags = hashtags
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> dict:
        self.calls.append((system, user))
        return {"caption": self.caption, "hashtags": self.hashtags}


def _brief(**overrides) -> ContentBrief:
    defaults = dict(
        key_event="x",
        summary="A thing happened.",
        headline="Big Tech Thing Happens",
        category=StoryCategory.TECHNOLOGY,
    )
    defaults.update(overrides)
    return ContentBrief(**defaults)


def test_generate_caption_includes_hashtags_footer_style():
    llm = FakeLLM("Something newsworthy occurred today.", ["tech", "ai"])
    result = generate_caption(
        _brief(), publish_platform=PublishPlatform.INSTAGRAM, tone=CaptionTone(), llm=llm,
    )
    assert result.text.startswith("Something newsworthy occurred today.")
    assert "#tech" in result.text
    assert "#ai" in result.text
    assert not result.truncated


def test_extra_hashtags_are_merged_and_deduped():
    llm = FakeLLM("Body.", ["tech"])
    tone = CaptionTone(extra_hashtags=["#tech", "#exampledaily"])
    result = generate_caption(_brief(), publish_platform=PublishPlatform.INSTAGRAM, tone=tone, llm=llm)
    assert result.hashtags.count("#tech") == 1
    assert "#exampledaily" in result.hashtags


def test_platform_hashtag_cap_is_enforced():
    llm = FakeLLM("Body.", [f"tag{i}" for i in range(20)])
    tone = CaptionTone(max_hashtags=20)
    result = generate_caption(_brief(), publish_platform=PublishPlatform.X, tone=tone, llm=llm)
    assert len(result.hashtags) <= PLATFORM_CAPTION_RULES[PublishPlatform.X].max_hashtags


def test_long_caption_is_truncated_to_platform_max_chars():
    llm = FakeLLM("word " * 200, ["tech"])
    result = generate_caption(
        _brief(), publish_platform=PublishPlatform.X, tone=CaptionTone(), llm=llm,
    )
    assert len(result.text) <= PLATFORM_CAPTION_RULES[PublishPlatform.X].max_chars
    assert result.truncated


def test_no_emoji_when_tone_disables_them():
    llm = FakeLLM("Great news! \U0001F680\U0001F525", [])
    tone = CaptionTone(emoji=False)
    result = generate_caption(_brief(), publish_platform=PublishPlatform.INSTAGRAM, tone=tone, llm=llm)
    assert "\U0001F680" not in result.text
    assert "\U0001F525" not in result.text
