from __future__ import annotations

import subprocess

import imageio_ffmpeg
import pytest
from PIL import Image

from narovva.video.reel import VideoAssemblyError, assemble_reel, slide_duration


def test_assemble_reel_raises_without_images(tmp_path):
    with pytest.raises(VideoAssemblyError):
        assemble_reel([], b"", str(tmp_path / "out.mp4"))


def test_assemble_reel_rejects_mismatched_durations_length(tmp_path):
    with pytest.raises(VideoAssemblyError):
        assemble_reel(["a.png", "b.png"], b"", str(tmp_path / "out.mp4"), durations=[1.8])


def test_slide_duration_floors_at_1_8_seconds_for_sparse_text():
    assert slide_duration(0) == pytest.approx(1.8 + 0.4)
    assert slide_duration(5) == pytest.approx(1.8 + 0.4)  # 5/14 < floor


def test_slide_duration_scales_with_character_count_above_the_floor():
    # 280 chars / 14 chars-per-second = 20s, well above the 1.8s floor
    assert slide_duration(280) == pytest.approx(20.0 + 0.4)


@pytest.fixture
def silent_mp3_bytes(tmp_path) -> bytes:
    # assemble_reel uses -shortest, so this must outlast every test's video
    # (longest here: 3 slides * _SECONDS_PER_IMAGE) or the audio track will
    # silently truncate the output.
    out = tmp_path / "silence.mp3"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y",
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
            "-t", "30", "-q:a", "9",
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
    assert "Duration: 00:00:07.4" in info  # 2 slides * 4s, minus one 0.6s crossfade overlap


def test_assemble_reel_honors_per_slide_durations(tmp_path, silent_mp3_bytes):
    image_paths = []
    for i, color in enumerate([(30, 60, 90), (90, 30, 60)]):
        path = tmp_path / f"slide{i}.png"
        Image.new("RGB", (1080, 1920), color).save(path)
        image_paths.append(str(path))

    output_path = str(tmp_path / "reel.mp4")
    # 2s + 3s, minus one 0.6s crossfade overlap = 4.4s total.
    assemble_reel(image_paths, silent_mp3_bytes, output_path, durations=[2.0, 3.0])

    probe = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-i", output_path],
        capture_output=True, text=True,
    )
    assert "Duration: 00:00:04.4" in probe.stderr


def test_assemble_reel_advances_past_the_first_slide(tmp_path, silent_mp3_bytes):
    """Regression test: a zoompan/input-framerate mismatch previously caused
    every slide after the first to never appear, so the whole clip was one
    image zoomed in a loop regardless of how many slides were rendered."""
    image_paths = []
    for i, color in enumerate([(200, 30, 30), (30, 200, 30), (30, 30, 200)]):
        path = tmp_path / f"slide{i}.png"
        Image.new("RGB", (1080, 1920), color).save(path)
        image_paths.append(str(path))

    output_path = str(tmp_path / "reel.mp4")
    assemble_reel(image_paths, silent_mp3_bytes, output_path)

    def frame_at(seconds: float) -> tuple[int, int, int]:
        # -ss after -i (output seeking) is frame-accurate; seeking before -i
        # is imprecise and can land past the last frame on a short synthetic
        # stream like this test's, silently producing no output despite a
        # zero exit code.
        frame_path = tmp_path / f"frame_{seconds}.png"
        subprocess.run(
            [
                imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", output_path, "-ss", str(seconds),
                "-frames:v", "1", str(frame_path),
            ],
            check=True, capture_output=True,
        )
        return Image.open(frame_path).convert("RGB").getpixel((540, 960))

    colors_seen = {frame_at(t) for t in (1.0, 5.0, 9.0)}
    assert len(colors_seen) == 3, f"expected 3 distinct slide colors, got {colors_seen}"
