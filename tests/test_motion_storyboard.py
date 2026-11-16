from __future__ import annotations

import copy
import io
import math
import struct
import sys
import wave

import pytest

import narovva.orchestration.run_channel  # noqa: F401
from narovva.config.schema import BrandKitConfig, ChannelConfig, GenreSetting, MotionStyleConfig, NarrationConfig
from narovva.motion.sample import SAMPLE_STORYBOARD, sample_brief_and_article
from narovva.motion.storyboard import BEAT_MIN, beat_specs, parse_storyboard, total_seconds, write_storyboard
from narovva.motion.style import stamp_colors

rc = sys.modules["narovva.orchestration.run_channel"]
BRIEF, ARTICLE = sample_brief_and_article()
COLORS = stamp_colors(MotionStyleConfig())


def _board(raw=None, max_beats=14, max_stamps=3):
    return parse_storyboard(copy.deepcopy(raw or SAMPLE_STORYBOARD), BRIEF, ARTICLE, brand="Context Unfiltered",
                            max_beats=max_beats, max_stamps=max_stamps)


def _beat(scene, data, lines=("A line that is spoken.",), **kw):
    return {"scene": scene, "lines": list(lines), "screen": list(lines), "data": data, **kw}


def _raw(*middle):
    """A minimal valid reply: a hook, the given beats, enough filler, and the call to follow."""
    filler = [_beat("headline", {"text": f"Point {w} of the story"}) for w in ("one", "two", "three")]
    return {"subject": "AI pricing", "beats": [_beat("question", {"text": "WHY?"}), *middle, *filler,
                                               _beat("cta", {}, ["Follow us for more."])]}


def test_the_sample_storyboard_validates_in_full():
    board = _board()
    assert board.subject == "AI PRICING" and len(board.beats) == len(SAMPLE_STORYBOARD["beats"])
    assert [b["scene"] for b in board.beats][-1] == "cta"
    dates = next(b for b in board.beats if b["scene"] == "dates")
    assert dates["data"]["title"] == "How the price war got here" and len(dates["lines"]) == 3


def test_a_figure_the_source_does_not_state_drops_the_beat():
    board = _board(_raw(_beat("number", {"value": "91%", "label": "cheaper per token"})))
    assert "number" not in [b["scene"] for b in board.beats]
    board = _board(_raw(_beat("number", {"value": "67%", "label": "cheaper per token", "from": "$15"})))
    number = next(b for b in board.beats if b["scene"] == "number")
    assert number["data"]["from"] is None                     # $15 is in the source, but not in % like 67%


def test_no_field_can_slip_in_an_invented_figure():
    board = _board(_raw(_beat("question", {"text": "WHY 6 DAYS?"}, kicker="DAY 9"),
                        _beat("terminal", {"title": "scan 42", "lines": ["flagship: $5 per million", "speed: 3.2x faster"]},
                              kicker="THE 99")))
    assert [b["data"]["text"] for b in board.beats if b["scene"] == "question"] == ["WHY?"]   # only the hook's
    terminal = next(b for b in board.beats if b["scene"] == "terminal")
    assert terminal["data"]["title"] == "log" and terminal["kicker"] is None


def test_screen_text_with_an_invented_figure_falls_back_to_the_spoken_words():
    beat = _beat("headline", {"text": "Prices fall again"}, ["Prices fall by half again."])
    beat["screen"] = ["Prices fall 50% again."]
    board = _board(_raw(beat))
    assert next(b for b in board.beats if b["data"].get("text") == "Prices fall again")["screens"] == ["Prices fall by half again."]


def test_a_quote_must_be_word_for_word():
    real = _beat("quote", {"text": "Intelligence should be too cheap to meter.", "who": "Spokesperson", "mark": "too cheap"})
    fake = _beat("quote", {"text": "Intelligence will soon be completely free for everyone.", "who": "Spokesperson"})
    scenes = [b["scene"] for b in _board(_raw(real, fake)).beats]
    assert scenes.count("quote") == 1


