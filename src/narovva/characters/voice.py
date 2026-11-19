"""Cast voices: Microsoft neural voices through edge-tts (free, no key), one voice per character, delivery (rate/pitch)
from each line's emotion, real word timings for captions and lip-sync, and mouth-movement envelopes."""

from __future__ import annotations

import asyncio
import random
import subprocess
import wave
from pathlib import Path

import numpy as np

PROSODY = {  # emotion -> (rate %, pitch Hz)
    "host": {"neutral": (0, 0), "explain": (0, 0), "curious": (5, 3), "laugh": (7, 4), "wow": (9, 5), "deadpan": (-7, -3), "shrug": (-3, -1),
             "proud": (4, 2), "shock": (8, 4), "happy": (5, 3), "confused": (-3, 2)},
    "mascot": {"neutral": (2, 0), "shock": (12, 8), "happy": (8, 5), "confused": (-4, 3), "proud": (5, 3), "deadpan": (-6, -3),
               "curious": (6, 4), "wow": (10, 6), "explain": (2, 0), "laugh": (8, 5), "shrug": (0, 0)},
}
SR = 24000


def _exe():
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _ffmpeg(args):
    r = subprocess.run([_exe(), "-y", "-v", "error", *map(str, args)], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("ffmpeg: " + r.stderr[-400:])


def _tts(text, voice, rate, pitch, mp3):
    import edge_tts
    words = []

    async def go():
        comm = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch, boundary="WordBoundary")
        with open(mp3, "wb") as f:
            async for ch in comm.stream():
                if ch["type"] == "audio":
                    f.write(ch["data"])
                elif ch["type"] == "WordBoundary":
                    words.append({"w": ch["text"], "start": ch["offset"] / 1e7, "end": (ch["offset"] + ch["duration"]) / 1e7})

    for attempt in range(3):
        try:
            asyncio.run(go())
            if words:
                return words
        except Exception:
            if attempt == 2:
                raise
    raise RuntimeError("edge-tts returned no audio")


def _amp(path, hz):
    with wave.open(str(path), "rb") as w:
        x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
        sr = w.getframerate()
    n = max(1, sr // hz)
    env = np.array([np.sqrt(np.mean(x[i:i + n] ** 2)) if len(x[i:i + n]) else 0 for i in range(0, len(x), n)])
    p = np.percentile(env, 95) or 1.0
    return np.clip(env / p, 0, 1)


def record(lines: list[dict], cast: dict, workdir: Path, seed: str = "", hz: int = 30):
    """lines = character script lines (speaker = cast id). cast = {id: {"voice", "kind"}}.
    -> (timed turns, track wav path, {id: envelope}, duration)."""
    workdir.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(seed)
    amp = {cid: [] for cid in cast}
    out, parts, t = [], [], 0.0
    for k, tr in enumerate(lines):
        who = tr["speaker"]
        c = cast[who]
        role = "mascot" if c.get("kind") == "blob" else "host"
        nxt = lines[k + 1] if k + 1 < len(lines) else None
        g = 0.14 if k == 0 else (0.04 if nxt and nxt["speaker"] == who else (0.07 if tr["text"].rstrip().endswith("?") else 0.10))
        dr, dp = PROSODY[role].get(tr.get("emotion", "neutral"), (0, 0))
        mp3, raw, fin = workdir / f"raw_{k:03d}.mp3", workdir / f"raw_{k:03d}.wav", workdir / f"t_{k:03d}.wav"
        words = _tts(tr["text"], c["voice"], f"{dr + rnd.randint(-3, 3):+d}%", f"{dp + rnd.randint(-2, 2):+d}Hz", mp3)
        _ffmpeg(["-i", mp3, "-ar", SR, "-ac", 1, "-c:a", "pcm_s16le", raw])
        lead, tail_end = max(0.0, words[0]["start"] - 0.04), words[-1]["end"] + 0.14
        _ffmpeg(["-i", raw, "-af", f"atrim=start={lead:.3f}:end={tail_end:.3f},asetpts=PTS-STARTPTS,apad=pad_dur={g}", "-ar", SR, "-ac", 1,
                 "-c:a", "pcm_s16le", fin])
        with wave.open(str(fin), "rb") as w:
            dur = w.getnframes() / w.getframerate() - g
        speech = max(dur, 0.3)
        a = _amp(fin, hz)
        a[int(speech * hz):] = 0
        n_total = int(round((speech + g) * hz))
        for cid in amp:
            seg = a[:n_total] if cid == who else np.zeros(n_total)
            if len(seg) < n_total:
                seg = np.pad(seg, (0, n_total - len(seg)))
            amp[cid] += [round(float(v), 3) for v in seg]
        out.append({**tr, "start": round(t, 3), "end": round(t + speech, 3),
                    "words": [{"w": w["w"], "start": round(t + w["start"] - lead, 3), "end": round(t + w["end"] - lead, 3)} for w in words]})
        parts.append(fin)
        t += speech + g
    lst = workdir / "concat.txt"
    lst.write_text("".join(f"file '{p.name}'\n" for p in parts), encoding="utf-8")
    track = workdir / "voices.wav"
    subprocess.run([_exe(), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", track.name], cwd=workdir, check=True)
    return out, track, amp, round(t, 2)
