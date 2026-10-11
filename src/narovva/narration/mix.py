"""Mix voice-over clips with the music bed: the bed sits faint and ducks under
the voice; the master is normalised to -14 LUFS with a -1.5 dB true-peak limit."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import imageio_ffmpeg

from .errors import NarrationError
from .tts import Clip


def mix_voice_and_music(
    clips: list[Clip], starts: list[float], music_bytes: bytes, total: float, *,
    music_db: float = -16.0,
) -> bytes:
    """`starts[i]` is when clip i begins (seconds). Returns an mp3 of length `total`."""
    if len(clips) != len(starts) or not clips:
        raise NarrationError("clips/starts mismatch")
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as tmp:
        tmpd = Path(tmp)
        cmd = [ff, "-v", "error", "-y"]
        for i, c in enumerate(clips):
            (tmpd / f"v{i}.wav").write_bytes(c.wav)
            cmd += ["-i", str(tmpd / f"v{i}.wav")]
        (tmpd / "music.src").write_bytes(music_bytes)
        cmd += ["-stream_loop", "-1", "-i", str(tmpd / "music.src")]
        n = len(clips)
        parts = [
            f"[{i}:a]adelay={int(starts[i] * 1000)}|{int(starts[i] * 1000)},apad[v{i}]" for i in range(n)
        ]
        voices = "".join(f"[v{i}]" for i in range(n))
        parts.append(f"{voices}amix=inputs={n}:normalize=0:duration=longest,atrim=0:{total:.3f},asplit=2[voice][vsc]")
        parts.append(f"[{n}:a]atrim=0:{total:.3f},aresample=44100,volume={music_db}dB[bed]")
        parts.append("[bed][vsc]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=350[ducked]")
        parts.append("[voice][ducked]amix=inputs=2:normalize=0:duration=longest[mix]")
        parts.append(f"[mix]loudnorm=I=-14:TP=-1.5:LRA=9,afade=t=out:st={max(total - 1.0, 0):.3f}:d=1.0[out]")
        out = tmpd / "mix.mp3"
        cmd += ["-filter_complex", ";".join(parts), "-map", "[out]", "-t", f"{total:.3f}",
                "-c:a", "libmp3lame", "-q:a", "3", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        if r.returncode != 0 or not out.exists():
            raise NarrationError(f"audio mix failed: {r.stderr[-500:]}")
        return out.read_bytes()
