"""Character-reel renderer (vendored from the content studio): sprite puppets on a Blender-rendered set plate, cards, b-roll, captions.

Originally the DualToon campfire renderer; stage mode (spec["stage"]) is what narovva uses.

Runs under the models venv (needs skia-python + numpy):  python render.py spec.json out.mp4 [scale] [fps]
Everything is a pure function of time t, so frames render in parallel chunks and are stitched with ffmpeg.
Spec (JSON): {duration, ffmpeg, turns:[{start,end,speaker,text,words,emotion,shot,move,gesture,card}], amp:{host:[..],mascot:[..]}, amp_hz}
"""
import bisect
import json
import math
import os
import random
import subprocess
import sys
from multiprocessing import Pool

import numpy as np
import skia

W, H = 720, 1280
_FONTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
FB, FR = os.path.join(_FONTS, "Inter-Bold.ttf"), os.path.join(_FONTS, "Inter-Medium.ttf")   # brand fonts (OFL), any OS
FM = os.path.join(_FONTS, "JetBrainsMono-Bold.ttf")

# ----------------------------------------------------------------------------- tiny helpers


def hexc(h, a=1.0):
    h = h.lstrip("#")
    return skia.Color(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), int(255 * max(0, min(1, a))))


def lerp(a, b, k):
    return a + (b - a) * k


def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def eo(k):  # ease-out cubic
    k = clamp(k)
    return 1 - (1 - k) ** 3


def eio(k):
    k = clamp(k)
    return 3 * k * k - 2 * k ** 3


def back(k):  # overshoot pop
    k = clamp(k)
    c = 1.70158
    return 1 + (c + 1) * (k - 1) ** 3 + c * (k - 1) ** 2


_fonts = {}


def font(path, size):
    key = (path, round(size, 1))
    if key not in _fonts:
        _fonts[key] = skia.Font(skia.Typeface.MakeFromFile(path), size)
    return _fonts[key]


def paint(color=None, stroke=0, shader=None, blur=0, mode=None, cap=True):
    p = skia.Paint(AntiAlias=True)
    if color is not None:
        p.setColor(color)
    if stroke:
        p.setStyle(skia.Paint.kStroke_Style)
        p.setStrokeWidth(stroke)
        if cap:
            p.setStrokeCap(skia.Paint.kRound_Cap)
            p.setStrokeJoin(skia.Paint.kRound_Join)
    if shader is not None:
        p.setShader(shader)
    if blur:
        p.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, blur))
    if mode is not None:
        p.setBlendMode(mode)
    return p


def lin(p0, p1, cols, pos=None):
    return skia.GradientShader.MakeLinear([p0, p1], cols, pos)


def rad(c, r, cols, pos=None):
    return skia.GradientShader.MakeRadial(c, r, cols, pos)


def R(l, t, r, b):
    return skia.Rect.MakeLTRB(l, t, r, b)


def smooth_path(pts, closed=True):
    """Closed smooth curve through points using quad curves via midpoints."""
    p = skia.Path()
    n = len(pts)
    mid = lambda a, b: ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    start = mid(pts[-1], pts[0]) if closed else pts[0]
    p.moveTo(*start)
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        if not closed and i == n - 1:
            p.lineTo(*a)
            break
        m = mid(a, b)
        p.quadTo(a[0], a[1], m[0], m[1])
    if closed:
        p.close()
    return p


def text(c, s, x, y, path, size, color, align="l", shadow=True, maxw=None):
    f = font(path, size)
    if maxw:
        while f.measureText(s) > maxw and size > 12:
            size -= 1
            f = font(path, size)
    w = f.measureText(s)
    if align == "r":
        x -= w
    elif align == "c":
        x -= w / 2
    if shadow:
        c.drawString(s, x + 2, y + 3, f, paint(hexc("#000000", 0.55), blur=1.5))
    c.drawString(s, x, y, f, paint(color))
    return w


# ----------------------------------------------------------------------------- world

SHOTS = {  # (cx, cy, zoom) in world coords; subjects sit low in frame so the card + captions have room above
    "wide": (360, 700, 1.12), "two": (385, 850, 1.5), "host": (240, 800, 2.0), "host_close": (238, 740, 3.0),
    "mascot": (520, 900, 2.5), "mascot_close": (520, 885, 3.3), "fire": (385, 960, 1.7),
}
HOST_POS, MASC_POS, FIRE = (235, 1015), (525, 1020), (388, 1118)
_rng = random.Random(11)
STARS = [(_rng.uniform(-120, 840), _rng.uniform(-200, 700), _rng.uniform(0.8, 2.1), _rng.uniform(0, 6.3)) for _ in range(110)]
TREES_FAR = [(x + _rng.uniform(-14, 14), _rng.uniform(150, 250), _rng.uniform(0, 6)) for x in range(-100, 860, 52)]
TREES_MID = [(x + _rng.uniform(-20, 20), _rng.uniform(210, 330), _rng.uniform(0, 6)) for x in range(-110, 880, 74)]
SNOW_FAR = [(_rng.uniform(0, W), _rng.uniform(0, H), _rng.uniform(1.2, 2.4), _rng.uniform(0, 6.3)) for _ in range(110)]
SNOW_NEAR = [(_rng.uniform(0, W), _rng.uniform(0, H), _rng.uniform(3, 5.5), _rng.uniform(0, 6.3)) for _ in range(34)]


def pine(c, x, base, h, color, sway, cap=True):
    w = h * 0.34
    for k in range(3):
        yb = base - k * h * 0.27
        apex = yb - h * 0.46
        bw = w * (1 - k * 0.24)
        p = skia.Path()
        p.moveTo(x + sway * (k + 1) * 0.3, apex)
        p.lineTo(x + bw, yb)
        p.lineTo(x - bw, yb)
        p.close()
        c.drawPath(p, paint(color))
        if cap:
            q = skia.Path()
            q.moveTo(x + sway * (k + 1) * 0.3, apex)
            cf = 0.45 if k == 2 else 0.3      # lower caps end above the next tier's base (no sliver streaks)
            q.lineTo(x + bw * 0.42 * cf / 0.45, apex + (yb - apex) * cf)
            q.lineTo(x - bw * 0.42 * cf / 0.45, apex + (yb - apex) * cf)
            q.close()
            c.drawPath(q, paint(hexc("#9db8ee", 0.16)))
    c.drawRect(R(x - 5, base, x + 5, base + 14), paint(color))


def tent(c, cx, base, w, h, t, ph):
    fl = 0.85 + 0.15 * math.sin(t * 7 + ph) + 0.05 * math.sin(t * 13 + ph * 2)
    c.drawCircle(cx, base - h * 0.35, h * 1.5, paint(shader=rad((cx, base - h * 0.35), h * 1.5, [hexc("#ff9a3a", 0.5 * fl), hexc("#ff9a3a", 0)])))
    p = skia.Path()
    p.moveTo(cx, base - h)
    p.lineTo(cx + w / 2, base)
    p.lineTo(cx - w / 2, base)
    p.close()
    c.drawPath(p, paint(shader=lin((cx, base - h), (cx, base), [hexc("#ffb25a"), hexc("#d2601f")])))
    d = skia.Path()
    d.moveTo(cx, base - h * 0.62)
    d.lineTo(cx + w * 0.17, base)
    d.lineTo(cx - w * 0.17, base)
    d.close()
    c.drawPath(d, paint(hexc("#ffe0a0", 0.9 * fl)))
    c.drawPath(p, paint(hexc("#5a1f0e", 0.25), stroke=2))


