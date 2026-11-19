"""Lightweight kinetic-typography + motion-graphics renderer (pure 2D skia; no Blender, no per-shot agents).

    python kinetic.py spec.json out.mp4 [scale] [fps]
spec = {duration, ffmpeg, palette: {bg1, bg2, accent, accent2, fg}, beats: [{start, end, scene, scene_title, step, headline, emph,
        icons: [...], flow: bool, card: {...} | null, display: "roman text", words: [{w, start, end}], final: bool}]}
Everything is a pure function of time t, rendered in parallel chunks (same driver as the DualToon renderer).
"""
import bisect
import json
import math
import os
import subprocess
import sys
from multiprocessing import Pool

import numpy as np
import skia

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from render import (  # noqa: E402
    FB,
    FM,
    FR,
    H,
    R,
    W,
    _free_gb,
    back,
    clamp,
    draw_card,
    eio,
    eo,
    font,
    hexc,
    lerp,
    lin,
    paint,
    rad,
    smooth_path,
    text,
)

PAL = {"bg1": "#070b1f", "bg2": "#1b1050", "accent": "#7c5cff", "accent2": "#22d3ee", "fg": "#ffffff", "warn": "#ff5c7a", "ok": "#34d399"}


# ----------------------------------------------------------------------------- icons (drawn in a 200x200 box centred on 0,0)


def _rr(c, l, t, r, b, rr, p):
    c.drawRRect(skia.RRect.MakeRectXY(R(l, t, r, b), rr, rr), p)


