from __future__ import annotations

import copy

from narovva.config.schema import MotionStyleConfig
from narovva.llm import FallbackLLM
from narovva.llm.fallback import _Entry
from narovva.motion.local_director import local_direction
from narovva.motion.sample import SAMPLE_DIRECTION, SAMPLE_STORY_FIRST, sample_brief_and_article, sample_story_first
from narovva.motion.story_first import (
    HARD_SECONDS,
    FullSource,
    direct_story,
    parse_story,
    story_gaps,
    story_seconds,
    write_story_first,
)

BRIEF, ARTICLE = sample_brief_and_article()
SRC = FullSource(BRIEF, ARTICLE)


def _beats(raw=None):
    beats, gaps = parse_story(copy.deepcopy(raw or SAMPLE_STORY_FIRST), SRC, brand="Context Unfiltered")
    return beats, gaps


class _LLM:
    """Writer answers come from a queue; the director gets the sample direction (or `direction`)."""

    def __init__(self, stories, direction=None, director_fails=False):
        self.stories, self.direction, self.director_fails = list(stories), direction, director_fails
        self.writer_prompts, self.director_calls = [], 0

    def complete_json(self, system, user):
        if system.startswith("You are the animation director"):
            self.director_calls += 1
            if self.director_fails:
                raise RuntimeError("director down")
            return copy.deepcopy(self.direction if self.direction is not None else SAMPLE_DIRECTION)
        self.writer_prompts.append(user)
        return copy.deepcopy(self.stories.pop(0) if len(self.stories) > 1 else self.stories[0])


def _write(llm, **kw):
    return write_story_first(llm, BRIEF, ARTICLE, brand="Context Unfiltered", **kw)


# -- the writer ------------------------------------------------------------------------------------------------------

def test_sample_story_is_complete():
    beats, gaps = _beats()
    assert gaps == []
    assert [b["part"] for b in beats][0] == "hook" and beats[-1]["part"] == "cta"
    assert len(beats) == 9


def test_missing_coverage_is_a_gap():
    raw = copy.deepcopy(SAMPLE_STORY_FIRST)
    del raw["coverage"]["next"], raw["coverage"]["why"]
    beats, gaps = _beats(raw)
    assert {"next", "why"} <= set(gaps)


def test_coverage_pointing_past_the_story_is_a_gap():
    raw = copy.deepcopy(SAMPLE_STORY_FIRST)
    raw["coverage"]["impact"] = 40
    beats, _ = _beats(raw)
    assert "impact" in story_gaps(raw, beats)


def test_story_without_cta_gets_one():
    raw = copy.deepcopy(SAMPLE_STORY_FIRST)
    raw["beats"] = raw["beats"][:-1]
    beats, _ = _beats(raw)
    assert beats[-1]["part"] == "cta"


def test_invented_fact_is_not_kept():
    raw = copy.deepcopy(SAMPLE_STORY_FIRST)
    raw["beats"][1]["facts"].append("$99 per million tokens next year")
    beats, _ = _beats(raw)
    assert not any("$99" in f for b in beats for f in b["facts"])


# -- length follows the story ----------------------------------------------------------------------------------------

def test_short_target_does_not_cut_the_story():
    board = _write(_LLM([SAMPLE_STORY_FIRST]), target_seconds=20)
    assert board is not None
    assert len(board.beats) == 9                     # nothing dropped to meet 20 s
    assert story_seconds(_beats()[0]) < HARD_SECONDS


def test_incomplete_story_is_retried_with_the_gaps():
    thin = copy.deepcopy(SAMPLE_STORY_FIRST)
    del thin["coverage"]["next"]
    llm = _LLM([thin, SAMPLE_STORY_FIRST])
    board = _write(llm)
    assert len(llm.writer_prompts) == 2
    assert "LEFT OUT: next" in llm.writer_prompts[1]
    assert board.coverage_gaps == []


def test_unusable_story_returns_none():
    llm = _LLM([{"beats": []}])
    assert _write(llm) is None
    assert llm.director_calls == 0


# -- the director ----------------------------------------------------------------------------------------------------

