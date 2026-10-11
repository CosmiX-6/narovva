"""Audition voices: python -m narovva.narration.demo <openai|gemini|elevenlabs> <out_dir> [voice ...]

Reads the provider's API key from the usual env var (OPENAI_API_KEY,
GOOGLE_API_KEY, ELEVENLABS_API_KEY), reads one sample news line in each
voice and in each delivery style, and writes MP3s so you can pick by ear."""

from __future__ import annotations

import os
import sys

import httpx
from pathlib import Path

from .tts import build_provider
from .voices import default_voices, style_for_tone

_KEY_ENV = {"openai": "OPENAI_API_KEY", "gemini": "GOOGLE_API_KEY", "elevenlabs": "ELEVENLABS_API_KEY"}
SAMPLE = (
    "OpenAI just made its models three times cheaper to run. "
    "Here's what changed, and who pays for it. Sixty-seven percent cheaper per token, "
    "and fourteen models updated."
)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) < 2 or args[0] not in _KEY_ENV:
        print(__doc__)
        return 2
    provider_name, out_dir = args[0], Path(args[1])
    voices = args[2:] or default_voices(provider_name)
    if not voices:
        print("no voices: pass ElevenLabs voice ids as arguments")
        return 2
    key = os.environ.get(_KEY_ENV[provider_name], "")
    provider = build_provider(provider_name, key)
    out_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    for voice in voices:
        for tone in ("neutral", "urgent"):
            path = out_dir / f"{provider_name}-{voice}-{tone}.mp3"
            try:
                path.write_bytes(provider.synthesize(SAMPLE, voice=voice, style=style_for_tone(tone)))
                print("wrote", path)
            except Exception as exc:  # keep going: one bad voice shouldn't hide the rest
                failures += 1
                print(f"FAILED {voice}/{tone}: {exc}")
    if failures and provider_name == "gemini":
        try:  # a wrong model name is the usual cause: show what the key can actually use
            r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                          headers={"x-goog-api-key": key}, timeout=30.0)
            names = [m["name"].split("/")[-1] for m in r.json().get("models", []) if "tts" in m["name"].lower()]
            print("Gemini TTS models available to this key:", names or "none found")
        except Exception as exc:
            print("could not list Gemini models:", exc)
    return 1 if failures == len(voices) * 2 else 0


if __name__ == "__main__":
    raise SystemExit(main())