def world(c, t, flick):
    # sky
    c.drawRect(R(-700, -700, 1420, 900), paint(shader=lin((0, -200), (0, 890), [hexc("#030716"), hexc("#12204a"), hexc("#3a3a72")], [0, 0.68, 1])))
    for x, y, r, ph in STARS:
        c.drawCircle(x, y, r, paint(hexc("#dfe8ff", 0.45 + 0.4 * math.sin(t * (1 + r) + ph))))
    # moon
    c.drawCircle(545, 205, 190, paint(shader=rad((545, 205), 190, [hexc("#c9d8ff", 0.28), hexc("#c9d8ff", 0)])))
    c.drawCircle(545, 205, 62, paint(hexc("#fff4cf")))
    for cx, cy, r in ((528, 192, 12), (563, 222, 9), (552, 180, 6)):
        c.drawCircle(cx, cy, r, paint(hexc("#e8d9a8", 0.55)))
    # far / mid forest
    for x, h, ph in TREES_FAR:
        pine(c, x, 905, h, hexc("#0b1536"), math.sin(t * 0.6 + ph) * 3, cap=False)
    tent(c, 98, 915, 150, 112, t, 0.5)
    tent(c, 648, 905, 128, 96, t, 2.1)
    for x, h, ph in TREES_MID:
        pine(c, x, 930, h, hexc("#08102a"), math.sin(t * 0.7 + ph) * 4)
    # ground
    g = skia.Path()
    g.moveTo(-700, 2200)
    g.lineTo(-700, 900)
    g.quadTo(360, 850, 1420, 900)
    g.lineTo(1420, 2200)
    g.close()
    c.drawPath(g, paint(shader=lin((0, 880), (0, 1500), [hexc("#2c3d78"), hexc("#16214a"), hexc("#0a1130")], [0, 0.45, 1])))
    # log
    c.drawRRect(skia.RRect.MakeRectXY(R(110, 1008, 660, 1072), 30, 30), paint(shader=lin((0, 1008), (0, 1072), [hexc("#8a5a3a"), hexc("#4a2e22")])))
    c.drawOval(R(100, 1008, 150, 1072), paint(hexc("#b88458")))
    c.drawOval(R(112, 1020, 138, 1060), paint(hexc("#8a5a3a"), stroke=3))
    c.drawOval(R(118, 1028, 132, 1052), paint(hexc("#8a5a3a"), stroke=2))


# ----------------------------------------------------------------------------- characters

HOST_EXP = {
    "neutral": (0, 0.0, 0.25, 1.0), "curious": (-7, 0.18, 0.15, 1.12), "explain": (-3, 0.0, 0.55, 1.0), "laugh": (-6, -0.1, 1.0, 0.45),
    "wow": (-12, 0.0, 0.1, 1.3), "deadpan": (3, 0.0, 0.0, 0.72), "shrug": (-4, -0.16, 0.2, 1.0), "proud": (-4, 0.0, 0.8, 0.85),
}
MASC_EXP = {  # eyelid(0..1 closed from top), brow tilt, mouth: flat|smile|O|wavy, eye scale
    "neutral": (0.15, 0, "flat", 1.0), "deadpan": (0.45, 0, "flat", 0.95), "shock": (0, 0.0, "O", 1.35), "happy": (0, 0, "smile", 1.0),
    "confused": (0.1, 0.5, "wavy", 1.0), "proud": (0.25, 0, "smile", 1.0), "sleepy": (0.65, 0, "flat", 0.9),
}
SKIN, SKIN2, JACKET, HAIR = "#f1c39a", "#d9a174", "#2f58d1", "#1c1822"


def blink(t, off):
    ph = (t + off) % 3.6
    return 1.0 if ph > 0.16 else max(0.06, abs(ph - 0.08) / 0.08)


def hand_targets(g, gp, t, typing):
    """Hand positions (local to hip origin) for left/right for each gesture; blended by gp."""
    jit = math.sin(t * 22) * 4, math.sin(t * 17 + 1) * 4
    base = [(-48 + (jit[0] if typing else 0), -62), (48 + (jit[1] if typing else 0), -62)]
    if g == "shrug":
        tgt = [(-105, -158), (105, -158)]
    elif g == "point":
        tgt = [base[0], (-150 + math.sin(t * 5) * 6, -250)]
    elif g == "wave":
        tgt = [base[0], (112 + math.sin(t * 9) * 20, -230)]
    else:
        return base
    return [(lerp(base[i][0], tgt[i][0], gp), lerp(base[i][1], tgt[i][1], gp)) for i in range(2)]


def draw_host(c, t, st):
    amp, gest, gp = st["amp"], st["gesture"], st["gp"]
    brow, tilt, smile, eyes = st["exp"]
    bob = math.sin(t * 1.7) * 2 + (amp * 3 if st["speaking"] else 0)
    c.save()
    c.translate(HOST_POS[0], HOST_POS[1] + bob * 0.4)
    # legs
    for sx in (-1, 1):
        c.drawRRect(skia.RRect.MakeRectXY(R(sx * 38 - 24, 8, sx * 38 + 24, 78), 14, 14), paint(hexc("#222c4a")))
        c.drawOval(R(sx * 38 - 30, 66, sx * 38 + 30, 92), paint(hexc("#3a2418")))
    # torso
    body = smooth_path([(-74, -150), (0, -166), (74, -150), (66, -30), (58, 8), (-58, 8), (-66, -30)])
    c.drawPath(body, paint(shader=lin((-74, 0), (74, 0), [hexc("#203f9c"), hexc(JACKET), hexc("#5b86f0")])))
    c.drawPath(smooth_path([(-22, -163), (0, -122), (22, -163), (0, -168)]), paint(hexc("#e9edf7")))
    c.drawLine(0, -122, 0, 6, paint(hexc("#1a2f78", 0.7), stroke=3))
    # hands / arms (behind laptop)
    shs = [(-70, -136), (70, -136)]
    hands = hand_targets(gest, gp, t, st["typing"])
    for (sx, sy), (hx, hy) in zip(shs, hands):
        p = skia.Path()
        p.moveTo(sx, sy)
        p.quadTo(sx + (sx / abs(sx)) * 46, (sy + hy) / 2 + 20, hx, hy)
        c.drawPath(p, paint(hexc(JACKET), stroke=34))
        c.drawCircle(hx, hy, 15, paint(hexc(SKIN)))
    # laptop (lid faces camera)
    lid = R(-64, -92, 64, -20)
    c.drawRRect(skia.RRect.MakeRectXY(lid, 8, 8), paint(shader=lin((0, -92), (0, -20), [hexc("#aab3c6"), hexc("#7b869c")])))
    c.drawCircle(0, -56, 9, paint(hexc("#ffffff", 0.75 + 0.15 * math.sin(t * 2))))
    c.drawRRect(skia.RRect.MakeRectXY(R(-72, -22, 72, -14), 4, 4), paint(hexc("#5f6a80")))
    # neck + head
    c.drawRect(R(-18, -192, 18, -150), paint(hexc(SKIN2)))
    c.save()
    c.translate(0, -166)
    c.rotate(math.sin(t * 1.1) * 1.2 + (amp * 2.2 * math.sin(t * 9) if st["speaking"] else 0) + st["look"] * 3)
    c.translate(0, -58)
    for sx in (-1, 1):
        c.drawOval(R(sx * 56 - 10, -10, sx * 56 + 10, 20), paint(hexc(SKIN2)))
    c.drawOval(R(-56, -64, 56, 62), paint(shader=lin((-56, 0), (56, 0), [hexc(SKIN2), hexc(SKIN), hexc("#ffd9b6")])))
    hair = skia.Path()
    hair.moveTo(-60, -6)
    hair.cubicTo(-74, -92, 74, -92, 60, -6)
    hair.quadTo(52, -34, 36, -40)
    hair.quadTo(4, -62, -34, -36)
    hair.quadTo(-52, -30, -60, -6)
    c.drawPath(hair, paint(hexc(HAIR)))
    c.drawPath(smooth_path([(-30, -78), (-6, -92), (24, -84), (10, -70)]), paint(hexc(HAIR)))
    c.drawArc(R(-40, -70, 30, -30), 200, 80, False, paint(hexc("#4a4458", 0.7), stroke=3))
    bl = blink(t, 0.4) * eyes
    gx = st["look"] * 5
    for sx in (-1, 1):
        ex = sx * 23
        c.drawOval(R(ex - 13, -2 - 15 * bl, ex + 13, -2 + 15 * bl), paint(hexc("#ffffff")))
        c.drawCircle(ex + gx, -2, 7.5 * min(1, bl + 0.15), paint(hexc("#2a1c14")))
        c.drawCircle(ex + gx + 2.5, -5, 2.4, paint(hexc("#ffffff")))
        c.drawCircle(ex, -2, 25, paint(hexc("#ffffff", 0.10)))
        c.drawCircle(ex, -2, 25, paint(hexc("#15151f"), stroke=4.5))
        c.save()
        c.translate(ex, -38 + brow)
        c.rotate(math.degrees(tilt) * sx * -1)
        c.drawLine(-12, 0, 12, 0, paint(hexc(HAIR), stroke=5.5))
        c.restore()
    c.drawLine(-2, -2, 2, -2, paint(hexc("#15151f"), stroke=4.5))
    c.drawLine(-2, -2, -10, -2, paint(hexc("#15151f"), stroke=4.5))
    c.drawLine(2, -2, 10, -2, paint(hexc("#15151f"), stroke=4.5))
    c.drawPath(smooth_path([(-4, 14), (0, 20), (4, 14)], False), paint(hexc("#c98f66"), stroke=3))
    c.drawOval(R(-40, 14, -26, 24), paint(hexc("#ff8f8f", 0.28)))
    c.drawOval(R(26, 14, 40, 24), paint(hexc("#ff8f8f", 0.28)))
    op = clamp(amp * 1.5) if st["speaking"] else 0.0
    if op > 0.07:
        mw, mh = 13 + 7 * op, 3 + 15 * op
        c.drawOval(R(-mw, 36 - mh * 0.3, mw, 36 + mh), paint(hexc("#6a1f2c")))
        c.drawOval(R(-mw * 0.6, 36 + mh * 0.35, mw * 0.6, 36 + mh * 0.95), paint(hexc("#e2707e")))
        c.drawRect(R(-mw * 0.7, 36 - mh * 0.3, mw * 0.7, 36 - mh * 0.3 + 4), paint(hexc("#ffffff", 0.9)))
    else:
        s = 4 + 11 * smile
        p = skia.Path()
        p.moveTo(-14, 36)
        p.quadTo(0, 36 + s, 14, 36)
        c.drawPath(p, paint(hexc("#8a3a3a"), stroke=3.5))
    c.restore()
    c.restore()