def icon(c, name, P, t):
    a, a2, fg = P["accent"], P["accent2"], P["fg"]
    s = lambda col, alpha=1.0: paint(hexc(col, alpha))
    st = lambda col, w, alpha=1.0: paint(hexc(col, alpha), stroke=w)
    if name in ("laptop", "laptop_pro"):
        pro = name == "laptop_pro"
        body = ["#d9dde6", "#9aa3b5"] if pro else ["#4b5674", "#2c3550"]
        _rr(c, -92, -78, 92, 42, 10, paint(shader=lin((0, -78), (0, 42), [hexc(body[0]), hexc(body[1])])))
        _rr(c, -82, -68, 82, 32, 6, paint(shader=lin((0, -68), (0, 32), [hexc("#1e2a5a"), hexc("#0c1230")])))
        for i in range(4):
            c.drawRect(R(-68, -54 + i * 18, -68 + (40 + (i * 37 + int(t * 20)) % 90), -46 + i * 18), s(a2 if i % 2 else a, 0.8))
        _rr(c, -110, 42, 110, 56, 7, paint(shader=lin((0, 42), (0, 56), [hexc(body[0]), hexc(body[1])])))
        if pro:
            c.drawCircle(0, -10, 150, paint(shader=rad((0, -10), 150, [hexc("#ffffff", 0.18 + 0.06 * math.sin(t * 3)), hexc("#ffffff", 0)])))
    elif name == "chip":
        _rr(c, -60, -60, 60, 60, 12, paint(shader=lin((-60, -60), (60, 60), [hexc("#3a3f55"), hexc("#151827")])))
        _rr(c, -38, -38, 38, 38, 8, paint(shader=lin((-38, -38), (38, 38), [hexc(a), hexc(a2)])))
        for k in range(-3, 4):
            for side in (-1, 1):
                c.drawRect(R(k * 15 - 4, side * 60 - (14 if side < 0 else 0), k * 15 + 4, side * 60 + (14 if side > 0 else 0)), s("#c8cbd8"))
                c.drawRect(R(side * 60 - (14 if side < 0 else 0), k * 15 - 4, side * 60 + (14 if side > 0 else 0), k * 15 + 4), s("#c8cbd8"))
        text(c, "M5", 0, 12, FB, 30, hexc("#ffffff"), "c", shadow=False)
    elif name == "gpu":
        _rr(c, -100, -45, 100, 45, 10, paint(shader=lin((0, -45), (0, 45), [hexc("#2b2f3f"), hexc("#11131c")])))
        for cx in (-48, 48):
            c.drawCircle(cx, 0, 34, s("#0a0c12"))
            c.save(); c.translate(cx, 0); c.rotate(t * 400)
            for k in range(6):
                c.rotate(60)
                c.drawPath(smooth_path([(0, 0), (8, -30), (-6, -28)]), s("#5b6178"))
            c.restore()
        c.drawRect(R(-100, 40, 100, 48), s(a))
        text(c, "RTX", -90, -52, FB, 22, hexc(a2), "l", shadow=False)
    elif name == "desktop_pc":
        _rr(c, -55, -85, 55, 85, 10, paint(shader=lin((0, -85), (0, 85), [hexc("#2e3348"), hexc("#141726")])))
        for i in range(3):
            c.drawCircle(0, -40 + i * 40, 18, st(a if i % 2 else a2, 4, 0.9))
    elif name == "cloud":
        p = skia.Path()
        for cx, cy, r in ((-45, 10, 42), (0, -20, 55), (48, 8, 40), (0, 25, 45)):
            p.addCircle(cx, cy, r)
        c.drawPath(p, paint(shader=lin((0, -75), (0, 70), [hexc("#ffffff"), hexc("#b9c7ff")])))
        c.drawCircle(0, 0, 130, paint(shader=rad((0, 0), 130, [hexc(a2, 0.25), hexc(a2, 0)])))
    elif name == "server":
        for i in range(3):
            _rr(c, -75, -80 + i * 55, 75, -35 + i * 55, 8, paint(shader=lin((0, -80), (0, 80), [hexc("#3a4060"), hexc("#1a1e33")])))
            for j in range(3):
                on = (int(t * 6) + i + j) % 3 != 0
                c.drawCircle(-55 + j * 16, -57 + i * 55, 5, s(PAL["ok"] if on else "#30364d"))
            c.drawRect(R(0, -62 + i * 55, 60, -54 + i * 55), s(a, 0.7))
    elif name == "terminal":
        _rr(c, -100, -75, 100, 75, 12, s("#0b0f1a"))
        c.drawRect(R(-100, -75, 100, -52), s("#1f2638"))
        for k, col in enumerate(("#ff5f57", "#febc2e", "#28c840")):
            c.drawCircle(-84 + k * 16, -63, 5, s(col))
        text(c, "$ ollama run", -86, -22, FM, 19, hexc(PAL["ok"]), "l", shadow=False)
        text(c, "llama3.2:3b", -86, 4, FM, 19, hexc("#e6edf3"), "l", shadow=False)
        if (t * 2) % 1 < 0.6:
            c.drawRect(R(-86, 22, -74, 44), s("#e6edf3"))
    elif name == "code":
        _rr(c, -100, -75, 100, 75, 12, s("#111827"))
        cols = [a, a2, PAL["ok"], "#f59e0b", a]
        for i, col in enumerate(cols):
            ind = (i % 3) * 16
            c.drawRect(R(-80 + ind, -55 + i * 24, -80 + ind + 40 + (i * 29 % 70), -45 + i * 24), s(col, 0.85))
            c.drawRect(R(-80 + ind + 50 + (i * 29 % 70), -55 + i * 24, 60, -45 + i * 24), s("#64748b", 0.6))
    elif name == "chat":
        _rr(c, -95, -70, 40, -10, 18, s(a))
        _rr(c, -40, 5, 95, 65, 18, s("#e2e8f0"))
        for k in range(3):
            c.drawCircle(-5 + k * 22, 35, 6 + 2 * math.sin(t * 8 + k), s("#475569"))
        c.drawRect(R(-75, -48, 15, -40), s("#ffffff", 0.9))
        c.drawRect(R(-75, -32, -10, -24), s("#ffffff", 0.7))
    elif name == "brain":
        p = skia.Path()
        for cx, cy, r in ((-35, -20, 40), (10, -40, 40), (45, -5, 38), (20, 30, 38), (-30, 25, 36)):
            p.addCircle(cx, cy, r)
        c.drawPath(p, paint(shader=lin((-70, -80), (80, 70), [hexc("#f9a8d4"), hexc(a)])))
        for k in range(4):
            c.drawPath(smooth_path([(-50 + k * 25, -50), (-40 + k * 25, -10), (-55 + k * 25, 30)], False), st("#ffffff", 4, 0.35))
    elif name == "tokens":
        words = ["LL", "Ms", " le", "arn", " fa", "st"]
        x = -150
        for i, w in enumerate(words):
            ph = clamp((t * 2.5 - i * 0.25) % 3)
            y = -10 * eo(min(1, ph * 3))
            col = [a, a2, PAL["ok"], "#f59e0b", PAL["warn"], a][i]
            _rr(c, x, -28 + y, x + 46, 28 + y, 8, s(col, 0.9))
            text(c, w.strip(), x + 23, 9 + y, FB, 20, hexc("#0b0f1a"), "c", shadow=False)
            x += 52
    elif name == "network":
        pts = [(-80, -50), (-80, 10), (-80, 70), (0, -20), (0, 40), (80, 10)]
        for i in range(3):
            for j in (3, 4):
                c.drawLine(*pts[i], *pts[j], st("#94a3b8", 2, 0.5))
        for j in (3, 4):
            c.drawLine(*pts[j], *pts[5], st("#94a3b8", 2, 0.5))
        for i, (x, y) in enumerate(pts):
            on = 0.5 + 0.5 * math.sin(t * 5 - x / 40)
            c.drawCircle(x, y, 15, s(a2 if on > 0.5 else a))
        k = (t * 0.8) % 1
        c.drawCircle(lerp(-80, 80, k), lerp(-50, 10, k), 7, s("#ffffff"))
    elif name == "attention":
        toks = ["the", "cat", "sat"]
        for i, w in enumerate(toks):
            _rr(c, -110 + i * 80, 40, -50 + i * 80, 80, 8, s(a, 0.9))
            text(c, w, -80 + i * 80, 68, FB, 20, hexc("#ffffff"), "c", shadow=False)
        for i in range(3):
            for j in range(3):
                wgt = 0.25 + 0.75 * abs(math.sin(t * 1.5 + i * 1.3 + j))
                p = skia.Path()
                p.moveTo(-80 + i * 80, 40)
                p.quadTo((-80 + i * 80 + -80 + j * 80) / 2, -60, -80 + j * 80, 40)
                c.drawPath(p, st(a2, 1 + 5 * wgt, wgt))
    elif name == "doc":
        _rr(c, -60, -80, 60, 80, 10, s("#f8fafc"))
        for i in range(6):
            c.drawRect(R(-42, -55 + i * 20, 42 - (i % 2) * 25, -47 + i * 20), s("#94a3b8"))
        c.drawRect(R(-42, -55, 10, -47), s(a))
    elif name == "search":
        c.drawCircle(-15, -15, 45, st(fg, 14))
        c.drawLine(18, 18, 65, 65, paint(hexc(fg), stroke=18))
    elif name == "agent":
        _rr(c, -60, -55, 60, 45, 22, paint(shader=lin((0, -55), (0, 45), [hexc("#e2e8f0"), hexc("#94a3b8")])))
        for sx in (-1, 1):
            c.drawCircle(sx * 25, -10, 12, s(a2 if (t * 1.5) % 1 > 0.1 else "#0b0f1a"))
        c.drawLine(0, -55, 0, -80, st("#e2e8f0", 5))
        c.drawCircle(0, -86, 9, s(PAL["warn"]))
        c.drawRect(R(-25, 18, 25, 26), s("#0b0f1a"))
    elif name == "gear":
        c.save(); c.rotate(t * 60)
        for k in range(8):
            c.rotate(45)
            c.drawRect(R(-12, -72, 12, -50), s("#cbd5e1"))
        c.drawCircle(0, 0, 55, s("#cbd5e1"))
        c.drawCircle(0, 0, 22, s("#0b0f1a"))
        c.restore()
    elif name in ("check", "cross"):
        col = PAL["ok"] if name == "check" else PAL["warn"]
        c.drawCircle(0, 0, 70, s(col))
        if name == "check":
            c.drawPath(smooth_path([(-32, 2), (-8, 26), (36, -22)], False), paint(hexc("#ffffff"), stroke=16))
        else:
            c.drawLine(-28, -28, 28, 28, paint(hexc("#ffffff"), stroke=16))
            c.drawLine(28, -28, -28, 28, paint(hexc("#ffffff"), stroke=16))
    elif name == "question":
        c.drawCircle(0, 0, 70, s(a))
        text(c, "?", 0, 30, FB, 96, hexc("#ffffff"), "c", shadow=False)
    elif name == "money":
        for i in range(3):
            _rr(c, -80 + i * 6, -45 - i * 10, 80 + i * 6, 35 - i * 10, 8, s("#16a34a", 1 - i * 0.2))
        text(c, "$", 0, 10, FB, 60, hexc("#ffffff"), "c", shadow=False)
    elif name == "python":
        _rr(c, -70, -70, 70, 70, 20, paint(shader=lin((-70, -70), (70, 70), [hexc("#3776ab"), hexc("#ffd43b")])))
        text(c, "Py", 0, 22, FB, 64, hexc("#ffffff"), "c", shadow=False)
    elif name == "cluster":
        for i in range(3):
            for j in range(2):
                c.save(); c.translate(-70 + i * 70, -35 + j * 70); c.scale(0.38, 0.38); icon(c, "server", P, t + i); c.restore()
    elif name == "rocket":
        c.save(); c.translate(0, math.sin(t * 6) * 4)
        c.drawPath(smooth_path([(0, -90), (30, -30), (30, 40), (-30, 40), (-30, -30)]), s("#e2e8f0"))
        c.drawCircle(0, -20, 15, s(a2))
        for sx in (-1, 1):
            c.drawPath(smooth_path([(sx * 30, 10), (sx * 55, 50), (sx * 30, 40)]), s(PAL["warn"]))
        c.drawPath(smooth_path([(-18, 42), (0, 90 + 10 * math.sin(t * 20)), (18, 42)]), s("#f59e0b"))
        c.restore()
    elif name == "lightbulb":
        c.drawCircle(0, -20, 110, paint(shader=rad((0, -20), 110, [hexc("#fde68a", 0.4), hexc("#fde68a", 0)])))
        c.drawCircle(0, -20, 55, s("#fde047"))
        c.drawRect(R(-25, 30, 25, 60), s("#94a3b8"))
    elif name == "hourglass":
        c.drawPath(smooth_path([(-45, -70), (45, -70), (8, 0), (45, 70), (-45, 70), (-8, 0)]), st("#e2e8f0", 6))
        k = (t * 0.3) % 1
        c.drawPath(smooth_path([(-35 * (1 - k), -60 + 60 * k), (35 * (1 - k), -60 + 60 * k), (0, -5)]), s("#f59e0b"))
        c.drawPath(smooth_path([(-35 * k, 60 - 50 * k), (35 * k, 60 - 50 * k), (40, 62), (-40, 62)]), s("#f59e0b"))
    elif name == "person":
        c.drawCircle(0, -45, 32, s("#fcd5b5"))
        c.drawPath(smooth_path([(-55, 70), (-50, 0), (0, -10), (50, 0), (55, 70)]), s(a))
    elif name == "layers":
        for i in range(3):
            y = 30 - i * 30 - 6 * math.sin(t * 3 + i)
            p = skia.Path()
            p.moveTo(0, y - 30); p.lineTo(80, y); p.lineTo(0, y + 30); p.lineTo(-80, y); p.close()
            c.drawPath(p, s([a, a2, PAL["ok"]][i], 0.9))
    else:  # unknown -> keyword dot
        c.drawCircle(0, 0, 60, s(a, 0.8))


