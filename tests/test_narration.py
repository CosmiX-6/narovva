from __future__ import annotations

import base64
import io
import math
import struct
import sys
import wave

import pytest
from poster_core.models import AssetPlan, AssetType, ContentBrief, DeckSlide, GeneratedAsset, Platform, SlideKind

from narovva.config.schema import BrandKitConfig, ChannelConfig, GenreSetting, NarrationConfig
from narovva.motion.render import _probe_duration
from narovva.narration import (
    NarrationError, build_provider, choose_voice, default_voices, mix_voice_and_music,
    style_for_tone, synthesize_lines, write_script,
)
from narovva.narration import tts as tts_module
from narovva.narration.tts import Clip, to_clip

import narovva.orchestration.run_channel  # noqa: F401

rc = sys.modules["narovva.orchestration.run_channel"]


def _wav(seconds: float, freq: float = 440.0, rate: int = 24000, amp: float = 0.4) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(
            struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate)))
            for i in range(int(seconds * rate))
        ))
    return buf.getvalue()


# -- voices ---------------------------------------------------------------

def test_choose_voice_avoids_recent_and_is_deterministic():
    pool = ["a", "b", "c", "d"]
    assert choose_voice(pool, {"a", "b", "c"}, "x") == "d"
    assert choose_voice(pool, set(), "story-1") == choose_voice(pool, set(), "story-1")
    # all used recently -> still returns something from the pool
    assert choose_voice(pool, set(pool), "x") in pool
    with pytest.raises(ValueError):
        choose_voice([], set(), "x")


def test_voices_vary_across_stories():
    pool = default_voices("openai")
    picks = {choose_voice(pool, set(), f"story-{i}") for i in range(40)}
    assert len(picks) >= 4


def test_style_for_tone_falls_back_to_neutral():
    assert style_for_tone("urgent")[0] != style_for_tone("sombre")[0]
    assert style_for_tone("???") == style_for_tone("neutral")


# -- script ---------------------------------------------------------------

class _LLM:
    def __init__(self, lines=None, boom=False):
        self.lines, self.boom, self.seen = lines, boom, None

    def complete_json(self, system, user):
        self.seen = (system, user)
        if self.boom:
            raise RuntimeError("503 UNAVAILABLE")
        return {"lines": self.lines}


def _brief(tone="neutral"):
    return ContentBrief(key_event="k", summary="Chips got cheaper", headline="Chips", tone=tone, category="ai")


SPECS = [
    {"kind": "hook", "heading": "Chips just got cheaper", "body": "Here is why"},
    {"kind": "stats", "heading": "The numbers", "facts": ["67% cheaper"]},
    {"kind": "cta", "heading": "Follow"},
]


def test_write_script_uses_llm_lines_and_sends_slide_data():
    llm = _LLM(["Hook line?", "Numbers line.", "Follow us."])
    assert write_script(llm, _brief(), SPECS, brand="CU") == ["Hook line?", "Numbers line.", "Follow us."]
    assert "67% cheaper" in llm.seen[1] and "EXACTLY one line per slide" in llm.seen[0]


def test_write_script_replaces_bad_lines_and_survives_llm_failure():
    too_long = " ".join(["word"] * 40)
    out = write_script(_LLM([too_long, "", "ok"]), _brief(), SPECS, brand="Context Unfiltered")
    assert out[0] == "Chips just got cheaper." and out[1] == "The numbers." and out[2] == "ok"
    out = write_script(_LLM(boom=True), _brief(), SPECS, brand="Context Unfiltered")
    assert len(out) == 3 and "Context Unfiltered" in out[2]
    assert len(write_script(_LLM(["only one"]), _brief(), SPECS, brand="CU")) == 3


# -- providers --------------------------------------------------------------

class _Resp:
    def __init__(self, status=200, content=b"", payload=None):
        self.status_code, self.content, self._p, self.text = status, content, payload, str(payload)
        self.headers = {}

    def json(self):
        return self._p


