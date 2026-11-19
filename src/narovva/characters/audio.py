"""Original procedural music + sound effects + the final mix (no licensed audio needed).

    music(mood, seconds, out, seed)   moods: tech (curious, A minor ~100 bpm), tense (D minor pulses), upbeat (C major ~112), calm (F major pads)
    sfx(name, out)                    whoosh, swish, pop, tick, hit, riser, chime, glitch, type, boom
    mix(voice, out, seconds, events=[(sfx_name, t, gain)], music=wav|None, music_gain)
        -> voice + music ducked under the voice (sidechain) + sound effects, loudness-normalised to -14 LUFS.
All synthesis is numpy/scipy; deterministic for a seed.
"""
from __future__ import annotations

import subprocess
import wave
from pathlib import Path

import numpy as np
from scipy.signal import butter, lfilter

SR = 44100


def _write(path, x):
    x = np.clip(x, -1, 1)
    if x.ndim == 1:
        x = np.stack([x, x], 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())
    return str(path)


def _lp(x, f, order=2):
    b, a = butter(order, min(f, SR / 2 - 100) / (SR / 2), "low")
    return lfilter(b, a, x)


def _hp(x, f, order=2):
    b, a = butter(order, f / (SR / 2), "high")
    return lfilter(b, a, x)


def _bp(x, lo, hi, order=2):
    b, a = butter(order, [lo / (SR / 2), min(hi, SR / 2 - 100) / (SR / 2)], "band")
    return lfilter(b, a, x)


def _env(n, a=0.01, r=0.3, sustain=None):
    t = np.arange(n) / SR
    att = np.clip(t / max(a, 1e-4), 0, 1)
    dec = np.exp(-t / max(r, 1e-4)) if sustain is None else np.ones(n)
    return att * dec


def _note(m):
    return 440.0 * 2 ** ((m - 69) / 12)


# ----------------------------------------------------------------------------- music

MOODS = {
    "tech": {"root": 57, "minor": True, "bpm": 100, "prog": [0, 8, 3, 10], "arp": True, "drums": "soft", "cut": 1800},
    "tense": {"root": 50, "minor": True, "bpm": 92, "prog": [0, 0, 8, 7], "arp": False, "drums": "pulse", "cut": 1200},
    "upbeat": {"root": 60, "minor": False, "bpm": 112, "prog": [0, 7, 9, 5], "arp": True, "drums": "full", "cut": 2600},
    "calm": {"root": 53, "minor": False, "bpm": 76, "prog": [0, 9, 5, 7], "arp": False, "drums": "none", "cut": 1400},
}


def _chord(root, deg, minor):
    third = 3 if minor else 4
    # deg is semitones from the key root; quality follows the scale (good enough for pop progressions)
    q = {0: third, 3: 4, 5: 4 if not minor else 3, 7: 4, 8: 4, 9: 3, 10: 4}.get(deg, third)
    return [root + deg, root + deg + q, root + deg + 7, root + deg + 12]


