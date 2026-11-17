from __future__ import annotations

import pytest

from narovva import lessons
from narovva.config.schema import GenreSetting


def test_the_shipped_series_loads():
    series = lessons.load_series("how-ai-works")
    assert series.name == "How AI works" and series.kicker == "HOW AI WORKS" and len(series.lessons) >= 50
    assert len({x.id for x in series.lessons}) == len(series.lessons)
    assert all(x.hook and x.reference.startswith("https://en.wikipedia.org/wiki/") for x in series.lessons)
    assert series.lessons[0].content_id == "lesson:how-ai-works:tokens"


def test_a_malformed_series_is_refused(tmp_path):
    (tmp_path / "bad.yaml").write_text("lessons:\n  - id: a\n    title: A\n    reference: http://x\n", encoding="utf-8")
    with pytest.raises(ValueError, match="https"):
        lessons.load_series("bad", tmp_path)
    (tmp_path / "dup.yaml").write_text(
        "lessons:\n  - {id: a, title: A, reference: 'https://x'}\n  - {id: a, title: B, reference: 'https://y'}\n",
        encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate"):
        lessons.load_series("dup", tmp_path)


class _Store:
    def __init__(self, seen):
        self.seen = set(seen)

    def filter_unseen(self, ids):
        return {i for i in ids if i not in self.seen}


def test_pending_gives_the_next_unposted_lesson_in_order():
    series = lessons.load_series("how-ai-works")
    first, second = series.lessons[0], series.lessons[1]
    nxt = lessons.pending(series, _Store([first.content_id]), "lessons")
    assert [a.content_id for a in nxt] == [second.content_id]
    assert nxt[0].url == second.reference and nxt[0].description == second.hook and nxt[0].genre == "lessons"
    assert series.by_content_id(nxt[0].content_id) is second
    done = _Store([x.content_id for x in series.lessons])
    assert lessons.pending(series, done, "lessons") == []


WIKI = (
    "Intro paragraph about models.\n\n\n== History ==\nOld times.\n\n\n== Dataset preprocessing ==\n\n\n"
    "=== Tokenization ===\nText is split into tokens.\n\n\n== See also ==\nOther pages.\n\n\n== References ==\nRefs."
)


def test_focus_text_moves_the_section_up_and_drops_reference_lists():
    out = lessons.focus_text(WIKI, "tokenization")
    assert out.startswith("Intro paragraph") and out.index("Tokenization") < out.index("History")
    assert "Other pages" not in out and "Refs." not in out
    assert lessons.focus_text(WIKI).index("History") < lessons.focus_text(WIKI).index("Tokenization")


def test_a_wikipedia_reference_is_read_through_the_api(monkeypatch):
    calls = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"query": {"pages": [{"title": "Large language model", "extract": WIKI}]}}

    def get(url, params, headers, timeout):
        calls.update(url=url, params=params, headers=headers)
        return Resp()

    monkeypatch.setattr(lessons.httpx, "get", get)
    lesson = lessons.load_series("how-ai-works").lessons[0]
    src = lessons.reference_source(lesson)
    assert calls["url"] == "https://en.wikipedia.org/w/api.php" and calls["params"]["titles"] == "Large language model"
    assert "narovva" in calls["headers"]["User-Agent"]
    assert src["source_name"] == "Wikipedia" and src["text"].index("Tokenization") < src["text"].index("History")
    assert "CC BY-SA" in lessons.caption_reference(lesson) and "Large language model" in lessons.caption_reference(lesson)


def test_any_other_reference_is_left_to_the_article_fetcher():
    other = lessons.Lesson(id="x", title="X", hook="", reference="https://example.org/explainer", series="S", series_key="s")
    assert lessons.reference_source(other) == "https://example.org/explainer"


def test_a_genre_can_teach_a_series():
    assert GenreSetting(genre="lessons", series="how-ai-works").series == "how-ai-works"
    assert GenreSetting(genre="ai").series is None
