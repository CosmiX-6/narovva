"""The animated story (motion.story.mode "animated"), the teaching set pieces and lessons."""

from __future__ import annotations

import copy
import sys

import pytest

import narovva.orchestration.run_channel  # noqa: F401
from narovva.config.schema import BrandKitConfig, ChannelConfig, GenreSetting, MotionStyleConfig
from narovva.motion.sample import (
    SAMPLE_ANIMATED,
    SAMPLE_LESSON,
    SAMPLE_STORYBOARD,
    sample_brief_and_article,
    sample_lesson,
    sample_lesson_inputs,
)
from narovva.motion.storyboard import hook_board, parse_storyboard, write_storyboard

rc = sys.modules["narovva.orchestration.run_channel"]  # the package re-exports the function under this name
BRIEF, ARTICLE = sample_brief_and_article()


def _animated(raw):
    return parse_storyboard(copy.deepcopy(raw), BRIEF, ARTICLE, brand="Context Unfiltered", max_beats=14,
                            max_stamps=0, animated=True)


def _world(**data):
    """One world beat checked inside an otherwise valid animated reply."""
    raw = copy.deepcopy(SAMPLE_ANIMATED)
    raw["beats"].insert(1, {"scene": "world", "lines": ["It plays out like this.", "Then it turns."],
                            "screen": ["It plays out like this.", "Then it turns."], "data": data})
    board = _animated(raw)
    return board.beats[1]["data"] if board and board.beats[1]["lines"][0] == "It plays out like this." else None


# -- the animated story ---------------------------------------------------------

def test_the_animated_sample_is_all_world_but_a_few_allowed_scenes():
    board = _animated(SAMPLE_ANIMATED)
    scenes = [b["scene"] for b in board.beats]
    assert scenes[0] == "world" and scenes[-1] == "cta" and scenes.count("world") == 6
    assert set(scenes) <= {"world", "ask", "source", "recap", "cta"}


def test_an_animated_reply_drops_motion_graphic_scenes_and_needs_three_world_beats():
    # the classic storyboard has a single world beat: as an animation it does not validate
    assert _animated(SAMPLE_STORYBOARD) is None
    raw = copy.deepcopy(SAMPLE_ANIMATED)
    raw["beats"].insert(2, {"scene": "number", "lines": ["Sixty-seven percent cheaper."], "data": {"value": "67%", "label": "cheaper"}})
    assert "number" not in [b["scene"] for b in _animated(raw).beats]


def test_the_hook_becomes_the_opening_world_title():
    board = hook_board(_animated(SAMPLE_ANIMATED), "Why AI just got cheap", "Why A I just got cheap", "x", trending=False)
    first = board.beats[0]
    assert first["data"]["title"] == "Why AI just got cheap" and first["lines"][0] == "Why A I just got cheap"


def test_the_animated_mode_asks_for_one_world_and_no_stamps():
    class LLM:
        def complete_json(self, system, user):
            self.system = system
            return copy.deepcopy(SAMPLE_ANIMATED)

    llm = LLM()
    board = write_storyboard(llm, BRIEF, ARTICLE, brand="Context Unfiltered", max_beats=14, mode="animated")
    assert "ONE continuous animation" in llm.system and '"piece": "focus"' in llm.system
    assert board is not None and not any(b.get("stamp") for b in board.beats)


class _Animator:
    def __init__(self, reply):
        self.reply, self.prompts = reply, []

    def complete_json(self, system, user):
        self.prompts.append((system, user))
        return copy.deepcopy(self.reply)


class _Track:
    id, audio_bytes, attribution = "t", b"", "c"


def _channel():
    return ChannelConfig(id="c", ig_business_account_id="1", genres=[GenreSetting(genre="ai")],
                         brand=BrandKitConfig(name="CONTEXT UNFILTERED", social_handle="cu", logo_path="assets/logo/CU.png"),
                         publish_format="motion_reel", narration=None,
                         motion=MotionStyleConfig.model_validate({"story": {"max_beats": 14}}))


def test_animated_is_the_default_and_drives_the_reel(monkeypatch):
    seen = {}
    monkeypatch.setattr(rc, "render_motion_reel", lambda specs, audio, out, **kw: (seen.update(specs=specs), out)[1])
    assert MotionStyleConfig().story.mode == "animated"
    llm = _Animator(SAMPLE_ANIMATED)
    path, _ = rc._try_motion_reel(_channel(), [], BRIEF, _Track(), "/tmp/o.mp4", llm=llm, article=ARTICLE)
    assert path == "/tmp/o.mp4" and len(llm.prompts) == 1
    kinds = [s["kind"] for s in seen["specs"]]
    assert kinds[0] == "world" and kinds[-1] == "endcard" and kinds.count("world") == 6