ICONS = ["laptop", "laptop_pro", "chip", "gpu", "desktop_pc", "cloud", "server", "terminal", "code", "chat", "brain", "tokens", "network",
         "attention", "doc", "search", "agent", "gear", "check", "cross", "question", "money", "python", "cluster", "rocket", "lightbulb",
         "hourglass", "person", "layers"]


# ----------------------------------------------------------------------------- frame


class Kinetic:
    def __init__(self, spec, scale):
        self.spec, self.scale = spec, scale
        self.P = {**PAL, **(spec.get("palette") or {})}
        self.beats = spec["beats"]
        self.starts = [b["start"] for b in self.beats]
        self.surface = skia.Surface(int(W * scale), int(H * scale))
        rng = np.random.default_rng(3)
        self.parts = [(rng.uniform(0, W), rng.uniform(0, H), rng.uniform(1, 3), rng.uniform(0, 6.3)) for _ in range(70)]

    def bg(self, c, t, bi):
        P = self.P
        c.drawRect(R(0, 0, W, H), paint(shader=lin((0, 0), (W * 0.3, H), [hexc(P["bg1"]), hexc(P["bg2"])])))
        for k, (cx, cy, r, col) in enumerate(((150, 300, 380, P["accent"]), (600, 950, 420, P["accent2"]), (300, 1200, 300, P["accent"]))):
            x = cx + math.sin(t * 0.3 + k) * 60
            y = cy + math.cos(t * 0.25 + k * 2) * 50
            c.drawCircle(x, y, r, paint(shader=rad((x, y), r, [hexc(col, 0.22), hexc(col, 0)])))
        gp = paint(hexc("#ffffff", 0.035), stroke=1)
        off = (t * 12) % 60
        for x in range(0, W + 60, 60):
            c.drawLine(x - off, 0, x - off, H, gp)
        for y in range(0, H + 60, 60):
            c.drawLine(0, y + off, W, y + off, gp)
        for x, y, r, ph in self.parts:
            c.drawCircle((x + math.sin(t * 0.5 + ph) * 20) % W, (y - t * 18 * r) % H, r, paint(hexc("#ffffff", 0.25)))

    def render(self, t):
        c = self.surface.getCanvas()
        c.save()
        c.scale(self.scale, self.scale)
        bi = max(0, bisect.bisect_right(self.starts, t) - 1)
        b = self.beats[bi]
        P = self.P
        age = t - b["start"]
        self.bg(c, t, bi)
        # progress + scene tag
        c.drawRect(R(0, 0, W * clamp(t / self.spec["duration"]), 6), paint(hexc(P["accent2"])))
        if b.get("scene_title") and not b.get("final"):
            tag = (f"STEP {b['step']} · " if b.get("step") else "") + b["scene_title"].upper()
            f = font(FB, 22)
            w_ = f.measureText(tag) + 36
            _rr(c, 36, 48, 36 + w_, 92, 22, paint(hexc("#ffffff", 0.08)))
            c.drawCircle(56, 70, 6, paint(hexc(P["accent2"])))
            text(c, tag, 70, 78, FB, 22, hexc("#dbe4ff"), "l", shadow=False)
        if b.get("final"):
            self.final(c, b, age)
        else:
            top = 140
            if b.get("card"):
                top = draw_card(c, b["card"], age - 0.15, 1.0) + 30 if age > 0.15 else 140
            self.icons(c, b, age, t, top)
            self.headline(c, b, age)
            self.captions(c, b, t)
        # scene wipe on a new scene
        if bi > 0 and b["scene"] != self.beats[bi - 1]["scene"] and age < 0.32:
            k = age / 0.32
            x = lerp(-W, W, eio(k))
            c.drawRect(R(x, 0, x + W, H), paint(shader=lin((x, 0), (x + W, 0), [hexc(P["accent"]), hexc(P["accent2"])])))
        c.drawRect(R(0, 0, W, H), paint(shader=rad((W / 2, H / 2), H * 0.8, [hexc("#000000", 0), hexc("#000000", 0), hexc("#000000", 0.5)], [0, 0.6, 1])))
        c.restore()
        return self.surface.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)

    def icons(self, c, b, age, t, top):
        ics = [i for i in (b.get("icons") or []) if i][:3]
        if not ics:
            return
        n = len(ics)
        cy = max(top + 190, 560) if b.get("card") else 560
        sz = 1.45 if n == 1 else (1.15 if n == 2 else 0.95)
        if b.get("card"):
            sz *= 0.75
        xs = [W / 2] if n == 1 else [lerp(170, W - 170, i / (n - 1)) for i in range(n)]
        if b.get("flow") and n > 1:
            for i in range(n - 1):
                x0, x1 = xs[i] + 80 * sz, xs[i + 1] - 80 * sz
                k = clamp((age - 0.3 - i * 0.15) / 0.35)
                c.drawLine(x0, cy, lerp(x0, x1, eo(k)), cy, paint(hexc(self.P["fg"], 0.35), stroke=4))
                if k >= 1:
                    for j in range(3):
                        q = ((t * 0.9 + j / 3) % 1)
                        c.drawCircle(lerp(x0, x1, q), cy, 7, paint(hexc(self.P["accent2"])))
                    c.drawPath(smooth_path([(x1 - 4, cy - 12), (x1 + 12, cy), (x1 - 4, cy + 12)]), paint(hexc(self.P["fg"], 0.6)))
        for i, (name, x) in enumerate(zip(ics, xs)):
            k = clamp((age - i * 0.12) / 0.45)
            if k <= 0:
                continue
            pop = back(k)
            c.save()
            c.translate(x, cy + math.sin(t * 1.6 + i) * 6)
            c.scale(sz * pop, sz * pop)
            c.drawOval(R(-90, 100, 90, 118), paint(hexc("#000000", 0.25), blur=8))
            icon(c, name, self.P, t)
            c.restore()

    def headline(self, c, b, age):
        hl = (b.get("headline") or "").strip()
        if not hl:
            return
        words = hl.split()
        emph = {e.lower().strip(".,!?") for e in str(b.get("emph") or "").split()}
        size = 66 if len(hl) < 18 else (56 if len(hl) < 28 else 46)
        f = font(FB, size)
        lines, cur = [], []
        for w in words:
            if f.measureText(" ".join(cur + [w])) > W - 90 and cur:
                lines.append(cur)
                cur = [w]
            else:
                cur.append(w)
        lines.append(cur)
        y0 = 860
        idx = 0
        for li, ln in enumerate(lines):
            widths = [f.measureText(w + " ") for w in ln]
            x = (W - sum(widths)) / 2
            for w, wd in zip(ln, widths):
                k = clamp((age - 0.08 * idx) / 0.3)
                if k > 0:
                    is_e = w.lower().strip(".,!?") in emph
                    sc = back(k) * (1.12 if is_e else 1.0)
                    c.save()
                    c.translate(x + wd / 2, y0 + li * (size * 1.15))
                    c.scale(sc, sc)
                    col = hexc(self.P["accent2"] if is_e else self.P["fg"], k)
                    if is_e:
                        c.drawRRect(skia.RRect.MakeRectXY(R(-wd / 2 - 6, -size * 0.82, wd / 2 - 6, size * 0.25), 10, 10), paint(hexc(self.P["accent"], 0.35 * k)))
                    text(c, w, -wd / 2, 0, FB, size, col, "l", shadow=True)
                    c.restore()
                x += wd
                idx += 1

    def captions(self, c, b, t):
        words = b.get("words") or []
        if not words:
            return
        f = font(FB, 34)
        k = max([i for i, w in enumerate(words) if w["start"] <= t] or [0])
        g = k // 6
        chunk = words[g * 6:(g + 1) * 6]
        txt = " ".join(w["w"] for w in chunk)
        tw = f.measureText(txt)
        y = 1150
        _rr(c, (W - tw) / 2 - 20, y - 40, (W + tw) / 2 + 20, y + 16, 16, paint(hexc("#000000", 0.45)))
        x = (W - tw) / 2
        for w in chunk:
            wd = f.measureText(w["w"] + " ")
            on = w["start"] <= t
            text(c, w["w"], x, y, FB, 34, hexc(self.P["accent2"] if on and w is words[k] else "#ffffff", 1.0 if on else 0.55), "l", shadow=False)
            x += wd

    def final(self, c, b, age):
        P = self.P
        lines = [ln.strip() for ln in (b.get("headline") or "").replace(". ", ".\n").split("\n") if ln.strip()]
        for i, ln in enumerate(lines):
            k = clamp((age - i * 0.45) / 0.5)
            if k <= 0:
                continue
            sc = back(k)
            c.save()
            c.translate(W / 2, 560 + i * 120)
            c.scale(sc, sc)
            c.drawCircle(0, -30, 260, paint(shader=rad((0, -30), 260, [hexc(P["accent"] if i else P["accent2"], 0.25 * k), hexc(P["accent"], 0)])))
            text(c, ln, 0, 0, FB, 86 if len(ln) < 14 else 70, hexc(P["accent2"] if i else P["fg"], k), "c", shadow=True)
            c.restore()
        if b.get("display") and age > 0.2:
            text(c, b["display"], W / 2, 900, FR, 30, hexc("#dbe4ff", clamp((age - 0.2) / 0.4)), "c", shadow=False, maxw=W - 80)