def test_unknown_scenes_icons_and_oversized_labels_are_dropped():
    board = _board(_raw(
        _beat("hologram", {"text": "x"}),
        _beat("grid", {"items": [{"label": "Anthropic", "icon": "unicorn"}, {"label": "Google", "icon": "globe"},
                                 {"label": "a label far too long to fit on a tile"}]}),
    ))
    grid = next(b for b in board.beats if b["scene"] == "grid")
    assert "hologram" not in [b["scene"] for b in board.beats]
    assert [(i["label"], i["icon"]) for i in grid["data"]["items"]] == [("Anthropic", None), ("Google", "globe")]


def test_the_reel_always_ends_on_the_call_to_follow_and_too_little_is_rejected():
    raw = _raw()
    raw["beats"].pop()                                        # the model forgot the cta
    board = _board(raw)
    assert board.beats[-1]["scene"] == "cta" and "Context Unfiltered" in board.beats[-1]["lines"][0]
    assert _board({"beats": [_beat("headline", {"text": "Only one beat"})]}) is None
    assert _board({"beats": "not a list"}) is None
    assert parse_storyboard(None, BRIEF, ARTICLE, brand="CU", max_beats=10, max_stamps=3) is None


def test_long_storyboards_are_cut_but_keep_their_ending():
    board = _board(max_beats=6)
    assert len(board.beats) == 6 and board.beats[-1]["scene"] == "cta"


def test_stamps_are_capped_never_on_the_ends_and_a_grid_counts_once():
    raw = _raw(_beat("cards", {"items": [{"text": "Prices fall 67% per token", "stamp": {"text": "CONFIRMED", "tone": "neutral"}}]}),
               _beat("grid", {"items": [{"label": "Google", "stamp": "PRESSURE"}, {"label": "Meta", "stamp": "PRESSURE"}]}),
               _beat("headline", {"text": "A third verdict"}, stamp={"text": "LATE", "tone": "negative"}))
    raw["beats"][0]["stamp"] = {"text": "HOOKED", "tone": "negative"}
    board = _board(raw, max_stamps=2)
    assert board.beats[0]["stamp"] is None
    grid = next(b for b in board.beats if b["scene"] == "grid")
    assert [i["stamp"]["text"] for i in grid["data"]["items"]] == ["PRESSURE", "PRESSURE"]
    assert next(b for b in board.beats if b["data"].get("text") == "A third verdict")["stamp"] is None


def test_beat_specs_time_each_line_and_map_scenes_to_the_template():
    specs = beat_specs(_board(), stamp_colors=COLORS)
    kinds = [s["kind"] for s in specs]
    assert {"excerpt", "comparison", "endcard", "stats"} - set(kinds) == {"stats"} and "quote" not in kinds
    dates = specs[kinds.index("dates")]
    ats = [p["at"] for p in dates["parts"]]
    assert ats[0] == pytest.approx(0.15) and ats == sorted(ats) and len(ats) == 3
    assert dates["duration"] >= dates["parts"][-1]["at"] + dates["parts"][-1]["voice"]
    assert dates["stamp"] == {"text": "PRICE WAR", "color": COLORS["neutral"]}
    comparison = specs[kinds.index("comparison")]
    assert comparison["viz"]["delta"] == "−67%" and comparison["comparison"]["value_b"] == "$5"
    assert all(s["duration"] >= BEAT_MIN for s in specs) and 40 < total_seconds(specs) < 75


def test_write_storyboard_asks_for_the_arc_and_survives_failure():
    class LLM:
        def __init__(self, reply=None, boom=False):
            self.reply, self.boom, self.seen = reply, boom, None

        def complete_json(self, system, user):
            self.seen = (system, user)
            if self.boom:
                raise RuntimeError("503")
            return self.reply

    llm = LLM(copy.deepcopy(SAMPLE_STORYBOARD))
    board = write_storyboard(llm, BRIEF, ARTICLE, brand="Context Unfiltered", max_beats=14, when="24 Oct 2026")
    assert board is not None and "Hook" in llm.seen[0] and "Verdict" in llm.seen[0] and "satellite-dish" in llm.seen[0]
    assert "too cheap to meter" in llm.seen[1] and "24 Oct 2026" in llm.seen[1]
    assert write_storyboard(LLM(boom=True), BRIEF, ARTICLE, brand="CU") is None
    assert write_storyboard(LLM({"lines": ["x"]}), BRIEF, ARTICLE, brand="CU") is None