def test_a_lesson_is_written_from_its_reference_with_its_own_hook(monkeypatch):
    brief, article, lesson = sample_lesson_inputs()
    seen = {}
    monkeypatch.setattr(rc, "render_motion_reel", lambda specs, audio, out, **kw: (seen.update(specs=specs), out)[1])
    channel = _channel()
    channel.motion.story.mode = "slides"  # a lesson is animated whatever the news posts use
    llm = _Animator(SAMPLE_LESSON)
    path, _ = rc._try_motion_reel(channel, [], brief, _Track(), "/tmp/o.mp4", llm=llm, article=article,
                                  hook=lesson.hook, lesson=lesson)
    system, user = llm.prompts[0]
    assert path and "teaches how AI works" in system and "LESSON ARC" in system
    assert f"word for word: {lesson.hook}" in user and "Reference text:" in user and "vocabulary" in user
    first = seen["specs"][0]
    assert first["kind"] == "world" and first["data"]["title"] == lesson.hook


def test_a_lesson_closes_on_save_and_follow_when_the_model_forgets():
    brief, article, lesson = sample_lesson_inputs()
    raw = copy.deepcopy(SAMPLE_LESSON)
    raw["beats"].pop()
    llm = _Animator(raw)
    board = write_storyboard(llm, brief, article, brand="Context Unfiltered", max_beats=14, lesson=lesson)
    assert board.beats[-1]["scene"] == "cta" and board.beats[-1]["lines"][0].startswith("Save this")


def test_the_lesson_sample_prepares():
    specs, subject = sample_lesson()
    assert subject == "TOKENS" and [s["kind"] for s in specs].count("world") == 5


# -- the teaching set pieces ------------------------------------------------------

def test_steps_sort_and_cluster_need_their_lists():
    steps = _world(piece="steps", steps=["Router", "Model", "Safety check", "Log", "Extra"], item="lasers")
    assert steps["steps"] == ["Router", "Model", "Safety check", "Log"] and steps["item"] == "data"
    assert _world(piece="steps", steps=["Only one"]) is None
    assert _world(piece="sort", sorter="Router", bins=["Code", "Maths"])["item"] == "documents"
    assert _world(piece="sort", sorter="Router", bins="Code") is None
    assert _world(piece="cluster", groups=["Pricing", "Chips"], query="Your question")["query"] == "Your question"


def test_focus_keeps_short_words_and_valid_indexes():
    focus = _world(piece="focus", words=["the", "cat", "sat", "because", "it"], focus=4, strongest=4)
    assert focus["focus"] == 4 and focus["strongest"] == 0          # never itself
    focus = _world(piece="focus", words=["how", "many", "r"], focus=9, strongest=True)
    assert focus["focus"] == 2 and focus["strongest"] == 0          # out of range, or not an index
    assert _world(piece="focus", words=["a", "b"]) is None          # too few
    assert _world(piece="focus", words=["a", "b", "an extremely long phrase"]) is None


def test_slice_window_hill_fetch_and_target():
    assert _world(piece="slice", whole="strawberry", parts=["str", "aw", "berry"])["parts"] == ["str", "aw", "berry"]
    assert _world(piece="slice", parts=["one"]) is None
    window = _world(piece="window", window="Context window", size=40, item="tokens")
    assert window["size"] == 4 and window["item"] == "tokens"
    assert _world(piece="hill", start="Wrong") is None              # needs its goal
    assert _world(piece="fetch", shelf="Your files", answer="Found it")["asker"] is None
    assert _world(piece="target", thrower="The model") is None
    assert _world(piece="steps", steps=["Pay $9B", "Wait"]) is None  # $9B is not in the source


@pytest.mark.parametrize("piece", ["steps", "sort", "cluster", "hill", "fetch", "focus", "slice", "window", "target"])
def test_every_teaching_piece_is_in_the_prompt_and_the_engine(piece):
    from pathlib import Path

    from narovva.motion.storyboard import _PIECES, _WORLD_PIECES
    engine = (Path(__file__).parents[1] / "src/narovva/motion/templates/reel/world.js").read_text(encoding="utf-8")
    assert piece in _PIECES and f'"piece": "{piece}"' in _WORLD_PIECES and f"PIECES.{piece} = " in engine


def test_scene_fields_written_beside_the_lines_are_understood():
    raw = copy.deepcopy(SAMPLE_ANIMATED)
    flat = []
    for b in raw["beats"]:
        b = dict(b, **b.pop("data"))           # every field at the top level, as models often write it
        if b["scene"] == "ask":
            b.pop("lines"), b.pop("screen")    # and the question given only as its text
            b["text"] = "Wait, why would a leader cut its own price?"
        flat.append(b)
    raw["beats"] = flat
    board = _animated(raw)
    assert board is not None and [b["scene"] for b in board.beats] == [b["scene"] for b in _animated(SAMPLE_ANIMATED).beats]
    assert board.beats[0]["data"]["piece"] == "gate"


def test_harm_to_people_is_never_acted_out():
    for line in ("Two more children died this week.", "The death toll rose to five.", "Dozens were injured."):
        raw = copy.deepcopy(SAMPLE_ANIMATED)
        raw["beats"][1]["lines"] = [line, "Now it is five."]
        board = _animated(raw)
        assert board is None or all(line not in b["lines"] for b in board.beats)
    assert _world(piece="pile", item="people", label="Victims", start="$15", end="$5") is None