def music(mood="tech", seconds=60.0, out="music.wav", seed=1):
    M = MOODS.get(mood, MOODS["tech"])
    rng = np.random.default_rng(seed)
    n = int(seconds * SR) + SR
    t = np.arange(n) / SR
    beat = 60 / M["bpm"]
    bar = beat * 4
    mix = np.zeros(n)
    # pads: detuned saws, one chord per bar, low-passed, slow attack/release
    for bi in range(int(seconds / bar) + 2):
        chord = _chord(M["root"], M["prog"][bi % len(M["prog"])], M["minor"])
        s0, s1 = int(bi * bar * SR), min(n, int((bi + 1) * bar * SR + 0.3 * SR))
        if s0 >= n:
            break
        seg = t[: s1 - s0]
        pad = np.zeros(s1 - s0)
        for m in chord:
            for det in (-0.12, 0.0, 0.11):
                f = _note(m - 12 + det)
                pad += 2 * ((seg * f) % 1.0) - 1
        env = np.minimum(1, seg / 0.6) * np.minimum(1, (seg[-1] - seg + 1e-3) / 0.5)
        mix[s0:s1] += _lp(pad, M["cut"]) * env * 0.035
        # bass on the root, pulsing quarter notes
        f = _note(chord[0] - 24)
        for k in range(4):
            q0 = s0 + int(k * beat * SR)
            q1 = min(n, q0 + int(beat * SR))
            if q0 >= n:
                break
            st = np.arange(q1 - q0) / SR
            mix[q0:q1] += np.sin(2 * np.pi * f * st) * _env(q1 - q0, 0.01, beat * 0.8) * (0.16 if M["drums"] != "none" else 0.08)
        # arpeggio plucks on 8ths
        if M["arp"]:
            pattern = [0, 2, 1, 3, 2, 1, 3, 2]
            for k in range(8):
                q0 = s0 + int(k * beat / 2 * SR)
                q1 = min(n, q0 + int(0.4 * SR))
                if q0 >= n:
                    break
                f = _note(chord[pattern[k]] + 12)
                st = np.arange(q1 - q0) / SR
                tone = np.sin(2 * np.pi * f * st) + 0.3 * np.sin(4 * np.pi * f * st)
                mix[q0:q1] += tone * _env(q1 - q0, 0.003, 0.12) * 0.05
    # drums
    if M["drums"] != "none":
        nb = int(seconds / beat) + 2
        for k in range(nb):
            q0 = int(k * beat * SR)
            if q0 >= n:
                break
            if M["drums"] in ("full", "soft", "pulse") and (k % 2 == 0 or M["drums"] == "pulse"):
                q1 = min(n, q0 + int(0.35 * SR))
                st = np.arange(q1 - q0) / SR
                f = 110 * np.exp(-st * 18) + 45
                kick = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(q1 - q0, 0.002, 0.18)
                mix[q0:q1] += kick * (0.32 if M["drums"] == "full" else 0.22)
            if M["drums"] in ("full", "soft"):
                h0 = q0 + int(beat / 2 * SR)
                h1 = min(n, h0 + int(0.06 * SR))
                if h0 < n:
                    hat = _hp(rng.normal(0, 1, h1 - h0), 7000) * _env(h1 - h0, 0.001, 0.025)
                    mix[h0:h1] += hat * (0.05 if M["drums"] == "soft" else 0.08)
            if M["drums"] == "full" and k % 4 == 2:
                q1 = min(n, q0 + int(0.2 * SR))
                snare = _bp(rng.normal(0, 1, q1 - q0), 900, 5000) * _env(q1 - q0, 0.001, 0.08)
                mix[q0:q1] += snare * 0.12
    mix = mix[: int(seconds * SR)]
    fade = np.minimum(1, np.minimum(np.arange(len(mix)) / (0.8 * SR), (len(mix) - np.arange(len(mix))) / (2.0 * SR)))
    mix = mix * fade
    mix = mix / (np.abs(mix).max() + 1e-6) * 0.7
    # gentle stereo width: delay one channel a few ms
    right = np.roll(mix, int(0.012 * SR))
    return _write(out, np.stack([mix, right], 1))


# ----------------------------------------------------------------------------- sound effects


