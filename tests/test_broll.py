from __future__ import annotations

import shutil
from types import SimpleNamespace

import pytest
from PIL import Image

from narovva.config.schema import BrollConfig, MotionStyleConfig
from narovva.motion import broll
from narovva.motion.render import _stage_media

BEATS = [
    {"scene": "headline", "lines": ["Nvidia is worth five trillion dollars."]},
    {"scene": "quote", "lines": ["Jensen Huang called it a revolution.", "Rivals disagree."]},
    {"scene": "number", "lines": ["Shares are up fifty percent."]},
    {"scene": "cta", "lines": ["Follow for more."]},
]


def test_only_reusable_licences_pass():
    for ok in ("CC BY-SA 4.0", "CC BY 2.0", "CC0", "Public domain", "Pexels License", "cc-by-sa-3.0"):
        assert broll.free_license(ok), ok
    for bad in ("CC BY-NC 4.0", "CC BY-ND 2.0", "CC BY-NC-SA 3.0", "Fair use", "All rights reserved", ""):
        assert not broll.free_license(bad), bad


def test_off_by_default_and_on_the_motion_look():
    assert MotionStyleConfig().broll.enabled is False
    assert BrollConfig(enabled=True).sources == ["commons", "openverse", "pexels"]


def test_wants_keep_only_real_beats_with_searches():
    raw = {"wants": [
        {"beat": 0, "subject": "Nvidia", "type": "organisation", "queries": ["Nvidia headquarters"], "logo": True},
        {"beat": 1, "subject": "Jensen Huang", "type": "person", "queries": ["Jensen Huang"], "stock": "ceo", "cutout": True},
        {"beat": 3, "subject": "follow", "queries": ["x"]},             # the cta: never
        {"beat": 9, "subject": "ghost", "queries": ["x"]},              # no such beat
        {"beat": 2, "subject": "shares", "queries": []},                # nothing to search
        {"beat": 0, "subject": "again", "queries": ["x"]},              # one want per beat
    ]}
    wants = broll.parse_wants(raw, BEATS)
    assert [w.beat for w in wants] == [0, 1]
    assert wants[1].stock is None and wants[1].cutout       # a named person never gets stock footage
    assert broll.parse_wants("not json", BEATS) == []


def _cand(kind="image", **kw):
    return broll.Candidate(provider=kw.pop("provider", "commons"), kind=kind, title="t", thumb="https://x/t.jpg",
                           full="https://x/f.jpg", page="", license="CC BY 4.0", author="A", width=1600, height=2000,
                           **kw)


def test_edits_are_checked_against_the_wants():
    wants = [broll.Want(beat=0, subject="s", type="place", queries=["q"], candidates=[_cand(), _cand("video", seconds=60)]),
             broll.Want(beat=1, subject="p", type="person", queries=["q"], candidates=[_cand()])]
    raw = {"edits": [
        {"beat": 0, "want": 0, "pick": "B", "use": "cutout", "start": 90, "line": 7, "move": "spin"},
        {"beat": 1, "want": 1, "pick": "Z"},                     # no such candidate
        {"beat": 2, "want": 1, "pick": "A"},                     # the want is for another beat
        {"beat": 1, "want": 1, "pick": "a", "use": "cutout", "side": "left", "focus": [2, -1]},
    ]}
    edits = broll.parse_edits(raw, wants, BEATS, max_beats=4)
    assert [e["beat"] for e in edits] == [0, 1]
    clip, person = edits
    assert clip["use"] == "backdrop" and clip["start"] == 57.0 and clip["line"] == 0 and clip["move"] == "in"
    assert person["use"] == "cutout" and person["side"] == "left" and person["focus"] == [1.0, 0.0]
    assert len(broll.parse_edits(raw, wants, BEATS, max_beats=1)) == 1


def test_clip_frames_spread_through_the_clip():
    assert broll.frame_times(100) == [15.0, 45.0, 75.0]
    assert broll.frame_times(0) == [1.0, 4.0, 8.0]


class _Agent:
    def __init__(self, reply):
        self.reply, self.calls = reply, []

    def complete_json(self, system, user):
        self.calls.append((system, user))
        return self.reply