def draw_mascot(c, t, st):
    amp, emo = st["amp"], st["emo"]
    lid, btilt, mouth, es = st["exp"]
    sq = 0.02 * math.sin(t * 2.2) + (0.05 * amp if st["speaking"] else 0) + (0.07 * eo(1 - st["emo_age"] / 0.35) if emo == "shock" and st["emo_age"] < 0.35 else 0)
    hop = -abs(math.sin(t * 7)) * 8 * amp if st["speaking"] else 0
    c.save()
    px_, py_ = st.get("pos", MASC_POS)
    c.translate(px_, py_ + hop * st.get("k", 1))
    c.scale(st.get("k", 1), st.get("k", 1))
    c.scale(1 - sq * 0.8, 1 + sq)
    c.rotate(math.sin(t * 1.3) * 1.2 + st["look"] * -2)
    for sx in (-1, 1):
        c.drawOval(R(sx * 34 - 18, -12, sx * 34 + 18, 6), paint(hexc("#c85a14")))
    body = skia.Path()
    body.addOval(R(-80, -136, 80, 0))
    c.drawPath(body, paint(shader=rad((-20, -96), 130, [hexc("#ffc468"), hexc("#ff9a2e"), hexc("#e8681a")], [0, 0.55, 1])))
    c.drawOval(R(-52, -124, -8, -98), paint(hexc("#ffffff", 0.30)))
    # antenna 'bit'
    c.drawLine(0, -134, 7 + math.sin(t * 2) * 3, -156, paint(hexc("#d9731c"), stroke=4))
    c.drawCircle(7 + math.sin(t * 2) * 3, -160, 9 + 2 * math.sin(t * 4), paint(shader=rad((7, -160), 22, [hexc("#9fe0ff"), hexc("#6ec3ff", 0)])))
    c.drawCircle(7 + math.sin(t * 2) * 3, -160, 5, paint(hexc("#d9f3ff")))
    bl = blink(t, 1.7) * es
    gx = st["look"] * -4
    for sx in (-1, 1):
        ex = sx * 29
        c.drawOval(R(ex - 10 * es, -82 - 14 * bl, ex + 10 * es, -82 + 14 * bl), paint(hexc("#1d1420")))
        c.drawCircle(ex + gx + 3, -86, 3.4, paint(hexc("#ffffff")))
        if lid > 0.01:
            c.save()
            c.clipRect(R(ex - 14, -100, ex + 14, -82 - 14 * bl + 28 * lid * bl), skia.ClipOp.kIntersect, True)
            c.drawOval(R(-80, -136, 80, 0), paint(hexc("#ffa535")))
            c.restore()
            c.drawLine(ex - 11 * es, -82 - 14 * bl + 28 * lid * bl, ex + 11 * es, -82 - 14 * bl + 28 * lid * bl, paint(hexc("#8a3a10"), stroke=2.5))
        if btilt:
            c.drawLine(ex - 11, -104 - sx * btilt * 7, ex + 11, -104 + sx * btilt * 7, paint(hexc("#b4530f"), stroke=3.5))
        c.drawOval(R(sx * 50 - 15, -66, sx * 50 + 15, -50), paint(hexc("#ff6f9c", 0.85)))
    op = clamp(amp * 1.5) if st["speaking"] else 0.0
    my = -52
    if op > 0.08:
        c.drawOval(R(-9 - 6 * op, my - 3, 9 + 6 * op, my + 4 + 14 * op), paint(hexc("#6a1f2c")))
        c.drawOval(R(-6, my + 4 + 8 * op, 6, my + 6 + 14 * op), paint(hexc("#ff8aa0")))
    elif mouth == "O":
        c.drawOval(R(-7, my - 2, 7, my + 14), paint(hexc("#6a1f2c")))
    elif mouth == "smile":
        p = skia.Path()
        p.moveTo(-12, my)
        p.quadTo(0, my + 14, 12, my)
        c.drawPath(p, paint(hexc("#7a2e18"), stroke=3.5))
    elif mouth == "wavy":
        p = skia.Path()
        p.moveTo(-13, my + 3)
        p.quadTo(-6, my - 5, 0, my + 3)
        p.quadTo(6, my + 11, 13, my + 3)
        c.drawPath(p, paint(hexc("#7a2e18"), stroke=3.5))
    else:
        c.drawLine(-9, my + 2, 9, my + 2, paint(hexc("#7a2e18"), stroke=3.5))
    c.restore()



# ----------------------------------------------------------------------------- sprite puppets (Blender-built packs)

EMO2EXPR = {  # animator emotions -> the 4 sprite expressions
    "neutral": "neutral", "explain": "neutral", "curious": "surprised", "laugh": "happy", "wow": "surprised", "deadpan": "skeptical",
    "shrug": "skeptical", "proud": "happy", "shock": "surprised", "happy": "happy", "confused": "skeptical", "sleepy": "neutral",
}
SAMPLING = skia.SamplingOptions(skia.FilterMode.kLinear, skia.MipmapMode.kLinear)