def test_a_viral_hook_opens_the_storyboard():
    from narovva.motion.storyboard import hook_board

    board = hook_board(_board(), "Why AI just got cheap", "Why A I just got cheap", "OpenAI cuts model prices by two-thirds")
    first = board.beats[0]
    assert first["lines"][0] == "Why A I just got cheap" and first["screens"][0] == "Why AI just got cheap"
    assert first["kicker"] == "TRENDING NOW" and first["data"]["text"] == "Why AI just got cheap"
    assert first["data"]["sub"] == "OpenAI cuts model prices by two-thirds"
    assert hook_board(_board(), None, None, "h").beats[0]["kicker"] == "AI"          # no hook, no change

    class LLM:
        def complete_json(self, system, user):
            self.user = user
            return copy.deepcopy(SAMPLE_STORYBOARD)

    llm = LLM()
    write_storyboard(llm, BRIEF, ARTICLE, brand="CU", max_beats=14, hook="Why AI just got cheap", audience="AI engineers")
    assert "Audience: AI engineers" in llm.user and "word for word: Why AI just got cheap" in llm.user


# -- orchestration ---------------------------------------------------------

def _wav(seconds: float, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(0.4 * 32767 * math.sin(2 * math.pi * 330 * i / rate)))
                               for i in range(int(seconds * rate))))
    return buf.getvalue()


class _Director:
    """Answers the storyboard prompt with the sample, anything else with a plain script."""

    def __init__(self):
        self.prompts = []

    def complete_json(self, system, user):
        self.prompts.append(system)
        if "storyboard" in system:
            return copy.deepcopy(SAMPLE_STORYBOARD)
        return {"lines": ["One.", "Two."]}


class _Track:
    id, audio_bytes, attribution = "t", _wav(3.0), "c"


def _channel(**kw):
    base = dict(id="c", ig_business_account_id="1", genres=[GenreSetting(genre="ai")],
                brand=BrandKitConfig(name="CONTEXT UNFILTERED", social_handle="cu", logo_path="assets/logo/CU.png"),
                publish_format="motion_reel", narration=None,
                motion=MotionStyleConfig.model_validate({"story": {"max_beats": 14}}))
    base.update(kw)
    return ChannelConfig(**base)


def _capture(monkeypatch):
    seen = {}
    monkeypatch.setattr(rc, "render_motion_reel", lambda specs, audio, out, **kw: (seen.update(kw, specs=specs, audio=audio), out)[1])
    return seen


def test_the_storyboard_drives_the_reel(monkeypatch):
    seen = _capture(monkeypatch)
    llm = _Director()
    path, voice = rc._try_motion_reel(_channel(), [], BRIEF, _Track(), "/tmp/o.mp4", llm=llm, article=ARTICLE)
    assert path == "/tmp/o.mp4" and voice is None and len(llm.prompts) == 1    # one call, no extra script call
    assert "Context Unfiltered" in llm.prompts[0]                              # the brand as a name, not shouted
    kinds = [s["kind"] for s in seen["specs"]]
    assert kinds[0] == "headline" and kinds[-1] == "endcard" and "dates" in kinds
    assert seen["ui"]["hud"]["label"] == "CASE FILE: AI PRICING"
    assert all(p.get("caption") for s in seen["specs"] for p in s["parts"])  # silent explainer: captions still tell it