def test_build_provider_validates():
    with pytest.raises(NarrationError):
        build_provider("nope", "key")
    with pytest.raises(NarrationError):
        build_provider("openai", "")


def test_openai_request_shape(monkeypatch):
    seen = {}

    def fake_post(url, **kw):
        seen.update(url=url, **kw)
        return _Resp(content=b"mp3")

    monkeypatch.setattr(tts_module.httpx, "post", fake_post)
    out = build_provider("openai", "sk-test").synthesize("Hello", voice="coral", style=("Be brisk.", "[confident]"))
    assert out == b"mp3" and seen["url"].endswith("/v1/audio/speech")
    assert seen["headers"]["Authorization"] == "Bearer sk-test"
    assert seen["json"]["voice"] == "coral" and seen["json"]["instructions"] == "Be brisk."


def test_elevenlabs_request_shape(monkeypatch):
    seen = {}
    monkeypatch.setattr(tts_module.httpx, "post", lambda url, **kw: (seen.update(url=url, **kw), _Resp(content=b"mp3"))[1])
    build_provider("elevenlabs", "k").synthesize("Hello", voice="VOICEID", style=("x", "[excited]"))
    assert "VOICEID" in seen["url"] and seen["json"]["text"] == "[excited] Hello"
    assert seen["json"]["voice_settings"]["stability"] == 0.0 and seen["headers"]["xi-api-key"] == "k"


def test_gemini_returns_wav_from_pcm(monkeypatch):
    pcm = b"\x00\x01" * 2400
    payload = {"candidates": [{"content": {"parts": [{"inlineData": {"data": base64.b64encode(pcm).decode()}}]}}]}
    monkeypatch.setattr(tts_module.httpx, "post", lambda url, **kw: _Resp(payload=payload))
    wav_bytes = build_provider("gemini", "k").synthesize("Hi", voice="Kore", style=("Brisk", ""))
    with wave.open(io.BytesIO(wav_bytes)) as w:
        assert w.getframerate() == 24000 and w.getnframes() == 2400


def test_tts_http_errors_become_narration_errors(monkeypatch):
    monkeypatch.setattr(tts_module.time, "sleep", lambda s: None)
    monkeypatch.setattr(tts_module.httpx, "post", lambda url, **kw: _Resp(status=401, payload={"error": "bad key"}))
    with pytest.raises(NarrationError, match="401"):
        build_provider("openai", "k").synthesize("x", voice="coral", style=("", ""))
    monkeypatch.setattr(tts_module.httpx, "post", lambda url, **kw: _Resp(status=503))
    with pytest.raises(NarrationError, match="after retries"):
        build_provider("openai", "k").synthesize("x", voice="coral", style=("", ""))


# -- audio ------------------------------------------------------------------