class Puppet:
    """A character made of pre-rendered toon sprites: body pose layer + head variant layer (expr x mouth x eyes)."""

    def __init__(self, folder):
        self.dir = folder
        self.meta = json.load(open(os.path.join(folder, "pack.json"), encoding="utf-8"))
        self.s = 100.0 / self.meta["px_per_unit"]          # sprite px -> world px
        self.cache = {}

    def img(self, key):
        im = self.cache.get(key)
        if im is None:
            f = self.meta["files"].get(key)
            if not f:
                return None
            im = skia.Image.open(os.path.join(self.dir, f)).withDefaultMipmaps()
            self.cache[key] = im
        return im

    def blit(self, c, key, layer, alpha=1.0):
        im = self.img(key)
        if im is None:
            return
        L = self.meta["layers"][layer]
        ox, oy = self.meta["origin"]
        x, y = (L["offset"][0] - ox) * self.s, (L["offset"][1] - oy) * self.s
        p = skia.Paint(AntiAlias=True)
        if alpha < 1:
            p.setAlphaf(alpha)
        c.drawImageRect(im, R(x, y, x + L["size"][0] * self.s, y + L["size"][1] * self.s), SAMPLING, p)

    def neck(self):
        ox, oy = self.meta["origin"]
        return (self.meta["neck"][0] - ox) * self.s, (self.meta["neck"][1] - oy) * self.s

    def head_key(self, expr, mouth, eyes):
        return f"head_{expr}_{mouth}_{eyes}"


def _eyes_state(bl, emo):
    if bl < 0.3:
        return "closed"
    if bl < 0.75 or emo in ("deadpan", "sleepy"):
        return "half"
    return "open"


def _mouth_state(op, t, emo, speaking):
    if not speaking or op < 0.08:
        return "o" if emo in ("shock", "wow") and not speaking else "closed"
    if op < 0.38:
        return "small"
    # vary open shapes so long vowels don't look like one flapping hole: ~1 in 4 windows is an "o"
    return "o" if (int(t * 6.5) * 2654435761) % 4 == 0 else "wide"


def puppet_host(c, t, st, pup):
    emo, gest, gp, amp = st["emo"], st["gesture"], st["gp"], st["amp"]
    bob = math.sin(t * 1.7) * 2 + (amp * 3 if st["speaking"] else 0)
    pose = gest if gest in ("shrug", "point", "wave") and gp > 0.35 else "type"
    pose = pose if pose in pup.meta["poses"] else pup.meta["poses"][0]
    c.save()
    px_, py_ = st.get("pos", HOST_POS)
    c.translate(px_, py_ + bob * 0.4 * st.get("k", 1))
    c.scale(st.get("k", 1), st.get("k", 1))
    if pose == "type" and st["typing"]:
        c.translate(0, abs(math.sin(t * 11)) * 0.8)                     # tiny typing jiggle
    pop = 1 + 0.04 * max(0.0, 1 - abs(gp - 0.45) / 0.12) if gest != "none" else 1   # pose-to-pose snap accent
    c.scale(pop, pop)
    pup.blit(c, f"body_{pose}", "body")
    nx, ny = pup.neck()
    c.translate(nx, ny)
    c.rotate(math.sin(t * 1.1) * 1.4 + (amp * 2.6 * math.sin(t * 9) if st["speaking"] else 0) + st["look"] * 3)
    c.translate(-nx, -ny)
    expr = EMO2EXPR.get(emo, "neutral")
    eyes = _eyes_state(blink(t, 0.4), emo)
    mouth = _mouth_state(clamp(amp * 1.5) if st["speaking"] else 0.0, t, emo, st["speaking"])
    pup.blit(c, pup.head_key(expr, mouth, eyes), "head")
    c.restore()


def puppet_mascot(c, t, st, pup):
    amp, emo = st["amp"], st["emo"]
    sq = 0.02 * math.sin(t * 2.2) + (0.05 * amp if st["speaking"] else 0) + (0.07 * eo(1 - st["emo_age"] / 0.35) if emo == "shock" and st["emo_age"] < 0.35 else 0)
    hop = -abs(math.sin(t * 7)) * 8 * amp if st["speaking"] else 0
    c.save()
    px_, py_ = st.get("pos", MASC_POS)
    c.translate(px_, py_ + hop * st.get("k", 1))
    c.scale(st.get("k", 1), st.get("k", 1))
    c.scale(1 - sq * 0.8, 1 + sq)
    c.rotate(math.sin(t * 1.3) * 1.4 + st["look"] * -2)
    expr = EMO2EXPR.get(emo, "neutral")
    eyes = _eyes_state(blink(t, 1.7), emo)
    mouth = _mouth_state(clamp(amp * 1.5) if st["speaking"] else 0.0, t + 0.37, emo, st["speaking"])
    pup.blit(c, pup.head_key(expr, mouth, eyes), "head")
    if st.get("antenna", True):    # antenna glow (2D, animated) on top of the sprite tip
        gx, gy = 17 + math.sin(t * 2) * 1.5, -176
        c.drawCircle(gx, gy, 16 + 3 * math.sin(t * 4), paint(shader=rad((gx, gy), 26, [hexc("#9fe0ff", 0.55), hexc("#6ec3ff", 0)])))
    c.restore()

def fire(c, t, fl, at=None, k=1.0, logs=True):
    fx, fy = at or FIRE
    c.save()
    c.translate(fx, fy)
    c.scale(k, k)
    for ang, dx in (((-14, -30), (16, 30)) if logs else ()):
        c.save()
        c.translate(dx, 6)
        c.rotate(ang)
        c.drawRRect(skia.RRect.MakeRectXY(R(-70, -12, 70, 12), 10, 10), paint(hexc("#4a2b1d")))
        c.drawOval(R(60, -12, 82, 12), paint(hexc("#8a5a3a")))
        c.restore()
    for k, (w, h, col_) in enumerate(((54, 118, "#ff5a1f"), (40, 92, "#ffa62e"), (24, 62, "#fff0a0"))):
        wob = lambda s: math.sin(t * (6 + k * 2.3) + s) * (4 + k)
        pts = [(-w, 4), (-w * 0.7, -h * 0.4 + wob(0)), (-w * 0.35, -h * 0.72 + wob(1)), (-w * 0.1, -h * 0.5), (wob(2) * 0.6, -h * (0.95 + 0.05 * math.sin(t * 9 + k))),
               (w * 0.18, -h * 0.55), (w * 0.42, -h * 0.78 + wob(3)), (w * 0.7, -h * 0.42 + wob(4)), (w, 4), (0, 12)]
        c.drawPath(smooth_path(pts), paint(hexc(col_, 0.95)))
    c.drawCircle(0, -40, 120, paint(shader=rad((0, -40), 120, [hexc("#ffb050", 0.55 * fl), hexc("#ffb050", 0)]), mode=skia.BlendMode.kPlus))
    for i in range(20):
        p = (t * 0.45 + i / 20) % 1
        ex, ey = math.sin(i * 7.3 + t * 1.4) * 40 * p, -30 - p * 260
        c.drawCircle(ex, ey, 3.2 * (1 - p) + 0.6, paint(hexc("#ffc35a", 1 - p), mode=skia.BlendMode.kPlus))
    c.restore()


# ----------------------------------------------------------------------------- UI cards


def card_size(card):
    k = card.get("kind", "lines")
    d = card.get("data", {})
    n = len(d.get("items", d.get("lines", d.get("rows", []))))
    return {"bits": 285, "bars": 125 + 52 * max(n, 1), "numberline": 290, "lines": 125 + 46 * max(n, 1), "formula": 125 + 46 * max(n, 1),
            "table": 135 + 40 * (n + 1)}.get(k, 260)