def test_narration_speaks_every_line_and_times_the_builds(monkeypatch):
    class Voice:
        def synthesize(self, text, *, voice, style):
            return _wav(1.0 + 0.02 * len(text))

    monkeypatch.setattr(rc, "build_provider", lambda *a, **k: Voice())
    monkeypatch.setattr(rc, "resolve_env", lambda name: "key")
    mixed = {}
    monkeypatch.setattr(rc, "mix_voice_and_music", lambda clips, starts, music, total: (mixed.update(clips=clips, starts=starts, total=total), b"mp3")[1])
    seen = _capture(monkeypatch)
    channel = _channel(narration=NarrationConfig(provider="openai", voices=["v1"]))
    path, voice = rc._try_motion_reel(channel, [], BRIEF, _Track(), "/tmp/o.mp4", llm=_Director(), article=ARTICLE, seed="s")
    assert voice == "v1" and seen["audio"] == b"mp3"
    # one clip per scene (its lines read as one passage), each line timed by its share of it
    assert len(mixed["clips"]) == len(mixed["starts"]) == len(seen["specs"]) and mixed["starts"] == sorted(mixed["starts"])
    dates = next(s for s in seen["specs"] if s["kind"] == "dates")
    assert len(dates["parts"]) == 3
    gaps = [b["at"] - (a["at"] + a["voice"]) for a, b in zip(dates["parts"], dates["parts"][1:])]
    assert all(g == pytest.approx(0.0, abs=0.01) for g in gaps)             # each line follows straight on
    clip = mixed["clips"][[s["kind"] for s in seen["specs"]].index("dates")]
    assert sum(p["voice"] for p in dates["parts"]) == pytest.approx(clip.seconds, abs=0.01)


def test_a_storyboard_that_fails_validation_falls_back_to_the_slides(monkeypatch):
    class Lazy:
        def complete_json(self, system, user):
            return {"lines": ["Hook?", "Point."]}

    seen = _capture(monkeypatch)
    from tests.test_motion_style import _asset
    path, voice = rc._try_motion_reel(_channel(), [_asset()], BRIEF, _Track(), "/tmp/o.mp4", llm=Lazy(), article=ARTICLE)
    assert path == "/tmp/o.mp4" and [s["kind"] for s in seen["specs"]] == ["hook", "text", "text"]


# -- explainer v3: the viewer's questions, receipts and the recap ---------------

def test_a_viewer_question_is_one_line_answered_later_and_never_at_the_ends():
    ask = lambda q: _beat("ask", {}, [q])
    raw = _raw(ask("Wait, so who pays for this?"))          # second beat: too early
    assert all(b["scene"] != "ask" for b in _board(raw).beats)
    raw = _raw()
    raw["beats"][3:3] = [ask("Wait, so who pays for this?"), ask("And then what happens next?")]
    board = _board(raw)
    asks = [i for i, b in enumerate(board.beats) if b["scene"] == "ask"]
    assert asks == [3]                                      # never two in a row
    beat = board.beats[3]
    assert beat["voice"] == "viewer" and beat["data"]["text"] == "Wait, so who pays for this?" and len(beat["lines"]) == 1
    del raw["beats"][4]
    raw["beats"][3] = ask("Wait, is that really 90% cheaper?")  # an invented figure
    assert all(b["scene"] != "ask" for b in _board(raw).beats)
    raw["beats"][3] = ask("Not a question at all.")
    assert all(b["scene"] != "ask" for b in _board(raw).beats)


def test_viewer_questions_can_be_switched_off():
    raw = _raw()
    raw["beats"][3:3] = [_beat("ask", {}, ["Wait, so who pays for this?"])]
    board = parse_storyboard(copy.deepcopy(raw), BRIEF, ARTICLE, brand="CU", max_beats=14, max_stamps=3, max_asks=0)
    assert all(b["scene"] != "ask" for b in board.beats)


def test_a_source_card_shows_only_the_articles_own_words():
    good = "OpenAI cut prices across its model lineup on Thursday, with the flagship now costing $5 per million tokens"
    board = _board(_raw(_beat("source", {"text": good, "mark": "costing $5"})))
    src = next(b for b in board.beats if b["scene"] == "source")
    assert src["data"]["text"] == good and src["data"]["mark"] == "costing $5" and src["data"]["publisher"] == "Sample Wire"
    for bad in ("OpenAI cut prices across its whole model lineup on Thursday, with the flagship now cheaper",  # reworded
                "Intelligence should be too cheap to meter."):                                              # too short
        assert all(b["scene"] != "source" for b in _board(_raw(_beat("source", {"text": bad}))).beats)