def test_to_clip_measures_and_trims_silence():
    # 0.5 s of silence + 1.0 s tone + 0.5 s silence -> ~1.0 s after trimming
    buf = io.BytesIO()
    rate = 24000
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\x00\x00" * (rate // 2))
        w.writeframes(b"".join(struct.pack("<h", int(13000 * math.sin(2 * math.pi * 300 * i / rate))) for i in range(rate)))
        w.writeframes(b"\x00\x00" * (rate // 2))
    clip = to_clip(buf.getvalue())
    assert 0.8 < clip.seconds < 1.3


def test_to_clip_rejects_silence_and_garbage():
    silent = io.BytesIO()
    with wave.open(silent, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000); w.writeframes(b"\x00\x00" * 24000)
    with pytest.raises(NarrationError):
        to_clip(silent.getvalue())
    with pytest.raises(NarrationError):
        to_clip(b"not audio")


def test_mix_voice_and_music_has_expected_length(tmp_path):
    clips = [to_clip(_wav(1.0, 300)), to_clip(_wav(1.0, 500))]
    music = _wav(2.0, 200, rate=44100)
    mp3 = mix_voice_and_music(clips, [0.25, 2.0], music, total=4.0)
    f = tmp_path / "mix.mp3"
    f.write_bytes(mp3)
    assert _probe_duration(str(f)) == pytest.approx(4.0, abs=0.2)  # music looped/padded to the full reel


# -- run_channel integration --------------------------------------------------

class _FakeProvider:
    def __init__(self):
        self.voices = []

    def synthesize(self, text, *, voice, style):
        self.voices.append(voice)
        return _wav(1.5, 350)


def _channel(**kw):
    base = dict(
        id="c", ig_business_account_id="1", genres=[GenreSetting(genre="tech")],
        brand=BrandKitConfig(name="Context Unfiltered", social_handle="cu", logo_path="assets/logo/CU.png"),
        publish_format="motion_reel", narration=NarrationConfig(provider="openai", voices=["v1", "v2"]),
    )
    base.update(kw)
    return ChannelConfig(**base)


def _asset(n=3):
    slides = [DeckSlide(kind=SlideKind.HOOK, heading="H")] + [DeckSlide(kind=SlideKind.TEXT, heading=f"T{i}") for i in range(n - 1)]
    plan = AssetPlan(asset_type=AssetType.CAROUSEL, platform=Platform.INSTAGRAM_STORY, headline="H", slides=slides)
    return GeneratedAsset(asset_type=AssetType.CAROUSEL, platform=Platform.INSTAGRAM_STORY,
                          paths=[f"/tmp/{i}.png" for i in range(n)], plan=plan)


class _Track:
    id, audio_bytes, attribution = "t", _wav(3.0, 220, rate=44100), "c"


def test_narrated_reel_uses_unused_voice_and_speech_sets_durations(monkeypatch):
    provider = _FakeProvider()
    monkeypatch.setattr(rc, "build_provider", lambda *a, **k: provider)
    monkeypatch.setattr(rc, "resolve_env", lambda name: "key")
    captured = {}

    def fake_render(specs, audio, out, **kw):
        captured.update(specs=specs, audio=audio)
        return out

    monkeypatch.setattr(rc, "render_motion_reel", fake_render)
    llm = _LLM(["One.", "Two.", "Three."])
    path, voice = rc._try_motion_reel(
        _channel(), [_asset(3)], _brief(), _Track(), "/tmp/o.mp4",
        llm=llm, recent_voices={"v1"}, seed="story",
    )
    assert path == "/tmp/o.mp4" and voice == "v2"                     # v1 was used recently
    assert provider.voices == ["v2", "v2", "v2"]
    assert [round(s["duration"], 2) for s in captured["specs"]] == [1.7, 1.7, 1.7]  # 1.5 s voice sped up 1.08x = 1.39 s, + 0.25 lead/tail, floored at 1.7
    assert len(captured["audio"]) > 1000
    # each slide carries its spoken line and how long it takes to say, for the burned-in captions
    assert [s["caption"] for s in captured["specs"]] == ["One.", "Two.", "Three."]
    assert all(s["voice"] == pytest.approx(1.5 / 1.08, abs=0.1) for s in captured["specs"])


def test_captions_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(rc, "build_provider", lambda *a, **k: _FakeProvider())
    monkeypatch.setattr(rc, "resolve_env", lambda name: "key")
    captured = {}
    monkeypatch.setattr(rc, "render_motion_reel", lambda specs, audio, out, **kw: (captured.update(specs=specs), out)[1])
    channel = _channel(narration=NarrationConfig(provider="openai", voices=["v1"], captions=False))
    path, voice = rc._try_motion_reel(channel, [_asset(2)], _brief(), _Track(), "/tmp/o.mp4", llm=_LLM(["One.", "Two."]), seed="s")
    assert voice == "v1" and not any("caption" in s for s in captured["specs"])


def test_narration_failure_degrades_to_music_only(monkeypatch):
    class Boom:
        def synthesize(self, *a, **k):
            raise NarrationError("quota exceeded")

    monkeypatch.setattr(rc, "build_provider", lambda *a, **k: Boom())
    monkeypatch.setattr(rc, "resolve_env", lambda name: "key")
    captured = {}
    monkeypatch.setattr(rc, "render_motion_reel", lambda specs, audio, out, **kw: (captured.update(audio=audio, specs=specs), out)[1])
    track = _Track()
    path, voice = rc._try_motion_reel(_channel(), [_asset(3)], _brief(), track, "/tmp/o.mp4", llm=_LLM(["a", "b", "c"]), seed="s")
    assert path == "/tmp/o.mp4" and voice is None
    assert captured["audio"] == track.audio_bytes                      # untouched music bed
    assert all(1.7 <= s["duration"] <= 3.6 for s in captured["specs"])  # brisk timing restored
    assert not any("caption" in s for s in captured["specs"])           # no voice, so nothing to caption


def test_no_narration_config_means_no_tts(monkeypatch):
    monkeypatch.setattr(rc, "build_provider", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no TTS expected")))
    monkeypatch.setattr(rc, "render_motion_reel", lambda specs, audio, out, **kw: out)
    path, voice = rc._try_motion_reel(_channel(narration=None), [_asset(2)], _brief(), _Track(), "/tmp/o.mp4", llm=_LLM([]))
    assert path == "/tmp/o.mp4" and voice is None


# -- failure handling ---------------------------------------------------------

def test_quota_429_fails_fast_with_the_providers_message(monkeypatch):
    calls = []
    body = {"error": {"message": "You exceeded your current quota", "code": "insufficient_quota"}}
    monkeypatch.setattr(tts_module.httpx, "post", lambda url, **kw: (calls.append(1), _Resp(status=429, payload=body))[1])
    monkeypatch.setattr(tts_module.time, "sleep", lambda s: None)
    with pytest.raises(NarrationError, match="insufficient_quota"):
        build_provider("openai", "k").synthesize("x", voice="coral", style=("", ""))
    assert len(calls) == 1  # retrying a billing problem is pointless


def test_plain_rate_limit_429_retries_then_reports_body(monkeypatch):
    calls = []
    monkeypatch.setattr(tts_module.httpx, "post", lambda url, **kw: (calls.append(1), _Resp(status=429, payload={"error": "slow down"}))[1])
    monkeypatch.setattr(tts_module.time, "sleep", lambda s: None)
    with pytest.raises(NarrationError, match="slow down"):
        build_provider("openai", "k").synthesize("x", voice="coral", style=("", ""))
    assert len(calls) == 3


def test_narration_falls_back_to_the_next_provider(monkeypatch):
    class Boom:
        def synthesize(self, *a, **k):
            raise NarrationError("HTTP 429: insufficient_quota")

    good = _FakeProvider()
    made = []

    def fake_build(name, key, model=None):
        made.append(name)
        return Boom() if name == "openai" else good

    monkeypatch.setattr(rc, "build_provider", fake_build)
    monkeypatch.setattr(rc, "resolve_env", lambda name: "key")
    monkeypatch.setattr(rc, "render_motion_reel", lambda specs, audio, out, **kw: out)
    ch = _channel(narration=NarrationConfig(provider="openai", fallback_providers=["gemini"]))
    path, voice = rc._try_motion_reel(ch, [_asset(3)], _brief(), _Track(), "/tmp/o.mp4", llm=_LLM(["a", "b", "c"]), seed="s")
    assert made == ["openai", "gemini"] and path == "/tmp/o.mp4"
    assert voice in default_voices("gemini") and good.voices          # narrated by the fallback


def test_all_providers_failing_still_posts_music_only(monkeypatch):
    class Boom:
        def synthesize(self, *a, **k):
            raise NarrationError("down")

    monkeypatch.setattr(rc, "build_provider", lambda *a, **k: Boom())
    monkeypatch.setattr(rc, "resolve_env", lambda name: "key")
    monkeypatch.setattr(rc, "render_motion_reel", lambda specs, audio, out, **kw: out)
    ch = _channel(narration=NarrationConfig(provider="openai", fallback_providers=["gemini"]))
    track = _Track()
    path, voice = rc._try_motion_reel(ch, [_asset(3)], _brief(), track, "/tmp/o.mp4", llm=_LLM(["a", "b", "c"]), seed="s")
    assert path == "/tmp/o.mp4" and voice is None


# -- Kokoro (local, keyless) ----------------------------------------------------

def test_kokoro_model_download_is_cached_and_validated(monkeypatch, tmp_path):
    monkeypatch.setenv("NAROVVA_KOKORO_DIR", str(tmp_path))
    fetched = []

    class _Stream:
        def __init__(self, url, **kw):
            fetched.append(url)
            self.big = url.endswith("kokoro-v1.0.onnx")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_bytes(self, n):
            yield b"x" * (300_000_001 if self.big else 20_000_001)

    monkeypatch.setattr(tts_module.httpx, "stream", lambda m, url, **kw: _Stream(url))
    onnx, voices = tts_module.ensure_kokoro_models()
    assert onnx.exists() and voices.exists() and len(fetched) == 2
    tts_module.ensure_kokoro_models()          # second call: cached, no new downloads
    assert len(fetched) == 2


def test_kokoro_rejects_truncated_download(monkeypatch, tmp_path):
    monkeypatch.setenv("NAROVVA_KOKORO_DIR", str(tmp_path))

    class _Short:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def raise_for_status(self): pass
        def iter_bytes(self, n): yield b"tiny"

    monkeypatch.setattr(tts_module.httpx, "stream", lambda m, url, **kw: _Short())
    with pytest.raises(NarrationError, match="too small"):
        tts_module.ensure_kokoro_models()
    assert not list(tmp_path.glob("*.part"))   # no half-written file left behind


def test_kokoro_without_the_extra_installed_is_a_narration_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_kokoro(name, *a, **k):
        if name == "kokoro_onnx":
            raise ImportError("not installed")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_kokoro)
    with pytest.raises(NarrationError, match="narration-local"):
        build_provider("kokoro", "")


def test_kokoro_is_a_valid_config_provider_with_default_voices():
    cfg = NarrationConfig(provider="openai", fallback_providers=["gemini", "kokoro"])
    assert cfg.fallback_providers == ["gemini", "kokoro"] and default_voices("kokoro")


def test_channel_falls_through_to_kokoro_when_keys_are_missing_or_broken(monkeypatch):
    local = _FakeProvider()
    built = []

    def fake_build(name, key, model=None):
        built.append((name, key))
        if name == "kokoro":
            return local
        raise NarrationError(f"no API key for narration provider {name!r}")

    monkeypatch.setattr(rc, "build_provider", fake_build)
    monkeypatch.setattr(rc, "resolve_env", lambda name: None)          # no keys configured at all
    monkeypatch.setattr(rc, "render_motion_reel", lambda specs, audio, out, **kw: out)
    ch = _channel(narration=NarrationConfig(provider="openai", fallback_providers=["gemini", "kokoro"]))
    path, voice = rc._try_motion_reel(ch, [_asset(3)], _brief(), _Track(), "/tmp/o.mp4", llm=_LLM(["a", "b", "c"]), seed="s")
    assert [n for n, _ in built] == ["openai", "gemini", "kokoro"]
    assert voice in default_voices("kokoro") and local.voices


def _kokoro_models_present() -> bool:
    d = tts_module.kokoro_dir()
    return (d / "kokoro-v1.0.onnx").exists() and (d / "voices-v1.0.bin").exists()


@pytest.mark.skipif(not _kokoro_models_present(), reason="Kokoro model files not cached (set NAROVVA_KOKORO_DIR)")
def test_real_kokoro_synthesis_produces_speech():
    provider = build_provider("kokoro", "")
    clips = synthesize_lines(provider, ["Prices cut on every tier.", "Batch jobs now cost half."], voice="af_heart", style=("", ""))
    assert all(1.0 < c.seconds < 6.0 for c in clips)