def draw_card(c, card, u, step_alpha):
    w, h = 480, card_size(card)
    slide = eo(u / 0.45)
    x0, y0 = 28 - (1 - slide) * 520, 62
    c.save()
    c.translate(x0, y0)
    c.drawRRect(skia.RRect.MakeRectXY(R(0, 0, w, h), 26, 26), paint(hexc("#070d24", 0.84 * step_alpha)))
    c.drawRRect(skia.RRect.MakeRectXY(R(0, 0, w, h), 26, 26), paint(hexc("#ffffff", 0.14), stroke=1.5))
    if card.get("step"):
        text(c, f"STEP {card['step']}", 26, 38, FB, 17, hexc("#8f9bbd"), shadow=False)
    text(c, card.get("title", ""), 26, 76, FB, 31, hexc("#ffffff"), shadow=False, maxw=w - 52)
    c.translate(26, 100)
    cw = w - 52
    kind, d = card.get("kind", "lines"), card.get("data", {})
    uu = max(0.0, u - 0.35)
    if kind == "bits":
        nb = int(d.get("bits", 4))
        val = int(uu * 2.2) % (2 ** nb)
        sw = min(70, (cw - 10) / nb - 10)
        for i in range(nb):
            on = (val >> (nb - 1 - i)) & 1
            x = 5 + i * (sw + 10)
            c.drawRRect(skia.RRect.MakeRectXY(R(x, 0, x + sw, 62), 14, 14), paint(hexc("#ffb02e") if on else hexc("#26305a")))
            c.drawRRect(skia.RRect.MakeRectXY(R(x + 6, 6 if on else 30, x + sw - 6, 28 if on else 56), 10, 10), paint(hexc("#fff3cc") if on else hexc("#3d4a82")))
        text(c, f"{2 ** nb} patterns  ·  {val:0{nb}b}", 5, 108, FM, 24, hexc("#9fe0ff"), shadow=False)
        text(c, d.get("note", f"{nb} bits → {2 ** nb} values"), 5, 140, FR, 19, hexc("#aab4d4"), shadow=False, maxw=cw)
    elif kind == "bars":
        items = d.get("items", [])
        mx = max([float(i.get("value", 1)) for i in items] + [1e-9])
        for i, it in enumerate(items):
            y = i * 52
            k = eo((uu - i * 0.35) / 0.8)
            text(c, str(it.get("label", "")), 0, y + 30, FB, 21, hexc("#dfe6ff"), shadow=False, maxw=104)
            bw = (cw - 220) * float(it.get("value", 1)) / mx
            col_ = "#6ee7a0" if it.get("hl") else "#ffb02e"
            c.drawRRect(skia.RRect.MakeRectXY(R(112, y + 8, 112 + max(6, bw * k), y + 38), 10, 10), paint(hexc(col_)))
            if k > 0.6:
                text(c, f"{it.get('value')} {it.get('unit', '')}", 112 + max(6, bw * k) + 12, y + 31, FB, 21, hexc("#ffffff"), shadow=False)
    elif kind == "numberline":
        lo, hi = float(d.get("min", -1)), float(d.get("max", 1))
        pts, snap = d.get("points", []), d.get("snap", [])
        X = lambda v: 8 + (v - lo) / (hi - lo) * (cw - 16)
        c.drawLine(8, 70, cw - 8, 70, paint(hexc("#8f9bbd"), stroke=3))
        for s in snap:
            c.drawLine(X(s), 54, X(s), 86, paint(hexc("#ffb02e"), stroke=3))
            text(c, f"{s:g}", X(s), 118, FR, 17, hexc("#ffcf80"), "c", shadow=False)
        mv = eio((uu - 1.6) / 1.0) if snap else 0
        for i, v in enumerate(pts):
            tgt = min(snap, key=lambda s: abs(s - v)) if snap else v
            p = lerp(v, tgt, mv)
            k = back((uu - i * 0.12) / 0.4)
            c.drawCircle(X(p), 70, 9 * clamp(k, 0, 1.3), paint(hexc("#ffb02e") if mv > 0.95 else hexc("#6ec3ff")))
        text(c, d.get("note", "snap each weight to the nearest level" if snap else "weights are decimals"), 8, 160, FR, 19, hexc("#aab4d4"), shadow=False, maxw=cw)
    elif kind in ("lines", "formula"):
        lines, checks = d.get("lines", []), d.get("checks", kind == "lines")
        for i, ln in enumerate(lines):
            t0 = i * 0.85
            n = int(clamp((uu - t0) * 38, 0, len(ln)))
            if n <= 0:
                continue
            y = i * 46 + 32
            last = i == len(lines) - 1 and kind == "formula"
            x = 0
            if kind == "lines" and checks:
                p = skia.Path()
                p.moveTo(2, y - 10)
                p.lineTo(10, y - 2)
                p.lineTo(24, y - 22)
                c.drawPath(p, paint(hexc("#6ee7a0"), stroke=4.5))
                x = 38
            text(c, ln[:n], x, y, FM if kind == "formula" else FR, 26 if kind == "formula" else 25, hexc("#6ee7a0") if last else hexc("#e8edff"), shadow=False, maxw=cw - x)
    elif kind == "table":
        cols, rows = d.get("cols", []), d.get("rows", [])
        cwid = cw / max(len(cols), 1)
        for j, cn in enumerate(cols):
            text(c, str(cn), j * cwid, 24, FB, 19, hexc("#8f9bbd"), shadow=False, maxw=cwid - 8)
        for i, r in enumerate(rows):
            if uu < i * 0.5:
                break
            for j, cell in enumerate(r):
                text(c, str(cell), j * cwid, 24 + (i + 1) * 40, FB if j == 0 else FR, 22, hexc("#ffffff"), shadow=False, maxw=cwid - 8)
    c.restore()
    return y0 + h


def draw_caption(c, turn, t, bottom):
    words = turn.get("words") or []
    if not words:
        return
    k = max([i for i, w in enumerate(words) if w["start"] <= t] or [-1])
    if k < 0:
        return
    g = k // 5
    chunk = words[g * 5:(g + 1) * 5]
    shown = [w for w in chunk if w["start"] <= t]
    host = turn["speaker"] == "host"
    f = font(FB, 38)
    maxw = 520
    lines, cur = [], ""
    for w in shown:
        s = (cur + " " + w["w"]).strip()
        if f.measureText(s) > maxw and cur:
            lines.append(cur)
            cur = w["w"]
        else:
            cur = s
    lines.append(cur)
    y = (bottom + 62) if bottom else 150
    for i, ln in enumerate(lines):
        a = 1.0 if i < len(lines) - 1 else eo((t - shown[-1]["start"]) / 0.10)
        col_ = hexc("#ffffff", max(0.75, a))
        text(c, ln, 40 if host else W - 40, y + i * 46, FB, 38, col_, "l" if host else "r")
    # speaker dot
    c.drawCircle(24 if host else W - 24, y - 12, 7, paint(hexc("#6ec3ff") if host else hexc("#ffb02e")))


def draw_hook(c, hk, t):
    """Big on-screen hook, visible from the very first frame (pop-settle in, slide/fade out at `until`)."""
    until = hk["until"]
    out = clamp((t - (until - 0.3)) / 0.3)
    if out >= 1 or not hk.get("text"):
        return
    words = hk["text"].split()
    hl = hk.get("highlight", "").lower().strip(".,!?")
    size = 80
    while True:
        f = font(FB, size)
        lines, cur = [], []
        for w in words:
            if cur and f.measureText(" ".join(cur + [w])) > W - 80:
                lines.append(cur)
                cur = [w]
            else:
                cur.append(w)
        lines.append(cur)
        if len(lines) <= 3 or size <= 52:
            break
        size -= 6
    c.drawRect(R(0, 0, W, 560), paint(shader=lin((0, 0), (0, 560), [hexc("#000000", 0.6 * (1 - out)), hexc("#000000", 0)])))
    pop = 1 + 0.07 * eo(1 - t / 0.25) if t < 0.25 else 1 + 0.012 * math.sin(t * 6)
    lh = size * 1.14
    cy = 290 - 70 * eo(out)
    c.save()
    c.translate(W / 2, cy)
    c.scale(pop, pop)
    y = -(len(lines) - 1) * lh / 2 + size * 0.32
    for ln in lines:
        total = f.measureText(" ".join(ln))
        x = -total / 2
        for w in ln:
            key = w.lower().strip(".,!?")
            col = hexc("#ffb02e", 1 - out) if (hl and key == hl) or (hl and hl in key) else hexc("#ffffff", 1 - out)
            c.drawString(w, x + 3, y + 5, f, paint(hexc("#000000", 0.6 * (1 - out)), blur=2))
            c.drawString(w, x, y, f, paint(col))
            x += f.measureText(w + " ")
        y += lh
    c.restore()



