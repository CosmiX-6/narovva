"""Character reels: a recurring cast (host + mascot) acts the story out on a branded set, with animated b-roll that SHOWS how
it works, word-timed captions, the story's music ducked under two neural voices, and sound effects placed from the edit.

Pure 2D compositing of pre-rendered assets (sprite packs + a set plate built once in Blender by the content studio), so a reel
renders on a CPU-only runner. Any failure returns None and the caller falls back to the motion reel, then the plain reel.

    build_character_reel(channel, brief, article, track, out_path, llm=..., hook=..., said=..., seed=...)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

logger = logging.getLogger(__name__)

HERE = Path(__file__).resolve().parent
ENGINE = HERE / "engine" / "render.py"
ASSETS = HERE / "assets"


def ffmpeg_exe() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()

MOOD_BY_CATEGORY = {"ai": "tech", "technology": "tech", "science": "calm", "health": "calm", "business": "upbeat",
                    "finance": "upbeat", "politics": "tense"}


def chosen(content_id: str, share: float) -> bool:
    """Deterministic A/B pick: the same story always lands in the same arm."""
    if share >= 1:
        return True
    if share <= 0:
        return False
    h = int(hashlib.sha256(content_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return h < share


def load_kit(name: str) -> dict:
    d = ASSETS / name
    kit = json.loads((d / "kit.json").read_text(encoding="utf-8"))
    kit["set"] = json.loads((d / "set.json").read_text(encoding="utf-8"))
    kit["dir"] = str(d)
    return kit


def _cast(kit: dict, cfg) -> tuple[dict, dict]:
    """-> ({NAME: {id, kind, role}} for the writer, {id: {voice, kind, name, pack, slot}} for voices + render)."""
    d = Path(kit["dir"])
    writer, members = {}, {}
    slots = ["left", "right", "far_left", "far_right"]
    for i, member in enumerate(cfg.cast):
        spec = json.loads((d / "packs" / member.id / "spec.json").read_text(encoding="utf-8"))
        writer[member.name] = {"id": member.id, "kind": spec.get("kind", "human"), "role": member.role}
        members[member.id] = {"voice": member.voice or (spec.get("voice") or {}).get("name") or "en-US-BrianMultilingualNeural",
                              "kind": spec.get("kind", "human"), "name": spec.get("name", member.name.title()),
                              "pack": str(d / "packs" / member.id), "slot": member.slot or slots[i % len(slots)],
                              "antenna": "antenna" in (spec.get("extras") or [])}
    return writer, members


def _sfx_events(turns, total, hook):
    ev = [("hit", 0.02, 0.55)] if hook else []
    prev = None
    for k, tr in enumerate(turns):
        if tr.get("broll"):
            ev.append(("whoosh", max(0, tr["start"] - 0.18), 0.55))
            if tr["broll"].get("piece") == "counter":
                ev += [("tick", tr["start"] + 0.15 + j * 0.09, 0.18) for j in range(8)]
            if tr["broll"].get("piece") in ("compare", "timeline"):
                ev.append(("riser", tr["start"] + 0.1, 0.3))
        elif tr.get("shot") != prev and k:
            ev.append(("swish", max(0, tr["start"] - 0.08), 0.22))
        prev = tr.get("shot")
    ev.append(("chime", max(0, total - 2.55), 0.5))
    return ev


def build_character_reel(channel, brief, article, track, output_path: str, *, llm, hook: str | None = None,
                         said: str | None = None, seed: str = "", workdir: str | None = None) -> tuple[str | None, str | None]:
    """Render the character reel. -> (mp4 path, voice label) or (None, None) after logging why."""
    from . import audio, script, voice

    cfg = channel.characters
    t0 = time.time()
    ff = ffmpeg_exe()
    try:
        kit = load_kit(cfg.kit)
        writer_cast, members = _cast(kit, cfg)
        cs = script.write(llm, brief, article, cast=writer_cast, seconds=cfg.target_seconds, hook=hook, said=said,
                          audience=channel.audience, banned=channel.banned_words, never_claim=list(channel.voice.never_claim) if channel.voice else [],
                          broll_share=cfg.broll_share)
        if cs is None:
            return None, None
        wd = Path(workdir or tempfile.mkdtemp(prefix="narovva_chars_"))
        turns, track_wav, amp, duration = voice.record(cs.lines, members, wd / "voice", seed=seed)
        total = duration + cfg.end_card_seconds
        brand = channel.brand
        category = getattr(brief.category, "value", str(brief.category))
        accent = brand.category_accents.get(category) or brand.accent_color
        logo = Path(brand.logo_path) if brand.logo_path else None
        sm = kit["set"]
        spec = {
            "duration": total, "ffmpeg": ff, "turns": turns, "amp": amp, "amp_hz": 30, "puppets": {},
            "hook": {"text": cs.hook_screen, "highlight": cs.highlight, "until": round(max(2.2, min(3.4, turns[0]["end"] + 0.3)), 2)}
            if cs.hook_screen else None,
            "stage": {"plate": str(Path(kit["dir"]) / sm.get("plate", "plate.webp")), "slots": sm["slots"], "marks": sm.get("marks", {}),
                      "particles": sm.get("particles", "dust"),
                      "cast": [{"id": cid, **{k: m[k] for k in ("name", "pack", "slot", "kind", "antenna")}} for cid, m in members.items()],
                      "palette": {"accent": accent, "highlight": (kit.get("brand") or {}).get("highlight", "#FACC15")}},
            "brand": {"name": brand.name, "handle": f"@{brand.social_handle}" if brand.social_handle else "", "bg": brand.background_color or "#0A0E1A",
                      "accent": accent, "logo": str(logo) if logo and logo.exists() else None,
                      "follow": cfg.follow_line or "Follow for the context behind the headline"},
        }
        sp = wd / "spec.json"
        sp.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
        silent = wd / "silent.mp4"
        env = {**os.environ, "PYTHONUTF8": "1"}
        r = subprocess.run([sys.executable, "-W", "ignore", str(ENGINE), str(sp), str(silent), str(cfg.scale), "30"],
                           capture_output=True, text=True, env=env, timeout=cfg.render_timeout_seconds)
        if r.returncode != 0 or not silent.exists():
            raise RuntimeError(f"render failed: {(r.stderr or r.stdout)[-800:]}")
        music = None
        if getattr(track, "audio_bytes", None):
            music = wd / "music_in.mp3"
            music.write_bytes(track.audio_bytes)
        elif cfg.procedural_music:
            music = Path(audio.music(MOOD_BY_CATEGORY.get(category, "tech"), total, wd / "music.wav", seed=len(turns)))
        mixed = wd / "mix.wav"
        audio.mix(track_wav, mixed, total, _sfx_events(turns, total, cs.hook_screen), str(music) if music else None,
                  music_gain=cfg.music_gain, ffmpeg=ff, workdir=wd)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([ff, "-y", "-v", "error", "-i", str(silent), "-i", str(mixed), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.2f}", "-movflags", "+faststart", output_path], check=True)
        logger.info("character reel: %d lines, %d b-roll, %.0fs, rendered in %.0fs", len(turns), sum(1 for t in turns if t.get("broll")),
                    total, time.time() - t0)
        return output_path, "characters:" + "+".join(m["voice"] for m in members.values())
    except Exception as exc:  # degrade to the motion reel, never lose the post
        logger.warning("channel %s: character reel failed (%s); falling back", channel.id, str(exc)[:300])
        return None, None
