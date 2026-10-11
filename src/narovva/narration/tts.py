"""Text-to-speech providers (OpenAI, ElevenLabs, Gemini) behind one tiny
interface, plus per-line synthesis with measured durations."""

from __future__ import annotations

import base64
import io
import logging
import subprocess
import tempfile
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


def _post(url: str, *, retries: int = 3, **kwargs) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = httpx.post(url, timeout=60.0, **kwargs)
        except httpx.HTTPError as exc:
            last = exc
        else:
            if resp.status_code not in _RETRY_STATUS:
                if resp.status_code >= 400:
                    raise NarrationError(f"TTS request failed ({resp.status_code}): {resp.text[:300]}")
                return resp
            last = NarrationError(f"TTS request returned {resp.status_code}")
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


def build_provider(name: str, api_key: str, model: str | None = None):
    cls = {"openai": OpenAITTS, "elevenlabs": ElevenLabsTTS, "gemini": GeminiTTS}.get(name)
    if cls is None:
        raise NarrationError(f"unknown narration provider {name!r}")
    if not api_key:
        raise NarrationError(f"no API key for narration provider {name!r}")
    return cls(api_key, model) if model else cls(api_key)


def to_clip(audio_bytes: bytes, trim_silence: bool = True) -> Clip:
    """Decode whatever the provider returned to 44.1 kHz mono wav (trimming
    leading/trailing silence) and measure its length."""
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = Path(tmp, "in.audio"), Path(tmp, "out.wav")
        src.write_bytes(audio_bytes)
        af = ("silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,"
              "areverse,silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse")
        cmd = [ff, "-v", "error", "-y", "-i", str(src), "-ac", "1", "-ar", "44100"]
        if trim_silence:
            cmd += ["-af", af]
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
    """One clip per line (3 requests at a time). Raises NarrationError if any line fails."""
    def one(line: str) -> Clip:
        return to_clip(provider.synthesize(line, voice=voice, style=style))

    with ThreadPoolExecutor(max_workers=3) as pool:
        return list(pool.map(one, lines))