def test_sample_direction_validates_with_varied_scenes():
    beats, _ = _beats()
    out, stats = direct_story(copy.deepcopy(SAMPLE_DIRECTION), beats, SRC)
    assert stats["fallbacks"] == 0
    assert stats["scenes"] == ["compose:row", "compare", "compose:flow", "dates", "compose:versus", "quote",
                               "compose:hub", "number", "cta"]
    assert all(a != b for a, b in zip(stats["scenes"], stats["scenes"][1:]))


def test_actor_not_in_the_story_is_dropped():
    beats, _ = _beats()
    d = copy.deepcopy(SAMPLE_DIRECTION)
    d["beats"][6]["data"]["actors"].append({"id": "x", "label": "Microsoft", "icon": "building-2"})
    out, _ = direct_story(d, beats, SRC)
    labels = [a["label"] for a in out[6]["data"]["actors"]]
    assert "Microsoft" not in labels and "Anthropic" in labels


def test_picture_of_invented_players_falls_back_to_the_words():
    beats, _ = _beats()
    d = copy.deepcopy(SAMPLE_DIRECTION)
    d["beats"][0]["data"]["actors"] = [{"id": "q", "label": "Quantum Pandas", "icon": "zap"}]
    out, stats = direct_story(d, beats, SRC)
    assert out[0]["scene"] == "headline" and stats["fallbacks"] == 1
    assert out[0]["lines"] == beats[0]["lines"]      # the story is untouched


def test_steps_follow_the_actor_ids():
    beats, _ = _beats()
    out, _ = direct_story(copy.deepcopy(SAMPLE_DIRECTION), beats, SRC)
    flow = out[2]["data"]
    assert flow["steps"][0] == {"do": "connect", "who": 0, "to": 1, "label": "update", "value": None, "line": 0}
    assert any(s["do"] == "count" and s["value"] == "3.2x" for s in flow["steps"])


def test_bad_step_is_skipped_and_silent_scene_still_moves():
    beats, _ = _beats()
    d = copy.deepcopy(SAMPLE_DIRECTION)
    d["beats"][4]["data"]["steps"] = [{"line": 0, "do": "explode", "who": "d"},
                                      {"line": 0, "do": "connect", "who": "d", "to": "nobody"}]
    out, _ = direct_story(d, beats, SRC)
    steps = out[4]["data"]["steps"]
    assert [s["do"] for s in steps] == ["appear", "appear"]


def test_same_scene_twice_in_a_row_falls_back():
    beats, _ = _beats()
    d = copy.deepcopy(SAMPLE_DIRECTION)
    d["beats"][2] = {"i": 2, "scene": "compare", "data": {"a": {"label": "Before", "value": "$15"},
                                                         "b": {"label": "After", "value": "$5"}}}
    out, stats = direct_story(d, beats, SRC)
    assert out[1]["scene"] == "comparison" or out[1]["scene"] == "compare"
    assert out[2]["scene"] == "headline" and stats["fallbacks"] == 1


def test_director_failure_is_pictured_locally():
    board = _write(_LLM([SAMPLE_STORY_FIRST], director_fails=True))
    assert board is not None and len(board.beats) == 9
    scenes = [b["scene"] for b in board.beats]
    assert scenes.count("headline") <= 2                       # not the all-text look of a failed director
    assert {"number", "compare", "dates", "quote", "compose"} <= set(scenes)
    assert all(a != b or a == "compose" for a, b in zip(scenes, scenes[1:]))


def test_unusable_direction_is_rescued_beat_by_beat():
    junk = {"beats": [{"i": i, "scene": "compose", "data": {"actors": [{"label": "Quantum Pandas"}]}}
                      for i in range(8)]}
    board = _write(_LLM([SAMPLE_STORY_FIRST], direction=junk))
    assert [b["scene"] for b in board.beats].count("headline") <= 2


# -- the local director ----------------------------------------------------------------------------------------------

def _story(*beats):
    return [{"part": p, "lines": list(lines), "screens": list(lines), "cmarks": [None] * len(lines),
             "facts": list(facts), "show": "", "kicker": None} for p, lines, facts in beats]