def test_a_recap_needs_two_grounded_rows():
    rows = [{"label": "Developers", "note": "pay $5, not $15"}, {"label": "Rivals", "note": "match the price"},
            {"label": "Ghost row", "note": "saves 99%"}]
    recap = next(b for b in _board(_raw(_beat("recap", {"title": "Who gets what", "rows": rows}))).beats if b["scene"] == "recap")
    assert [r["label"] for r in recap["data"]["rows"]] == ["Developers", "Rivals"] and recap["data"]["title"] == "Who gets what"
    assert all(b["scene"] != "recap" for b in _board(_raw(_beat("recap", {"rows": rows[:1]}))).beats)


def test_the_viewer_beat_is_marked_for_the_template():
    specs = beat_specs(_board(), stamp_colors=COLORS)
    ask = next(s for s in specs if s["kind"] == "ask")
    assert ask["speaker"] == "viewer" and all("speaker" not in s for s in specs if s["kind"] != "ask")
    assert {"source", "recap"} <= {s["kind"] for s in specs}


def test_the_viewer_question_is_read_in_a_second_voice(monkeypatch):
    heard = []

    class Voice:
        def synthesize(self, text, *, voice, style):
            heard.append((voice, style[0], text))
            return _wav(1.0)

    monkeypatch.setattr(rc, "build_provider", lambda *a, **k: Voice())
    monkeypatch.setattr(rc, "resolve_env", lambda name: "key")
    monkeypatch.setattr(rc, "mix_voice_and_music", lambda clips, starts, music, total: b"mp3")
    _capture(monkeypatch)
    channel = _channel(narration=NarrationConfig(provider="openai", voices=["v1", "v2"]))
    path, voice = rc._try_motion_reel(channel, [], BRIEF, _Track(), "/tmp/o.mp4", llm=_Director(), article=ARTICLE, seed="s")
    question = [h for h in heard if h[2].startswith("Wait")]
    assert len(question) == 1 and question[0][0] != voice and "sceptical" in question[0][1]
    assert all(v == voice for v, _, t in heard if not t.startswith("Wait"))


# -- the story world (3D set pieces) -----------------------------------------------

def _world_beat(**data):
    return _beat("world", data, ["It plays out like this.", "Then it turns."])


def _world(**data):
    board = _board(_raw(_world_beat(**data)))
    return next((b["data"] for b in board.beats if b["scene"] == "world"), None)


def test_the_world_gallery_validates_every_set_piece():
    from narovva.motion.sample import SAMPLE_WORLDS, world_gallery
    specs, _ = world_gallery()
    assert {s["data"]["piece"] for s in specs if s["kind"] == "world"} == {
        b["data"]["piece"] for b in SAMPLE_WORLDS["beats"] if b["scene"] == "world"} == {
        "gate", "flow", "pile", "race", "split", "machine", "wall", "balance"}


def test_a_set_piece_needs_its_labels_and_takes_no_invented_figures():
    assert _world(piece="gate", gate="Flagship AI", crowd="Developers")["count"] == 3
    assert _world(piece="gate", gate="Flagship AI") is None                       # no crowd
    assert _world(piece="teleport", gate="x", crowd="y") is None                  # unknown piece
    assert _world(piece="flow", **{"from": "Your app", "to": "The lab"}, amount="$9B") is None   # $9B is not in the source
    flow = _world(piece="flow", **{"from": "Your app", "to": "The lab"}, amount="$1.2B", item="lasers", change="explodes")
    assert flow["item"] == "money" and flow["change"] == "none" and flow["amount"] == "$1.2B"


def test_a_pile_works_out_its_direction_from_the_figures():
    pile = _world(piece="pile", label="Per million tokens", start="$15", end="$5", trend="up")
    assert pile["trend"] == "down" and pile["ratio"] == pytest.approx(1 / 3, abs=0.01)
    assert _world(piece="pile", label="Users", trend="up")["trend"] == "up"


def test_race_split_and_balance_are_cleaned():
    race = _world(piece="race", lanes=["OpenAI", "Anthropic", "Google", "Meta"], leader=7)
    assert race["lanes"] == ["OpenAI", "Anthropic", "Google"] and race["leader"] == 0
    assert _world(piece="race", lanes=["OpenAI"]) is None
    assert _world(piece="split", win="Developers", lose="Smaller labs", share=0.95)["share"] == 0.5
    assert _world(piece="balance", left="Price", right="Product", heavier="up")["heavier"] == "left"