# ----------------------------------------------------------------------------- stage (Blender set plate + any cast)


class Stage:
    """spec["stage"] = {"plate": png, "slots": {name: {"pos": [x, y], "ppu": px_per_unit}}, "marks": {"fire": [x, y], "moon": [x, y]},
                        "cast": [{"id", "pack", "slot", "kind": "human|blob", "antenna": bool}]}
    All positions are in the 720x1280 animation world. Characters are drawn at their slot, scaled by slot ppu."""

    def __init__(self, st):
        self.st = st
        img = skia.Image.open(st["plate"])
        self.plate = img.withDefaultMipmaps()
        surf = skia.Surface(img.width(), img.height())
        cv = surf.getCanvas()
        p = skia.Paint(ImageFilter=skia.ImageFilters.Blur(7.0, 7.0, skia.TileMode.kClamp))
        cv.drawImage(img, 0, 0, skia.SamplingOptions(), p)
        soft = surf.makeImageSnapshot()
        self.levels = [img]                       # depth of field: 4 pre-blended blur levels -> ONE plate draw per frame
        for a in (0.33, 0.66, 1.0):
            s2 = skia.Surface(img.width(), img.height())
            c2 = s2.getCanvas()
            c2.drawImage(img, 0, 0)
            pp = skia.Paint()
            pp.setAlphaf(a)
            c2.drawImage(soft, 0, 0, skia.SamplingOptions(), pp)
            self.levels.append(s2.makeImageSnapshot())
        self.particles = st.get("particles", "snow")
        br = st.get("palette") or {}
        self.palette = {"accent": br.get("accent", "#3B82F6"), "accent2": br.get("accent2", "#22d3ee"), "highlight": br.get("highlight", "#FACC15"),
                        "fg": "#ffffff", "warn": "#F43F5E", "ok": "#22C55E"}
        self.cast = []
        for m in st["cast"]:
            sl = st["slots"].get(m.get("slot")) or list(st["slots"].values())[len(self.cast) % len(st["slots"])]
            self.cast.append({**m, "pup": Puppet(m["pack"]), "pos": tuple(sl["pos"]), "k": sl["ppu"] / 100.0})
        self.by_id = {m["id"]: m for m in self.cast}
        self.shots = self._shots()

    def _shots(self):
        fm = self.st.get("marks", {}).get("fire")
        sh = {"wide": (360, 640, 1.0)}
        xs = [m["pos"][0] for m in self.cast]
        ys = [m["pos"][1] for m in self.cast]
        k = max(m["k"] for m in self.cast)
        sh["two"] = ((min(xs) + max(xs)) / 2, sum(ys) / len(ys) - 1.3 * 100 * k, 1.25)
        for m in self.cast:
            x, y, kk = m["pos"][0], m["pos"][1], m["k"]
            head = 2.3 if m.get("kind") == "human" else 0.75            # head height above the slot, in character units
            sh[m["id"]] = (x, y - (1.5 if m.get("kind") == "human" else 0.7) * 100 * kk, 1.6 if m.get("kind") == "human" else 1.9)
            sh[m["id"] + "_close"] = (x, y - head * 100 * kk + 60, 2.15 if m.get("kind") == "human" else 2.5)
        sh["fire"] = (fm[0], fm[1], 1.8) if fm else sh["two"]     # a set without a fire: the beat becomes a two-shot
        if self.cast:                                    # legacy shot names keep old directors working
            sh.setdefault("host", sh[self.cast[0]["id"]])
            sh.setdefault("host_close", sh[self.cast[0]["id"] + "_close"])
            m2 = self.cast[1] if len(self.cast) > 1 else self.cast[0]
            sh.setdefault("mascot", sh[m2["id"]])
            sh.setdefault("mascot_close", sh[m2["id"] + "_close"])
        return sh

    def member(self, speaker):
        if speaker in self.by_id:
            return self.by_id[speaker]
        if speaker == "host":
            return self.cast[0]
        if speaker == "mascot":
            return self.cast[min(1, len(self.cast) - 1)]
        return self.cast[0]

    @staticmethod
    def clamp_cam(cx, cy, z):
        z = max(1.0, z)
        hw, hh = W / 2 / z, H / 2 / z
        return min(max(cx, hw), W - hw), min(max(cy, hh), H - hh), z

    def draw_bg(self, c, z):
        k = clamp((z - 1.25) / 1.4)                      # depth of field: background softens as we push in
        img = self.levels[min(3, int(round(k * 3)))]
        c.drawImageRect(img, R(0, 0, W, H), skia.SamplingOptions(skia.FilterMode.kLinear, skia.MipmapMode.kNone))
        moon = self.st.get("marks", {}).get("moon")
        if moon:
            c.drawCircle(moon[0], moon[1], 120, paint(shader=rad(tuple(moon), 120, [hexc("#c9d8ff", 0.35), hexc("#c9d8ff", 0)]), mode=skia.BlendMode.kScreen))

    def draw_cast(self, c, frame, i, t, tr, speaking, gp, age):
        spk = self.member(tr["speaker"])
        gest = tr.get("gesture", "none")
        for m in sorted(self.cast, key=lambda q: q["pos"][1]):
            me = m is spk
            # contact shadow
            c.drawOval(R(m["pos"][0] - 75 * m["k"], m["pos"][1] - 8 * m["k"], m["pos"][0] + 75 * m["k"], m["pos"][1] + 12 * m["k"]),
                       paint(hexc("#05060c", 0.35), blur=6))
            emo = tr.get("emotion", "neutral") if me else tr.get("react", "neutral")
            look = 0 if me else (1 if spk["pos"][0] > m["pos"][0] else -1)
            key = m["id"] if m["id"] in frame.amp else ("host" if m is self.cast[0] else "mascot")
            st = {"amp": frame.amp_at(key, t), "emo": emo, "speaking": speaking and me, "look": look, "emo_age": age,
                  "pos": m["pos"], "k": m["k"], "antenna": m.get("antenna", False)}
            if m.get("kind") == "human" and m["pup"].meta.get("poses"):
                st.update({"gesture": gest if me else "none", "gp": gp if me else 0,
                           "typing": not (gest in ("shrug", "point", "wave") and me and gp > 0.5)})
                puppet_host(c, t, st, m["pup"])
            else:
                puppet_mascot(c, t, st, m["pup"])


# ----------------------------------------------------------------------------- brand layer (handle + end card), from the style kit


class Brand:
    def __init__(self, b, duration):
        self.b, self.dur = b, duration
        self.logo = skia.Image.open(b["logo"]).withDefaultMipmaps() if b.get("logo") and os.path.exists(b["logo"]) else None

    def draw(self, c, t):
        b = self.b
        if b.get("handle"):
            text(c, b["handle"], 34, H - 46, FB, 22, hexc("#ffffff", 0.7), "l", shadow=True)
        k = clamp((t - (self.dur - 2.6)) / 0.45)
        if k <= 0:
            return
        c.drawRect(R(0, 0, W, H), paint(hexc(b.get("bg", "#0A0E1A"), 0.86 * k)))
        c.save()
        c.translate(W / 2, 520)
        sc = back(k)
        c.scale(sc, sc)
        if self.logo:
            s_ = 200
            c.drawImageRect(self.logo, R(-s_ / 2, -s_ / 2 - 40, s_ / 2, s_ / 2 - 40), skia.SamplingOptions(skia.FilterMode.kLinear, skia.MipmapMode.kLinear))
        text(c, b.get("name", ""), 0, 120, FB, 40, hexc("#ffffff", k), "c", shadow=False)
        line = b.get("follow", "Follow for the context behind the headline")
        text(c, line, 0, 172, FR, 26, hexc("#dbe4ff", k), "c", shadow=False, maxw=W - 90)
        bw = 260
        c.drawRRect(skia.RRect.MakeRectXY(R(-bw / 2, 210, bw / 2, 266), 28, 28), paint(hexc(b.get("accent", "#3B82F6"), k)))
        text(c, "Follow " + b.get("handle", ""), 0, 246, FB, 24, hexc("#ffffff", k), "c", shadow=False, maxw=bw - 20)
        c.restore()