def test_the_whole_step_puts_media_on_the_chosen_beats(tmp_path, monkeypatch):
    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (1600, 1200), (90, 120, 160)).save(photo)

    def fake_download(url, dest, *, max_bytes, kinds):
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(photo, dest)
        return dest

    monkeypatch.setattr(broll, "download", fake_download)
    monkeypatch.setattr(broll, "gather", lambda w, **kw: [_cand(), _cand()])
    beats = [dict(b) for b in BEATS]
    scout = _Agent({"wants": [{"beat": 0, "subject": "Nvidia HQ", "type": "place", "queries": ["Nvidia HQ"]}]})
    editor = _Agent({"edits": [{"beat": 0, "want": 0, "pick": "B", "use": "backdrop", "focus": [0.5, 0.5], "move": "left"}]})
    credits = broll.add_broll(SimpleNamespace(beats=beats), "Nvidia", tmp_path / "work",
                              config=BrollConfig(enabled=True), token=None, agents=(scout, editor))
    media = beats[0]["media"]
    assert media["use"] == "backdrop" and media["move"] == "left" and media["type"] == "image"
    assert Image.open(media["path"]).size == broll.FRAME
    assert (tmp_path / "work" / "sheet_0.jpg").is_file() and "sheet_0.jpg" in editor.calls[0][1]
    assert credits == ["A, t (CC BY 4.0, via Wikimedia Commons)"]
    assert "Images & footage:" in broll.caption_credits(credits)
    assert all("media" not in b for b in beats[1:])


def test_no_token_no_broll(tmp_path):
    assert broll.add_broll(SimpleNamespace(beats=list(BEATS)), "x", tmp_path, config=BrollConfig(enabled=True),
                           token=None) == []


def test_a_failing_scout_leaves_the_reel_alone(tmp_path):
    class Boom:
        def complete_json(self, s, u):
            raise RuntimeError("usage limit")

    beats = [dict(b) for b in BEATS]
    assert broll.add_broll(SimpleNamespace(beats=beats), "x", tmp_path / "w", config=BrollConfig(enabled=True),
                           token=None, agents=(Boom(), Boom())) == []
    assert all("media" not in b for b in beats)


@pytest.mark.parametrize("kind", ["image", "video"])
def test_staging_times_media_from_the_line_that_names_it(tmp_path, kind):
    src = tmp_path / ("m.mp4" if kind == "video" else "m.jpg")
    src.write_bytes(b"x")
    assets = tmp_path / "assets"
    assets.mkdir()
    slides = [
        {"kind": "headline", "duration": 4.0, "parts": [{"at": 0.15}]},
        {"kind": "quote", "duration": 6.0, "parts": [{"at": 0.15}, {"at": 2.5}],
         "media": {"path": str(src), "type": kind, "use": "backdrop" if kind == "video" else "cutout",
                   "line": 1, "move": "up", "side": "left", "seconds": 3.0}},
    ]
    out, back, front = _stage_media(slides, assets)
    m = out[1]["media"]
    assert m["t0"] == pytest.approx(3.7 + 2.5 - 0.12)
    if kind == "video":
        assert m["t1"] == pytest.approx(m["t0"] + 3.0)        # a clip ends when its footage does
        assert 'data-start="6.080"' in back and "<video" in back and not front
    else:
        assert m["t1"] == pytest.approx(3.7 + 6.0)
        assert 'class="cutout left"' in front and not back
    assert (assets / f"m1{src.suffix}").is_file() and "media" not in out[0]


def test_a_cutout_beat_says_its_point_as_a_headline_above_the_person(tmp_path, monkeypatch):
    monkeypatch.setattr(broll, "gather", lambda w, **kw: [_cand()])
    monkeypatch.setattr(broll, "contact_sheet", lambda w, folder, n: folder / "sheet.jpg")
    monkeypatch.setattr(broll, "finish", lambda edit, folder, n, cutouts: {
        "type": "image", "use": "cutout", "path": "p.png", "line": 0, "move": "in", "side": "right", "credit": "c"})
    beats = [{"scene": "compose", "lines": ["Jensen Huang spoke."], "screens": ["Jensen Huang spoke."],
              "cmarks": ["Huang"], "takeaway": ("Huang", "speaks"), "data": {"layout": "row"}}]
    scout = _Agent({"wants": [{"beat": 0, "subject": "Jensen Huang", "type": "person", "queries": ["Jensen Huang"]}]})
    editor = _Agent({"edits": [{"beat": 0, "want": 0, "pick": "A", "use": "cutout"}]})
    broll.add_broll(SimpleNamespace(beats=beats), "x", tmp_path / "w", config=BrollConfig(enabled=True),
                    token=None, agents=(scout, editor))
    assert beats[0]["scene"] == "headline" and beats[0]["data"]["text"] == "Huang speaks"
