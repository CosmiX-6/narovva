"""Character reels: the script is validated in code, the config parses, the A/B pick is stable, and the reel is only
tried when enabled for an English story in the share."""

from types import SimpleNamespace

import pytest

from narovva.characters import _sfx_events, chosen, load_kit
from narovva.characters.script import parse, write
from narovva.config.schema import CharactersConfig

CAST = {"KAI": {"id": "kai", "kind": "human", "role": "host"}, "CUE": {"id": "cue", "kind": "blob", "role": "mascot"}}
SOURCE = "Gemini 3 Flash is ten times cheaper and runs 3 times faster on 1 million tokens. Google announced it today."


def _reply(**over):
    lines = [
        {"speaker": "KAI", "text": "Google just made its fast model ten times cheaper.", "shot": "kai_close", "emotion": "wow"},
        {"speaker": "CUE", "text": "Wait, cheaper and faster? What's the catch?", "shot": "cue", "emotion": "curious"},
        {"speaker": "KAI", "text": "It runs three times faster on long inputs.", "shot": "two",
         "broll": {"piece": "compare", "data": {"title": "Speed", "left": {"label": "Old", "value": 1}, "right": {"label": "Flash", "value": 3}}}},
        {"speaker": "KAI", "text": "Think of it like a cheaper delivery truck.", "shot": "kai",
         "broll": {"piece": "counter", "data": {"label": "tokens", "from": 0, "to": 1}}},
        {"speaker": "CUE", "text": "So who pays for that?", "shot": "cue_close", "emotion": "confused"},
        {"speaker": "KAI", "text": "Developers building on one million tokens win.", "shot": "kai_close"},
        {"speaker": "CUE", "text": "Would you switch? Yes or no, tell us.", "shot": "two"},
        {"speaker": "KAI", "text": "Cheap thinking changes what gets built.", "shot": "kai"},
    ]
    raw = {"lines": lines, "hook_screen": "Ten times cheaper", "highlight": "cheaper", "question": "Switch?", "subject": "Gemini"}
    raw.update(over)
    return raw


def test_parse_keeps_valid_script_and_staging():
    cs = parse(_reply(), cast=CAST, source=SOURCE, banned=[])
    assert cs is not None
    assert cs.lines[0]["speaker"] == "kai" and cs.lines[0]["move"] == "pull"
    assert cs.hook_screen == "Ten times cheaper"
    assert cs.lines[2]["broll"]["piece"] == "compare"
    assert "broll" not in cs.lines[3]  # never two b-roll lines in a row
    # an on-camera line never repeats the previous shot (a b-roll line keeps the camera under its cutaway)
    assert all(a["shot"] != b["shot"] for a, b in zip(cs.lines, cs.lines[1:]) if not b.get("broll"))
    assert all(ln["gesture"] == "none" for ln in cs.lines if ln["speaker"] == "cue")  # the blob has no hands


def test_parse_drops_invented_numbers_and_banned_words():
    raw = _reply()
    raw["lines"].insert(3, {"speaker": "KAI", "text": "It saves 47 percent on every call.", "shot": "kai"})
    raw["lines"].insert(4, {"speaker": "CUE", "text": "That is a game-changer for sure.", "shot": "cue"})
    raw["lines"][2]["broll"]["data"]["right"]["value"] = 99
    cs = parse(raw, cast=CAST, source=SOURCE, banned=["game-changer"])
    texts = [ln["text"] for ln in cs.lines]
    assert not any("47" in t or "game-changer" in t for t in texts)
    assert "broll" not in cs.lines[2]  # 99 is not in the source


def test_parse_rejects_short_or_mascot_opened_scripts():
    assert parse(_reply(lines=_reply()["lines"][:4]), cast=CAST, source=SOURCE, banned=[]) is None
    lines = _reply()["lines"]
    assert parse(_reply(lines=[lines[1], *lines]), cast=CAST, source=SOURCE, banned=[]) is None


def test_no_broll_on_the_hook_and_unknown_pieces_dropped():
    raw = _reply()
    raw["lines"][0]["broll"] = {"piece": "counter", "data": {"label": "x", "from": 0, "to": 10}}
    raw["lines"][2]["broll"] = {"piece": "explosion", "data": {}}
    cs = parse(raw, cast=CAST, source=SOURCE, banned=[])
    assert "broll" not in cs.lines[0] and "broll" not in cs.lines[2]


def test_write_returns_none_when_the_model_fails():
    class Boom:
        def complete_json(self, *a, **k):
            raise RuntimeError("quota")

    brief = SimpleNamespace(headline="h", model_dump_json=lambda **k: "{}")
    assert write(Boom(), brief, None, cast=CAST) is None


def test_ab_pick_is_deterministic_and_respects_share():
    assert chosen("abc", 1.0) and not chosen("abc", 0.0)
    picks = [chosen(f"story-{i}", 0.5) for i in range(400)]
    assert picks == [chosen(f"story-{i}", 0.5) for i in range(400)]
    assert 140 < sum(picks) < 260


def test_config_defaults_off_and_bounds():
    c = CharactersConfig()
    assert not c.enabled and c.share == 0
    with pytest.raises(ValueError):
        CharactersConfig(share=1.5)


def test_bundled_kit_has_cast_packs_and_plate():
    kit = load_kit("context_unfiltered")
    from pathlib import Path

    d = Path(kit["dir"])
    assert (d / kit["set"]["plate"]).exists()
    assert {"left", "right"} <= set(kit["set"]["slots"])
    for cid in ("kai", "cue"):
        assert (d / "packs" / cid / "pack.json").exists()


def test_sfx_follow_the_edit():
    turns = [{"start": 0, "end": 2, "shot": "kai_close"}, {"start": 2.1, "end": 4, "shot": "cue"},
             {"start": 4.1, "end": 6, "shot": "cue", "broll": {"piece": "counter"}}]
    names = [e[0] for e in _sfx_events(turns, 9.0, "hook")]
    assert names[0] == "hit" and "swish" in names and "whoosh" in names and "tick" in names and names[-1] == "chime"


def test_use_characters_gate():
    from narovva.config import load_channel
    from narovva.language import ENGLISH, HINDI
    from narovva.orchestration.run_channel import use_characters

    ch = load_channel("config/channels/example-tech-ig.yaml")
    assert not use_characters(ch, "x", ENGLISH)  # shipped off
    ch.characters.enabled, ch.characters.share = True, 1.0
    assert use_characters(ch, "x", ENGLISH)
    assert not use_characters(ch, "x", HINDI)


def test_broll_figures_match_the_source_in_any_magnitude_form():
    from narovva.characters.script import broll_grounded

    src = "Old databases held fewer than 200,000 descriptions; Osmo has more than 10 million labels."
    ok = {"left": {"value": 200000, "display": "200K"}, "right": {"value": 10000000, "display": "10M"}}
    assert broll_grounded(ok, src)
    assert broll_grounded({"to": "10 million"}, src)
    assert not broll_grounded({"right": {"value": 12000000, "display": "12M"}}, src)
    assert not broll_grounded({"to": 47}, src)
    assert broll_grounded({"label": "10 molecules"}, src)  # "m" of a word is not "million"