# ----------------------------------------------------------------------------- frame


class Frame:
    def __init__(self, spec, scale):
        self.spec, self.scale = spec, scale
        self.turns = spec["turns"]
        self.starts = [x["start"] for x in self.turns]
        self.hz = spec.get("amp_hz", 30)
        self.surface = skia.Surface(int(W * scale), int(H * scale))
        self.amp = {k: np.array(v, dtype=float) for k, v in spec.get("amp", {}).items()}
        pk = spec.get("puppets") or {}
        self.pup = {k: Puppet(v) for k, v in pk.items() if v and os.path.exists(os.path.join(v, "pack.json"))}
        self.stage = Stage(spec["stage"]) if spec.get("stage") else None
        self.brand = Brand(spec["brand"], spec["duration"]) if spec.get("brand") else None

    def draw_broll(self, c, i, tr, t, speaking, age):
        import broll as BR
        st = self.stage
        b = tr["broll"]
        nxt = self.turns[i + 1]["start"] if i + 1 < len(self.turns) else tr["end"] + 0.3
        u = clamp((t - tr["start"]) / max(0.4, nxt - tr["start"]))
        k = eo(clamp(age / 0.28))
        P = st.palette
        c.save()
        x0 = W * (1 - k)                                  # wipe in from the right
        c.clipRect(R(x0, 0, W, H))
        c.translate(x0 * 0.25, 0)
        BR.draw(c, b.get("piece"), b.get("data") or {}, u, t, P)
        c.restore()
        if k < 1:
            c.drawRect(R(x0 - 6, 0, x0, H), paint(hexc(P["accent2"])))
        # speaker bubble with live lip-sync
        m = st.member(tr["speaker"])
        bx, by, br = 120, 1080, 84
        c.drawCircle(bx, by, br + 6, paint(hexc(P["accent"], k)))
        c.save()
        p = skia.Path()
        p.addCircle(bx, by, br)
        c.clipPath(p, skia.ClipOp.kIntersect, True)
        c.drawCircle(bx, by, br, paint(shader=lin((bx, by - br), (bx, by + br), [hexc("#1e293b"), hexc("#0b1020")])))
        human = m.get("kind") == "human"
        kk = 0.92 if human else 1.15
        head_y = (232 if human else 75) * kk
        key = m["id"] if m["id"] in self.amp else ("host" if m is st.cast[0] else "mascot")
        stt = {"amp": self.amp_at(key, t), "emo": tr.get("emotion", "neutral"), "speaking": speaking, "look": 0, "emo_age": age,
               "pos": (bx, by + head_y + (25 if human else 30)), "k": kk, "antenna": m.get("antenna", False)}
        if human and m["pup"].meta.get("poses"):
            stt.update({"gesture": "none", "gp": 0, "typing": False})
            puppet_host(c, t, stt, m["pup"])
        else:
            puppet_mascot(c, t, stt, m["pup"])
        c.restore()
        text(c, m.get("name") or m["id"], bx + br + 18, by + 10, FB, 24, hexc("#ffffff", k), "l", shadow=True)

    def vignette(self):
        v = getattr(self, "_vig", None)
        if v is None:
            sf = skia.Surface(W, H)
            sf.getCanvas().drawRect(R(0, 0, W, H), paint(shader=rad((W / 2, H / 2), H * 0.78, [hexc("#000000", 0), hexc("#000000", 0), hexc("#02040c", 0.62)], [0, 0.55, 1])))
            v = self._vig = sf.makeImageSnapshot()
        return v

    def card_lift(self, i, t):
        """While a step card is on screen, frame the subject lower so the card never covers a face (0..1 eased)."""
        for j in range(i, -1, -1):
            if "card" in self.turns[j]:
                if self.turns[j]["card"] is None:
                    return 0.0
                c0 = self.turns[j]["start"] + self.turns[j].get("card_delay", 0.25)
                return eio(clamp((t - c0) / 0.35))
        return 0.0

    def amp_at(self, who, t):
        a = self.amp.get(who)
        if a is None or not len(a):
            return 0.0
        x = t * self.hz
        i = int(x)
        f = x - i
        g = lambda j: a[max(0, min(len(a) - 1, j))]
        v = g(i) * (1 - f) + g(i + 1) * f
        return float(0.25 * g(i - 1) + 0.5 * v + 0.25 * g(i + 2))   # soft attack/decay: no mouth flicker

    def exp_for(self, who, i, t):
        """Expression numbers blended from the previous beat's emotion (0.2 s) so faces never snap."""
        tab = HOST_EXP if who == "host" else MASC_EXP

        def emo_at(j):
            tr = self.turns[j]
            return tr.get("emotion", "neutral") if tr["speaker"] == who else tr.get("react", "neutral")

        cur = tab.get(emo_at(i), tab["neutral"])
        prv = tab.get(emo_at(i - 1), tab["neutral"]) if i > 0 else cur
        k = eio((t - self.turns[i]["start"]) / 0.2)
        if who == "host":
            return tuple(lerp(prv[j], cur[j], k) for j in range(4))
        return (lerp(prv[0], cur[0], k), lerp(prv[1], cur[1], k), cur[2] if k > 0.5 else prv[2], lerp(prv[3], cur[3], k))

    def _segments(self):
        segs = []
        self.seg_of = []
        for i, tr in enumerate(self.turns):
            if i and tr.get("shot") == self.turns[i - 1].get("shot"):
                segs[-1][1] = i
            else:
                segs.append([i, i])
            self.seg_of.append(len(segs) - 1)
        self.segs = [(a, b, self.turns[a]["start"], self.turns[b]["end"]) for a, b in segs]

    def seg_state(self, s, t):
        a, b, S, E = self.segs[s]
        table = self.stage.shots if self.stage else SHOTS
        cx, cy, z = table.get(self.turns[a].get("shot", "wide"), table["wide"])
        p = clamp((t - S) / max(E - S, 0.1))
        mv = self.turns[a].get("move", "push")
        if mv == "push":
            z *= 1 + 0.06 * p
        elif mv == "pull":
            z *= 1 + (0.14 if s == 0 else 0.07) * (1 - p)
        elif mv == "drift":
            cx += (p - 0.5) * 40
        return Stage.clamp_cam(cx, cy, z) if self.stage else (cx, cy, z)

    def cam(self, i, t):
        """One continuous move per shot (no zoom reset at every line) and a snappy 0.16 s cut between shots."""
        if not hasattr(self, "segs"):
            self._segments()
        s = self.seg_of[i]
        cur = self.seg_state(s, t)
        if s == 0:
            return cur
        S = self.segs[s][2]
        k = eio((t - S) / 0.16)
        if k >= 1:
            return cur
        prev = self.seg_state(s - 1, S)
        return tuple(lerp(prev[j], cur[j], k) for j in range(3))

    def render(self, t):
        c = self.surface.getCanvas()
        c.save()
        c.scale(self.scale, self.scale)
        i = max(0, bisect.bisect_right(self.starts, t) - 1)
        tr = self.turns[i]
        speaking = tr["start"] <= t <= tr["end"] + 0.15
        fl = 0.88 + 0.1 * math.sin(t * 9.1) + 0.05 * math.sin(t * 23.7 + 1)
        cx, cy, z = self.cam(i, t)
        if self.stage:
            lift = self.card_lift(i, t)
            if lift:
                cy, z = cy - 150 * lift / max(z, 1), z
                cx, cy, z = Stage.clamp_cam(cx, cy, z)
        # camera
        c.save()
        c.translate(W / 2, H / 2)
        c.scale(z, z)
        c.translate(-cx, -cy)
        covered = bool(self.stage and tr.get("broll") and (t - tr["start"]) >= 0.3)
        if covered:
            pass                                   # the b-roll covers the whole frame: skip the studio
        elif self.stage:
            self.stage.draw_bg(c, z)
        else:
            world(c, t, fl)
        age = t - tr["start"]
        gp = eo(age / 0.35) * (1 - eo((t - (tr["end"] - 0.3)) / 0.3)) if tr.get("gesture") else 0.0
        hs = tr["speaker"] == "host"
        gest = tr.get("gesture", "none")
        base_emo = lambda who: tr.get("emotion", "neutral") if (tr["speaker"] == who) else tr.get("react", "neutral")
        hk = self.spec.get("hook")
        until = hk["until"] if hk else 0.0
        if self.stage and not covered:
            self.stage.draw_cast(c, self, i, t, tr, speaking, gp, age)
            fpos = self.stage.st.get("marks", {}).get("fire")
            if fpos:
                fire(c, t, fl, at=tuple(fpos), k=0.9, logs=False)
                c.drawCircle(fpos[0], fpos[1] - 90, 560, paint(shader=rad((fpos[0], fpos[1] - 90), 560, [hexc("#ff8a2a", 0.22 * fl), hexc("#ff8a2a", 0.07 * fl), hexc("#ff8a2a", 0)], [0, 0.5, 1]), mode=skia.BlendMode.kScreen))
        else:
          (lambda cc, tt, st: puppet_host(cc, tt, st, self.pup["host"]) if "host" in self.pup else draw_host(cc, tt, st))(c, t, {"amp": self.amp_at("host", t), "emo": base_emo("host"), "gesture": gest if hs else "none", "gp": gp if hs else 0, "speaking": speaking and hs,
                         "typing": not (gest in ("shrug", "point", "wave") and hs and gp > 0.5) and not (not hs and gp > 0), "look": 0 if hs else 1,
                         "exp": self.exp_for("host", i, t)})
          (lambda cc, tt, st: puppet_mascot(cc, tt, st, self.pup["mascot"]) if "mascot" in self.pup else draw_mascot(cc, tt, st))(c, t, {"amp": self.amp_at("mascot", t), "emo": base_emo("mascot"), "speaking": speaking and not hs, "look": 1 if hs else 0, "emo_age": age, "exp": self.exp_for("mascot", i, t)})
          fire(c, t, fl)
          fx, fy = FIRE                                  # firelight over everything in the world
          c.drawCircle(fx, fy - 90, 560, paint(shader=rad((fx, fy - 90), 560, [hexc("#ff8a2a", 0.30 * fl), hexc("#ff8a2a", 0.10 * fl), hexc("#ff8a2a", 0)], [0, 0.5, 1]), mode=skia.BlendMode.kScreen))
        c.restore()
        # animated b-roll cutaway: SHOW how it works, with the speaker in a bubble
        broll_on = bool(self.stage and tr.get("broll"))
        if broll_on:
            self.draw_broll(c, i, tr, t, speaking, age)
        # screen-space: snow, vignette, UI
        parts = self.stage.particles if self.stage else "snow"
        if parts == "snow":
            for layer, sp in ((SNOW_FAR, 26), (SNOW_NEAR, 64)):
                for x, y, r, ph in layer:
                    c.drawCircle((x + math.sin(t * 0.8 + ph) * 18) % W, (y + t * sp * (r / 3 + 0.4)) % H, r, paint(hexc("#ffffff", 0.55 if r < 3 else 0.8)))
        elif parts == "dust":                         # slow floating studio dust / bokeh
            for x, y, r, ph in SNOW_FAR[:40]:
                c.drawCircle((x + math.sin(t * 0.3 + ph) * 30) % W, (y - t * 6 * (r / 2)) % H, r * 0.8, paint(hexc("#9fc2ff", 0.18)))
        c.drawImageRect(self.vignette(), R(0, 0, W, H), skia.SamplingOptions())
        # card
        card, c0 = None, 0
        for j in range(i, -1, -1):
            if "card" in self.turns[j]:
                card, c0 = self.turns[j]["card"], self.turns[j]["start"] + self.turns[j].get("card_delay", 0.25)
                break
        bottom = 0
        c0 = max(c0, until)
        if card and t >= c0 and not broll_on:
            bottom = draw_card(c, card, t - c0, 1.0)
        if t >= until:
            draw_caption(c, tr, t, bottom)
        if hk:
            draw_hook(c, hk, t)
        if self.brand:
            self.brand.draw(c, t)
        c.restore()
        img = self.surface.makeImageSnapshot()
        return img.toarray(colorType=skia.kRGBA_8888_ColorType)


