"""Text-to-speech providers (OpenAI, ElevenLabs, Gemini) behind one tiny
interface, plus per-line synthesis with measured durations."""

from __future__ import annotations

import base64
import io
import logging
import os
import subprocess
import tempfile
import threading
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import httpx
import imageio_ffmpeg

from .errors import NarrationError

logger = logging.getLogger(__name__)
_RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass
class Clip:
    wav: bytes       # 44.1 kHz mono 16-bit
    seconds: float


_QUOTA_HINTS = ("insufficient_quota", "billing", "exceeded your current quota", "quota exceeded")


def _post(url: str, *, retries: int = 3, **kwargs) -> httpx.Response:
    """POST with backoff on transient errors. The provider's own error message is
    always kept; a 429 that is really a billing/quota problem fails at once
    (retrying can't fix it) with that message."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = httpx.post(url, timeout=60.0, **kwargs)
        except httpx.HTTPError as exc:
            last = NarrationError(f"TTS request error: {exc}")
        else:
            if resp.status_code < 400:
                return resp
            body = (resp.text or "")[:400]
            logger.warning("TTS %s -> HTTP %s: %s", url.split("?")[0], resp.status_code, body)
            if resp.status_code not in _RETRY_STATUS or (
                resp.status_code == 429 and any(h in body.lower() for h in _QUOTA_HINTS)
            ):
                raise NarrationError(f"TTS request failed (HTTP {resp.status_code}): {body}")
            last = NarrationError(f"HTTP {resp.status_code}: {body}")
            try:
                time.sleep(min(float(resp.headers.get("retry-after", 0)), 10.0))
            except (TypeError, ValueError):
                pass
        time.sleep(1.5 * (attempt + 1))
    raise NarrationError(f"TTS request failed after retries: {last}")


class OpenAITTS:
    """gpt-4o-mini-tts: `instructions` steers the delivery."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini-tts"):
        self._key, self._model = api_key, model

    def synthesize(self, text: str, *, voice: str, style: tuple[str, str]) -> bytes:
        resp = _post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {self._key}"},
            json={"model": self._model, "voice": voice, "input": text,
                  "instructions": style[0], "response_format": "mp3"},
        )
        return resp.content


class ElevenLabsTTS:
    """eleven_v3 with audio tags; stability 0.0 is the 'creative' setting that
    gave real emotion. `voice` is a voice_id from the account."""

    def __init__(self, api_key: str, model: str = "eleven_v3"):
        self._key, self._model = api_key, model

    def synthesize(self, text: str, *, voice: str, style: tuple[str, str]) -> bytes:
        resp = _post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
            headers={"xi-api-key": self._key},
            json={"text": f"{style[1]} {text}", "model_id": self._model,
                  "voice_settings": {"stability": 0.0, "similarity_boost": 0.8}},
        )
        return resp.content