def sfx(name, out, seed=3):
    rng = np.random.default_rng(seed)
    if name in ("whoosh", "swish"):
        d = 0.55 if name == "whoosh" else 0.3
        n = int(d * SR)
        x = rng.normal(0, 1, n)
        st = np.arange(n) / SR
        center = 600 + 3000 * np.sin(np.pi * st / d) ** 2            # band sweeps up and back
        y = np.zeros(n)
        for k in range(0, n, 512):                                     # block-wise moving band-pass
            c = center[k]
            y[k:k + 512] = _bp(x[k:k + 512], max(100, c * 0.5), c * 1.6, 1)
        y *= np.sin(np.pi * st / d) ** 2
        return _write(out, y / (np.abs(y).max() + 1e-6) * (0.5 if name == "whoosh" else 0.35))
    if name == "pop":
        n = int(0.14 * SR)
        st = np.arange(n) / SR
        f = 520 + 900 * (1 - np.exp(-st * 60))
        y = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.002, 0.045)
        return _write(out, y * 0.6)
    if name == "tick":
        n = int(0.04 * SR)
        y = _hp(rng.normal(0, 1, n), 2500) * _env(n, 0.0005, 0.008)
        return _write(out, y * 0.5)
    if name == "type":
        n = int(0.05 * SR)
        y = _bp(rng.normal(0, 1, n), 1500, 6000) * _env(n, 0.0005, 0.012)
        return _write(out, y * 0.4)
    if name in ("hit", "boom"):
        n = int((0.9 if name == "boom" else 0.6) * SR)
        st = np.arange(n) / SR
        f = 120 * np.exp(-st * 9) + 38
        y = np.sin(2 * np.pi * np.cumsum(f) / SR) * _env(n, 0.002, 0.35)
        y += _lp(rng.normal(0, 1, n), 1800) * _env(n, 0.001, 0.05) * 0.5
        return _write(out, y / (np.abs(y).max() + 1e-6) * 0.85)
    if name == "riser":
        d = 1.2
        n = int(d * SR)
        st = np.arange(n) / SR
        x = rng.normal(0, 1, n)
        y = np.zeros(n)
        for k in range(0, n, 512):
            c = 300 + 6000 * (st[k] / d) ** 2
            y[k:k + 512] = _bp(x[k:k + 512], c * 0.6, c * 1.4, 1)
        y += np.sin(2 * np.pi * np.cumsum(200 + 600 * (st / d) ** 2) / SR) * 0.15
        y *= (st / d) ** 2
        return _write(out, y / (np.abs(y).max() + 1e-6) * 0.45)
    if name == "chime":
        n = int(1.4 * SR)
        st = np.arange(n) / SR
        y = sum(np.sin(2 * np.pi * _note(m) * st) * _env(n, 0.003, 0.6) * g for m, g in ((76, 0.5), (83, 0.35), (88, 0.25)))
        return _write(out, y * 0.45)
    if name == "glitch":
        n = int(0.25 * SR)
        y = np.sign(np.sin(2 * np.pi * 220 * np.arange(n) / SR)) * (rng.random(n) > 0.6) * _env(n, 0.001, 0.1)
        return _write(out, _bp(y, 400, 4000) * 0.4)
    raise ValueError(f"unknown sfx {name}")


# ----------------------------------------------------------------------------- final mix


def mix(voice, out, seconds, events=(), music_wav=None, music_gain=0.32, ffmpeg="ffmpeg", workdir=None):
    """voice + ducked music + sound effects -> AAC-ready WAV/M4A at -14 LUFS. events = [(sfx_name, time_s, gain)]."""
    wd = Path(workdir or Path(out).parent)
    cache = {}
    args, fc, labels = ["-i", str(voice)], [f"[0:a]aformat=sample_rates={SR}:channel_layouts=stereo,apad=whole_dur={seconds:.2f}[v]"], []
    idx = 1
    if music_wav:
        args += ["-i", str(music_wav)]
        fc.append(f"[{idx}:a]aformat=sample_rates={SR}:channel_layouts=stereo,volume={music_gain}[mus]")
        fc.append("[v]asplit=2[v1][vk]")
        fc.append("[mus][vk]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350:makeup=1[duck]")
        labels.append("[duck]")
        vlabel = "[v1]"
        idx += 1
    else:
        vlabel = "[v]"
    for k, (name, at, gain) in enumerate(list(events)[:60]):
        if name not in cache:
            cache[name] = sfx(name, wd / f"sfx_{name}.wav")
        args += ["-i", cache[name]]
        ms = max(0, int(at * 1000))
        fc.append(f"[{idx}:a]aformat=sample_rates={SR}:channel_layouts=stereo,volume={gain},adelay={ms}|{ms}[s{k}]")
        labels.append(f"[s{k}]")
        idx += 1
    fc.append(f"{vlabel}{''.join(labels)}amix=inputs={1 + len(labels)}:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]")
    cmd = [ffmpeg, "-y", "-v", "error", *args, "-filter_complex", ";".join(fc), "-map", "[a]", "-t", f"{seconds:.2f}", "-ar", str(SR), str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("mix failed: " + r.stderr[-800:])
    return str(out)


if __name__ == "__main__":
    import sys
    d = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    d.mkdir(parents=True, exist_ok=True)
    for m in MOODS:
        music(m, 16, d / f"music_{m}.wav")
    for s in ("whoosh", "swish", "pop", "tick", "type", "hit", "boom", "riser", "chime", "glitch"):
        sfx(s, d / f"sfx_{s}.wav")
    print("wrote samples to", d)
