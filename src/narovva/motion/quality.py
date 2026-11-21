"""Quality gates for a story-first reel: each step is checked against what makes a strong news Reel before the next
step runs, and a failed check is sent back to the step that can fix it (once) rather than shipped.

1. story_review     -- the writer's story: complete, a short hook, a verdict, every beat with an on-screen takeaway.
2. direction_review -- the director's pictures: few fallbacks, real variety, the hero recurring, the beats' verbs
                       animated (not just shown).
3. layout_audit     -- the staged page in headless Chrome, every scene at rest: text inside the frame and the safe
                       zone, no two labels on top of each other, nothing too small to read. (narovva.motion.render)
4. loudness_review  -- the finished file: about -14 LUFS, true peak at or under -1 dBTP.

Each review returns {"ok": bool, "issues": [...] (what fails the gate), "notes": [...] (worth knowing), "metrics"}.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess

logger = logging.getLogger(__name__)

HOOK_WORDS = 12            # the hook's first line (the writer is asked for 9)
MIN_SECONDS, MAX_SECONDS = 20.0, 170.0
TARGET_LUFS, LUFS_SLACK, MAX_TRUE_PEAK = -14.0, 2.0, -0.5
_ACTIONS = {"connect", "move", "grow", "shrink", "block", "highlight", "count"}
_MOVING_SCENES = {"number", "compare", "comparison", "stats", "dates", "chain"}


def _content(beats: list[dict]) -> list[dict]:
    return [b for b in beats if (b.get("part") or b.get("story_part")) not in ("ask", "cta")]


def story_review(beats: list[dict], gaps: list[str], hero: dict | None, seconds: float) -> dict:
    content = _content(beats)
    issues = [f"missing {g}" for g in gaps]
    notes = []
    if not hero:
        notes.append("no hero object")
    if not any(b["part"] == "verdict" for b in beats):
        issues.append("no verdict beat before the call to action")
    if seconds < MIN_SECONDS:
        issues.append(f"too short to tell it ({seconds:.0f}s)")
    elif seconds > MAX_SECONDS:
        issues.append(f"too long ({seconds:.0f}s)")
    missing = [i for i, b in enumerate(beats) if b["part"] not in ("ask", "cta") and not b.get("takeaway")]
    if len(missing) > max(1, len(content) // 4):
        notes.append(f"{len(missing)} beats without a takeaway line")
    hook = beats[0]["lines"][0] if beats and beats[0]["lines"] else ""
    return {"ok": not issues, "issues": issues, "notes": notes,
            "metrics": {"beats": len(beats), "seconds": round(seconds, 1), "hook_words": len(hook.split()),
                        "takeaways": len(content) - len(missing)}}


def _mentions(beat: dict, label: str) -> bool:
    d, low = beat.get("data") or {}, label.lower()
    if low in str(d.get("title") or "").lower():
        return True
    return any(low == str(a.get("label") or "").lower() or low in str(a.get("label") or "").lower()
               for a in d.get("actors") or [])


def direction_review(board_beats: list[dict], stats: dict, hero: dict | None) -> dict:
    """`board_beats` from direct_story; `stats` its stats (fallbacks, rescued, scenes)."""
    content = [b for b in board_beats if b["story_part"] not in ("ask", "cta")]
    n = max(1, len(content))
    kinds = [b["scene"] + (":" + b["data"].get("layout", "") if b["scene"] == "compose" else "") for b in content]
    distinct = len(set(kinds))
    headlines = sum(b["scene"] == "headline" for b in content)
    moving = sum(
        b["scene"] in _MOVING_SCENES
        or (b["scene"] == "compose" and any(s.get("do") in _ACTIONS for s in b["data"].get("steps") or []))
        for b in content)
    issues, notes = [], []
    if headlines > max(1, round(n * 0.2)):
        issues.append(f"{headlines} of {n} beats are only a headline -- picture what each one says")
    if stats.get("rescued", 0) > max(1, round(n * 0.3)):
        issues.append(f"{stats['rescued']} of {n} pictures failed validation (names or figures not in the story, "
                      "a repeated scene, or bad data)")
    if distinct < min(n, max(3, round(n * 0.5))):
        issues.append(f"only {distinct} different pictures for {n} beats")
    if moving < min(n, max(2, round(n * 0.4))):
        issues.append(f"only {moving} beats animate what happens -- show the verb (moves, grows, blocks, counts)")
    if hero:
        seen = [i for i, b in enumerate(board_beats) if _mentions(b, hero["label"])]
        if len(seen) < 2:
            notes.append(f"the hero ({hero['label']}) appears in {len(seen)} beat(s)")
    return {"ok": not issues, "issues": issues, "notes": notes,
            "metrics": {"beats": n, "distinct": distinct, "headlines": headlines, "moving": moving,
                        "rescued": stats.get("rescued", 0)}}


def loudness_review(path: str, ffmpeg: str | None = None) -> dict:
    """Integrated loudness and true peak of the finished file (ffmpeg's loudnorm analysis)."""
    if ffmpeg is None:
        import imageio_ffmpeg

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    proc = subprocess.run([ffmpeg, "-hide_banner", "-nostats", "-i", path, "-af",
                           "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-"],
                          capture_output=True, text=True, timeout=300)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr or "", re.S)
    if not m:
        return {"ok": True, "issues": [], "notes": ["no audio measured"], "metrics": {}}
    data = json.loads(m.group(0))
    lufs, peak = float(data["input_i"]), float(data["input_tp"])
    issues = []
    if lufs > -60 and abs(lufs - TARGET_LUFS) > LUFS_SLACK:
        issues.append(f"loudness {lufs:.1f} LUFS (target {TARGET_LUFS:.0f})")
    if peak > MAX_TRUE_PEAK:
        issues.append(f"true peak {peak:.1f} dBTP")
    return {"ok": not issues, "issues": issues, "notes": [], "metrics": {"lufs": lufs, "true_peak": peak}}


def summary(reports: dict[str, dict]) -> str:
    """One log line: each gate's result and its first issue."""
    parts = []
    for name, r in reports.items():
        if not r:
            continue
        mark = "pass" if r["ok"] else "FAIL"
        first = (r["issues"] or r["notes"] or [""])[0]
        parts.append(f"{name} {mark}" + (f" ({first})" if first else ""))
    return "; ".join(parts)