class GeminiTTS:
    """Gemini speech models return raw 24 kHz 16-bit mono PCM."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash-preview-tts"):
        self._key, self._model = api_key, model

    def synthesize(self, text: str, *, voice: str, style: tuple[str, str]) -> bytes:
        resp = _post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self._model}:generateContent",
            headers={"x-goog-api-key": self._key},
            json={
                "contents": [{"parts": [{"text": f"{style[0]}\n\n{text}"}]}],
                "generationConfig": {
                    "responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}},
                },
            },
        )
        try:
            pcm = base64.b64decode(resp.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"])
        except (KeyError, IndexError, ValueError) as exc:
            raise NarrationError(f"unexpected Gemini TTS response: {resp.text[:200]}") from exc
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(pcm)
        return buf.getvalue()


_KOKORO_BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
_KOKORO_FILES = {"kokoro-v1.0.onnx": 300_000_000, "voices-v1.0.bin": 20_000_000}  # (min plausible sizes)


def kokoro_dir() -> Path:
    return Path(os.environ.get("NAROVVA_KOKORO_DIR") or Path.home() / ".cache" / "narovva" / "kokoro")


def ensure_kokoro_models() -> tuple[Path, Path]:
    """Model files for the local Kokoro voice, downloaded once and cached."""
    d = kokoro_dir()
    d.mkdir(parents=True, exist_ok=True)
    for name, min_size in _KOKORO_FILES.items():
        path = d / name
        if path.exists() and path.stat().st_size >= min_size:
            continue
        logger.info("downloading Kokoro model file %s (one-time, cached)", name)
        tmp = path.with_suffix(path.suffix + ".part")
        try:
            with httpx.stream("GET", f"{_KOKORO_BASE}/{name}", follow_redirects=True, timeout=300.0) as r:
                r.raise_for_status()
                with open(tmp, "wb") as f:
                    for chunk in r.iter_bytes(1 << 20):
                        f.write(chunk)
        except httpx.HTTPError as exc:
            tmp.unlink(missing_ok=True)
            raise NarrationError(f"could not download Kokoro model {name}: {exc}") from exc
        if tmp.stat().st_size < min_size:
            tmp.unlink(missing_ok=True)
            raise NarrationError(f"downloaded Kokoro file {name} is too small")
        tmp.replace(path)
    return d / "kokoro-v1.0.onnx", d / "voices-v1.0.bin"


class KokoroTTS:
    """Free, offline voice (Kokoro-82M via ONNX): no API key, no quota. Less
    expressive than the cloud voices, but it always works. Needs the
    `narration-local` extra (kokoro-onnx, soundfile)."""

    _lock = threading.Lock()

    def __init__(self, _key: str = "", model: str | None = None, speed: float = 1.12):
        try:
            import soundfile  # noqa: F401
            from kokoro_onnx import Kokoro
        except ImportError as exc:
            raise NarrationError("Kokoro needs: pip install 'narovva[narration-local]'") from exc
        onnx, voices = ensure_kokoro_models()
        self._kokoro, self._speed = Kokoro(str(onnx), str(voices)), speed

    def synthesize(self, text: str, *, voice: str, style: tuple[str, str]) -> bytes:
        import soundfile as sf

        with self._lock:  # one ONNX session; keep synthesis sequential
            samples, rate = self._kokoro.create(
                text, voice=voice, speed=self._speed, lang="en-gb" if voice.startswith("b") else "en-us",
            )
        buf = io.BytesIO()
        sf.write(buf, samples, rate, format="WAV")
        return buf.getvalue()


def build_provider(name: str, api_key: str, model: str | None = None):
    if name == "kokoro":
        return KokoroTTS(api_key, model)
    cls = {"openai": OpenAITTS, "elevenlabs": ElevenLabsTTS, "gemini": GeminiTTS}.get(name)
    if cls is None:
        raise NarrationError(f"unknown narration provider {name!r}")
    if not api_key:
        raise NarrationError(f"no API key for narration provider {name!r}")
    return cls(api_key, model) if model else cls(api_key)


TEMPO = 1.08  # quick-update pace on top of the provider's own; pitch is preserved


def to_clip(audio_bytes: bytes, trim_silence: bool = True, tempo: float = TEMPO) -> Clip:
    """Decode whatever the provider returned to 44.1 kHz mono wav (trimming
    leading/trailing silence, speeding it up by `tempo`) and measure its length."""
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp, "in.audio"), Path(tmp, "out.wav")
        src.write_bytes(audio_bytes)
        af = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,"
              "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse")
        cmd = [ff, "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "44100"]
        filters = ([af] if trim_silence else []) + ([f"atempo={tempo}"] if abs(tempo - 1.0) > 1e-3 else [])
        if filters:
            cmd += ["-af", ",".join(filters)]
        cmd += [str(dst)]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode != 0 or not dst.exists():
            raise NarrationError(f"could not decode TTS audio: {r.stderr[-300:]}")
        data = dst.read_bytes()
    with wave.open(io.BytesIO(data)) as w:
        seconds = w.getnframes() / float(w.getframerate())
    if seconds < 0.3:
        raise NarrationError("TTS returned (almost) no audio")
    return Clip(wav=data, seconds=seconds)


def synthesize_lines(provider, lines: list[str], *, voice: str, style: tuple[str, str]) -> list[Clip]:
    """One clip per line (3 requests at a time). Raises NarrationError if any line fails,
    naming the line (a bare 'no audio' error was undiagnosable in the logs)."""
    def one(line: str) -> Clip:
        try:
            return to_clip(provider.synthesize(line, voice=voice, style=style))
        except NarrationError as exc:
            raise NarrationError(f"{exc} (line: {line!r})") from exc

    with ThreadPoolExecutor(max_workers=3) as pool:
        return list(pool.map(one, lines))