# ----------------------------------------------------------------------------- driver


def _free_gb():
    try:
        import ctypes

        class MS(ctypes.Structure):
            _fields_ = [("l", ctypes.c_ulong), ("load", ctypes.c_ulong), ("tot", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("pt", ctypes.c_ulonglong), ("pa", ctypes.c_ulonglong), ("vt", ctypes.c_ulonglong), ("va", ctypes.c_ulonglong), ("x", ctypes.c_ulonglong)]
        m = MS()
        m.l = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
        return m.avail / 2 ** 30
    except Exception:
        return 8.0


def _safe_chunk(args):
    """A chunk that fails returns None (and leaves no half-written file) so only it is retried."""
    try:
        out = render_chunk(args)
        return out if os.path.exists(out) and os.path.getsize(out) > 1000 else None
    except Exception as e:
        print(f"chunk {os.path.basename(args[5])} failed: {e}", file=sys.stderr)
        try:
            os.remove(args[5])
        except OSError:
            pass
        return None


def render_chunk(args):
    spec, scale, fps, a, b, out, ff = args
    fr = Frame(spec, scale)
    w, h = int(W * scale), int(H * scale)
    p = subprocess.Popen([ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
                          "-c:v", "libx264", "-preset", "medium", "-tune", "animation", "-crf", "14", "-pix_fmt", "yuv420p", out], stdin=subprocess.PIPE)
    for n in range(a, b):
        p.stdin.write(np.ascontiguousarray(fr.render(n / fps)).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError(f"encoder exited {p.returncode}")
    return out


def main():
    spec = json.load(open(sys.argv[1], encoding="utf-8"))
    out = sys.argv[2]
    scale = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    fps = int(sys.argv[4]) if len(sys.argv) > 4 else 30
    ff = spec.get("ffmpeg", "ffmpeg")
    total = int(math.ceil(spec["duration"] * fps))
    if spec.get("only_frame") is not None:   # preview a single still
        arr = Frame(spec, scale).render(spec["only_frame"])
        from PIL import Image
        Image.fromarray(arr[..., :3]).save(out)
        return
    out = os.path.abspath(out)
    workers = min(os.cpu_count() or 4, 12, max(2, int(_free_gb() / 0.7)))      # each worker holds a surface + sprite cache
    nch = min(max(workers * 2, 2), max(1, total // 30))                        # more, smaller chunks: a crash costs less
    edges = [round(i * total / nch) for i in range(nch + 1)]
    tmp = os.path.splitext(out)[0]
    jobs = [(spec, scale, fps, edges[i], edges[i + 1], f"{tmp}_c{i:02d}.mp4", ff) for i in range(nch)]
    done = {}
    for attempt, n in enumerate((workers, max(2, workers // 2), 1)):
        todo = [j for j in jobs if j[5] not in done]
        if not todo:
            break
        with Pool(min(n, len(todo))) as pool:
            for j, res in zip(todo, pool.map(_safe_chunk, todo)):
                if res:
                    done[j[5]] = res
        if len(done) < len(jobs):
            print(f"render: {len(jobs) - len(done)} chunk(s) failed, retrying with fewer workers", file=sys.stderr)
    if len(done) < len(jobs):
        raise RuntimeError("render chunks kept failing (low memory?)")
    parts = [done[j[5]] for j in jobs]
    lst = f"{tmp}_parts.txt"
    open(lst, "w").write("".join(f"file '{os.path.basename(p)}'\n" for p in parts))
    subprocess.run([ff, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out], check=True, cwd=os.path.dirname(os.path.abspath(out)))
    for p in parts + [lst]:
        os.remove(p)


if __name__ == "__main__":
    main()