def render_chunk(args):
    spec, scale, fps, a, b, out, ff = args
    fr = Kinetic(spec, scale)
    w, h = int(W * scale), int(H * scale)
    p = subprocess.Popen([ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
                          "-c:v", "libx264", "-preset", "medium", "-tune", "animation", "-crf", "16", "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
    for n in range(a, b):
        p.stdin.write(np.ascontiguousarray(fr.render(n / fps)).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("encoder failed")
    return out


def main():
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    out = os.path.abspath(sys.argv[2])
    scale = float(sys.argv[3]) if len(sys.argv) > 3 else 1.5
    fps = int(sys.argv[4]) if len(sys.argv) > 4 else 30
    ff = spec.get("ffmpeg", "ffmpeg")
    if spec.get("only_frame") is not None:
        from PIL import Image
        Image.fromarray(Kinetic(spec, scale).render(spec["only_frame"])[..., :3]).save(out)
        return
    total = int(math.ceil(spec["duration"] * fps))
    workers = min(os.cpu_count() or 4, 12, max(2, int(_free_gb() / 0.5)))
    nch = min(workers * 2, max(1, total // 30))
    edges = [round(i * total / nch) for i in range(nch + 1)]
    tmp = os.path.splitext(out)[0]
    jobs = [(spec, scale, fps, edges[i], edges[i + 1], f"{tmp}_k{i:02d}.mp4", ff) for i in range(nch)]
    with Pool(workers) as pool:
        parts = pool.map(render_chunk, jobs)
    lst = f"{tmp}_parts.txt"
    open(lst, "w").write("".join(f"file '{os.path.basename(p)}'\n" for p in parts))
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out], check=True, cwd=os.path.dirname(out))
    for p in parts + [lst]:
        os.remove(p)


if __name__ == "__main__":
    main()