def test_local_director_reads_the_writers_facts():
    beats = _story(("hook", ["OpenAI just cut its prices by two thirds."], ["Prices fall 67% per token"]),
                   ("context", ["The price war began in March 2024."],
                    ["Mar 2024: a rival lab halves its prices", "Jan 2025: open models match the flagship"]),
                   ("event", ["A million tokens went from $15 to $5."], []),
                   ("next", ["Anthropic, Google and Mistral now face pressure."], []))
    d = {e["i"]: e for e in local_direction(beats, SRC, BRIEF)["beats"]}
    assert d[0]["scene"] == "number" and d[0]["data"]["value"] == "67%"
    assert d[1]["scene"] == "dates" and [e["when"] for e in d[1]["data"]["events"]] == ["Mar 2024", "Jan 2025"]
    assert d[2]["scene"] == "compare" and (d[2]["data"]["a"]["value"], d[2]["data"]["b"]["value"]) == ("$15", "$5")
    assert d[3]["scene"] == "compose"
    assert [a["label"] for a in d[3]["data"]["actors"]] == ["Anthropic", "Google", "Mistral"]


def test_local_director_never_invents_players_or_figures():
    beats = _story(("event", ["Globex and Initech signed a $40B deal."], []),
                   ("impact", ["Prices could fall 99% next year."], []))
    out, stats = direct_story({}, beats, SRC, backup=local_direction(beats, SRC, BRIEF))
    assert [b["scene"] for b in out] == ["headline", "headline"]    # neither name nor figure is in the article
    assert stats["fallbacks"] == 2


def test_local_director_varies_back_to_back_beats():
    beats = _story(("hook", ["Customers save $1.2B this year."], []),
                   ("impact", ["Prices fall 67% per token."], []))
    scenes = [e["scene"] for e in local_direction(beats, SRC, BRIEF)["beats"]]
    assert scenes[:1] == ["number"] and scenes[1:] != ["number"]


# -- quota: a weak model's reply is passed over ----------------------------------------------------------------------

class _Model:
    def __init__(self, reply):
        self.reply, self.calls = reply, 0

    def complete_json(self, system, user):
        self.calls += 1
        if isinstance(self.reply, Exception):
            raise self.reply
        return copy.deepcopy(self.reply(system) if callable(self.reply) else self.reply)


def _chain(*models):
    return FallbackLLM([_Entry(f"m{i}", m) for i, m in enumerate(models)], sleep=lambda s: None)


def test_weak_writer_reply_goes_to_the_next_model():
    spent = _Model(RuntimeError("429 RESOURCE_EXHAUSTED quota"))
    weak = _Model({"beats": [{"part": "hook", "lines": ["Something happened."]}]})
    good = _Model(lambda system: SAMPLE_DIRECTION if system.startswith("You are the animation") else SAMPLE_STORY_FIRST)
    board = _write(_chain(spent, weak, good))
    assert board is not None and len(board.beats) == 9
    assert weak.calls == 1                       # asked once for the story; once rejected it is not asked again...
    assert board.signature[0] == "compose:row"   # ...and the good model directs too


def test_chain_returns_the_set_aside_reply_when_every_model_is_weak():
    a, b = _Model({"n": 1}), _Model({"n": 2})
    assert _chain(a, b).complete_json("s", "u", accept=lambda r: "weak") == {"n": 1}


def test_chain_stops_asking_after_two_rejections():
    models = [_Model({"n": k}) for k in range(4)]
    _chain(*models).complete_json("s", "u", accept=lambda r: "weak")
    assert [m.calls for m in models] == [1, 1, 0, 0]


# -- end to end ------------------------------------------------------------------------------------------------------

def test_board_signature_and_specs():
    board = _write(_LLM([SAMPLE_STORY_FIRST]))
    assert board.signature[0] == "compose:row" and board.signature[-1] == "cta"
    specs, subject = sample_story_first(captions=False, look=MotionStyleConfig())
    assert subject == "AI pricing" and len(specs) == 9
    assert all("caption" not in p for s in specs for p in s["parts"])
