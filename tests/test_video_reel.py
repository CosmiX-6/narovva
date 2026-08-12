from __future__ import annotations

import subprocess

import imageio_ffmpeg
import pytest
from PIL import Image

from narovva.video.reel import VideoAssemblyError, assemble_reel


def test_assemble_reel_raises_without_images(tmp_path):
    with pytest.raises(VideoAssemblyError):
        assemble_reel([], b"", str(tmp_path / "out.mp4"))


@pytest.fixture
def silent_mp3_bytes(tmp_path) -> bytes:
    out = tmp_path / "silence.mp3"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", "8", "-q:a", "9",
            str(out),
        ],
        check=True, capture_output=True,
    )
    return out.read_bytes()


def test_assemble_reel_produces_playable_9x16_video(tmp_path, silent_mp3_bytes):
    image_paths = []
    for i, color in enumerate([(30, 60, 90), (90, 30, 60)]):
        path = tmp_path / f"slide{i}.png"
        Image.new("RGB", (1080, 1920), color).save(path)
        image_paths.append(str(path))

    output_path = str(tmp_path / "reel.mp4")
    result = assemble_reel(image_paths, silent_mp3_bytes, output_path)

    assert result == output_path
    assert (tmp_path / "reel.mp4").stat().st_size > 0

    probe = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-i", output_path],
        capture_output=True, text=True,
    )
    info = probe.stderr
    assert "1080x1920" in info
    assert "Video:" in info
    assert "Audio:" in info
