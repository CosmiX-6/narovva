"""Animated b-roll: full-frame "how it works" cutaways that SHOW what the voice explains (instead of writing it on screen).

draw(c, piece, data, u, t, P)   u = progress through the beat 0..1, t = absolute time (for idle motion), P = palette
Pieces (data fields; every label short, every number from the script):
  switch_split {before, items:[a, b], after}        one switch wired to two lamps splits into two independent switches
  timeline     {from:{value,label}, to:{value,label}, subject}   a bar stretches from one span to a longer one
  flow         {from:{icon,label}, to:{icon,label}, item, turn: none|block|reverse|grow, turn_label}
  compare      {title, left:{label, value, display}, right:{...}}   two bars rise; the bigger wins
  machine      {input:{icon,label}, output:{icon,label}, label}   items ride a belt into a machine and come out changed
  steps        {steps:[{icon,label}, ...2-4]}                  stations light up in order, a parcel travels through
  counter      {from, to, prefix, suffix, label}               a big number counts up
  filter       {item, gate_label, pass_label, block_label}     items arrive; some pass, some are rejected
  split        {title, left:{icon,label}, right:{icon,label}}  a crowd divides into two sides
  stack        {title, layers:[a, b, c]}                       layers stack into a whole
Icons come from the kinetic icon library (laptop, cloud, chip, gpu, server, chat, doc, brain, gear, person, money, ...).
"""
import math

import skia
from kinetic import _rr, icon
from render import FB, H, R, W, back, clamp, eio, eo, hexc, lerp, lin, paint, rad, smooth_path, text

PIECES = ["switch_split", "timeline", "flow", "compare", "machine", "steps", "counter", "filter", "split", "stack"]


def _bg(c, t, P):
    c.drawRect(R(0, 0, W, H), paint(shader=lin((0, 0), (W * 0.3, H), [hexc("#070b1f"), hexc("#101a3a")])))
    for k, (cx, cy, r, col) in enumerate(((140, 420, 420, P["accent"]), (600, 900, 380, P["accent2"]))):
        x, y = cx + math.sin(t * 0.3 + k) * 40, cy + math.cos(t * 0.25 + k) * 30
        c.drawCircle(x, y, r, paint(shader=rad((x, y), r, [hexc(col, 0.18), hexc(col, 0)])))
    gp = paint(hexc("#ffffff", 0.035), stroke=1)
    for x in range(0, W + 60, 60):
        c.drawLine(x, 0, x, H, gp)
    for y in range(0, H + 60, 60):
        c.drawLine(0, y, W, y, gp)


def _title(c, s, u, P, y=300):
    if not s:
        return
    k = eo(clamp(u * 5))
    text(c, str(s).upper(), W / 2, y - 20 * (1 - k), FB, 40 if len(str(s)) < 22 else 32, hexc("#ffffff", k), "c", shadow=True, maxw=W - 80)
    c.drawRect(R(W / 2 - 40 * k, y + 16, W / 2 + 40 * k, y + 21), paint(hexc(P["accent2"], k)))


def _label(c, s, x, y, P, k=1.0, size=26, col=None, bg=True):
    if not s:
        return
    f_w = len(str(s)) * size * 0.55 + 28
    x = min(max(x, f_w / 2 + 16), W - f_w / 2 - 16)
    if bg:
        _rr(c, x - f_w / 2, y - size - 6, x + f_w / 2, y + 12, 12, paint(hexc("#ffffff", 0.95 * k)))
        text(c, str(s), x, y, FB, size, hexc(col or "#0b1020", k), "c", shadow=False, maxw=f_w - 16)
    else:
        text(c, str(s), x, y, FB, size, hexc(col or "#ffffff", k), "c", shadow=True)


def _ic(c, name, x, y, s, t, P, k=1.0):
    if k <= 0:
        return
    c.save()
    c.translate(x, y)
    c.scale(s * back(min(1, k)), s * back(min(1, k)))
    icon(c, name or "doc", P, t)
    c.restore()


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------- pieces


def switch_split(c, d, u, t, P):
    _title(c, d.get("title") or d.get("after"), u, P)
    items = (d.get("items") or ["A", "B"])[:2]
    k_split = eio(clamp((u - 0.35) / 0.3))
    for i, lab in enumerate(items):
        lx = 210 + i * 300
        on = (i == 0) or k_split < 0.5 or (u % 0.5 < 0.25 if k_split >= 1 else True)
        if k_split >= 1:
            on = i == 0 or (math.sin(t * 3) > 0)                     # after the split they toggle independently
        # lamp
        c.drawCircle(lx, 520, 110, paint(shader=rad((lx, 520), 110, [hexc("#FDE68A", 0.45 if on else 0), hexc("#FDE68A", 0)])))
        c.drawCircle(lx, 520, 46, paint(hexc("#FDE047" if on else "#334155")))
        c.drawRect(R(lx - 20, 566, lx + 20, 596), paint(hexc("#94a3b8")))
        _label(c, lab, lx, 470 - 80, P, eo(clamp(u * 4)))
        # wire to the switch(es)
        sx = lerp(360, lx, k_split)
        c.drawPath(smooth_path([(lx, 596), (lx, 700), (sx, 760), (sx, 830)], False), paint(hexc(P["accent2"], 0.9), stroke=5))
    # switches
    for i in range(2 if k_split > 0 else 1):
        sx = lerp(360, 210 + i * 300, k_split) if k_split > 0 else 360
        _rr(c, sx - 45, 830, sx + 45, 960, 16, paint(hexc("#e2e8f0")))
        up = (math.sin(t * 3 + i * 2) > 0) if k_split >= 1 else True
        _rr(c, sx - 22, 850 if up else 900, sx + 22, 900 if up else 940, 10, paint(hexc(P["accent"])))
    _label(c, d.get("before") if k_split < 0.5 else d.get("after"), 360, 1040, P, 1.0, 28, bg=False, col=P["highlight"])


def timeline(c, d, u, t, P):
    _title(c, d.get("subject"), u, P)
    fr, to = d.get("from") or {}, d.get("to") or {}
    x0, y0, x1 = 90, 640, 630
    c.drawRect(R(x0, y0 - 6, x1, y0 + 6), paint(hexc("#ffffff", 0.15)))
    k1 = eo(clamp(u / 0.25))
    short = x0 + (x1 - x0) * 0.12
    c.drawRect(R(x0, y0 - 18, lerp(x0, short, k1), y0 + 18), paint(hexc("#94a3b8")))
    def badge(x):
        v, lab = str(x.get("value", "")), str(x.get("label", ""))
        main = x.get("display") or (lab if lab and (not v or v.split()[0] in lab or v.replace(".", "").isdigit()) else v) or v
        sub = x.get("note") or (lab if main != lab else "")
        return main, sub

    m1, s1 = badge(fr)
    m2, s2 = badge(to)
    _label(c, m1, short, y0 - 60, P, k1, 30)
    _label(c, s1, short, y0 + 70, P, k1, 22, bg=False)
    k2 = eio(clamp((u - 0.3) / 0.45))
    if k2 > 0:
        c.drawRect(R(x0, y0 - 18, lerp(short, x1, k2), y0 + 18), paint(shader=lin((x0, 0), (x1, 0), [hexc(P["accent"]), hexc(P["highlight"])])))
        _label(c, m2, lerp(short, x1, k2), y0 - 120, P, k2, 38, col="#0b1020")
        _label(c, s2, lerp(short, x1, k2) - 40, y0 + 120, P, k2, 22, bg=False)
        # ticking day markers
        n = int(18 * k2)
        for i in range(n):
            x = lerp(short, x1, i / 18)
            c.drawLine(x, y0 + 26, x, y0 + 40, paint(hexc("#ffffff", 0.5), stroke=2))
    _ic(c, d.get("icon", "chat"), 360, 880, 1.0, t, P, eo(clamp(u * 3)))


def flow(c, d, u, t, P):
    _title(c, d.get("title"), u, P)
    a, b = d.get("from") or {}, d.get("to") or {}
    ka = eo(clamp(u * 4))
    _ic(c, a.get("icon", "laptop"), 160, 640, 1.0, t, P, ka)
    _ic(c, b.get("icon", "server"), 560, 640, 1.0, t, P, eo(clamp(u * 4 - 0.3)))
    _label(c, a.get("label"), 160, 780, P, ka, 24)
    _label(c, b.get("label"), 560, 780, P, ka, 24)
    turn = d.get("turn", "none")
    kt = clamp((u - 0.55) / 0.2)
    c.drawLine(250, 640, 470, 640, paint(hexc("#ffffff", 0.2), stroke=4))
    n = 6 if not (turn == "grow" and kt > 0) else 12
    for j in range(n):
        q = ((t * 0.55 + j / n) % 1)
        if turn == "reverse" and kt > 0.5:
            q = 1 - q
        x = lerp(250, 470, q)
        if turn == "block" and kt > 0 and x > 355:
            continue
        c.save()
        c.translate(x, 640 + math.sin(q * 6.28) * 6)
        c.scale(0.4, 0.4)
        icon(c, d.get("item", "doc"), P, t)
        c.restore()
    if turn == "block" and kt > 0:
        _rr(c, 352, 560 - 40 * (1 - eo(kt)), 368, 720, 6, paint(hexc(P["warn"])))
        _label(c, d.get("turn_label", "BLOCKED"), 360, 520, P, kt, 24, col=P["warn"])
    elif d.get("turn_label") and kt > 0:
        _label(c, d.get("turn_label"), 360, 520, P, kt, 24)


def compare(c, d, u, t, P):
    _title(c, d.get("title"), u, P)
    L, Rt = d.get("left") or {}, d.get("right") or {}
    vl, vr = _num(L.get("value")) or 1, _num(Rt.get("value")) or 1
    m = max(vl, vr)
    k = eio(clamp((u - 0.1) / 0.5))
    for i, (s, v) in enumerate(((L, vl), (Rt, vr))):
        x = 220 + i * 280
        h = 420 * (v / m) * k
        win = v == m
        c.drawRect(R(x - 70, 900 - h, x + 70, 900), paint(shader=lin((0, 900 - h), (0, 900), [hexc(P["highlight"] if win else P["accent"]), hexc(P["accent"], 0.6)])))
        _label(c, s.get("display") or s.get("value"), x, 860 - h, P, k, 32)
        _label(c, s.get("label"), x, 960, P, eo(clamp(u * 4)), 22, bg=False)
    c.drawRect(R(100, 900, 620, 904), paint(hexc("#ffffff", 0.4)))


def machine(c, d, u, t, P):
    _title(c, d.get("title") or d.get("label"), u, P)
    inp, out = d.get("input") or {}, d.get("output") or {}
    _rr(c, 270, 520, 450, 760, 24, paint(shader=lin((0, 520), (0, 760), [hexc("#334155"), hexc("#1e293b")])))
    c.save(); c.translate(360, 640); c.scale(0.7, 0.7); icon(c, "gear", P, t); c.restore()
    _label(c, d.get("label"), 360, 500, P, eo(clamp(u * 4)), 22)
    c.drawRect(R(40, 770, 680, 790), paint(hexc("#475569")))
    for j in range(4):
        q = ((t * 0.35 + j / 4) % 1)
        x = lerp(40, 680, q)
        if 270 < x < 450:
            continue
        c.save(); c.translate(x, 725); c.scale(0.45, 0.45)
        icon(c, (inp if x < 360 else out).get("icon", "doc"), P, t)
        c.restore()
    _label(c, inp.get("label"), 140, 870, P, eo(clamp(u * 4)), 22)
    _label(c, out.get("label"), 580, 870, P, eo(clamp(u * 4 - 0.3)), 22)


def steps(c, d, u, t, P):
    st = (d.get("steps") or [])[:4] or [{"icon": "doc", "label": "step"}]
    _title(c, d.get("title"), u, P)
    n = len(st)
    ys = [470 + i * (520 / max(1, n - 1)) for i in range(n)] if n > 1 else [700]
    active = min(n - 1, int(u * n * 1.05))
    c.drawLine(200, ys[0], 200, ys[-1], paint(hexc("#ffffff", 0.2), stroke=5))
    c.drawLine(200, ys[0], 200, lerp(ys[0], ys[-1], clamp(u * 1.05)), paint(hexc(P["accent2"]), stroke=5))
    for i, s in enumerate(st):
        on = i <= active
        c.drawCircle(200, ys[i], 62, paint(hexc(P["accent"] if on else "#1e293b")))
        c.save(); c.translate(200, ys[i]); c.scale(0.38, 0.38); icon(c, s.get("icon", "doc"), P, t); c.restore()
        text(c, s.get("label", ""), 300, ys[i] + 12, FB, 32 if on else 28, hexc("#ffffff" if on else "#64748b"), "l", shadow=on, maxw=380)
    k = clamp(u * 1.05)
    c.drawCircle(200, lerp(ys[0], ys[-1], k), 14, paint(hexc(P["highlight"])))


def counter(c, d, u, t, P):
    _title(c, d.get("label"), u, P, y=420)
    a, b = _num(d.get("from")) or 0, _num(d.get("to")) or 0
    k = eo(clamp((u - 0.05) / 0.6))
    v = lerp(a, b, k)
    s = f"{v:,.0f}" if abs(b) >= 10 or float(b).is_integer() else f"{v:.1f}"
    big = f"{d.get('prefix', '')}{s}{d.get('suffix', '')}"
    c.drawCircle(360, 680, 300, paint(shader=rad((360, 680), 300, [hexc(P["accent"], 0.35), hexc(P["accent"], 0)])))
    text(c, big, 360, 720, FB, 150 if len(big) < 6 else 110, hexc(P["highlight"]), "c", shadow=True, maxw=W - 60)


def filter_(c, d, u, t, P):
    _title(c, d.get("title") or d.get("gate_label"), u, P)
    _rr(c, 300, 520, 420, 860, 18, paint(hexc("#1e293b")))
    _label(c, d.get("gate_label"), 360, 500, P, eo(clamp(u * 4)), 22)
    for j in range(6):
        q = ((t * 0.4 + j / 6) % 1)
        ok = j % 3 != 1
        if q < 0.5:
            x, y = lerp(40, 300, q * 2), 690
        else:
            x, y = lerp(420, 680, (q - 0.5) * 2), (600 if ok else 820)
        c.save(); c.translate(x, y); c.scale(0.42, 0.42)
        icon(c, d.get("item", "doc") if q < 0.5 else ("check" if ok else "cross"), P, t)
        c.restore()
    _label(c, d.get("pass_label"), 600, 540, P, eo(clamp(u * 4 - 0.4)), 22, col=P["ok"])
    _label(c, d.get("block_label"), 600, 900, P, eo(clamp(u * 4 - 0.5)), 22, col=P["warn"])


def split(c, d, u, t, P):
    _title(c, d.get("title"), u, P)
    k = eio(clamp((u - 0.2) / 0.4))
    for i in range(10):
        side = -1 if i % 2 else 1
        x0 = 360 + (i - 5) * 22
        x = lerp(x0, 360 + side * (150 + (i // 2) * 18), k)
        y = 700 + (i % 3) * 30
        c.save(); c.translate(x, y); c.scale(0.55, 0.55); icon(c, "person", P, t + i); c.restore()
    L, Rt = d.get("left") or {}, d.get("right") or {}
    _label(c, L.get("label"), 190, 900, P, k, 24, col=P["ok"])
    _label(c, Rt.get("label"), 530, 900, P, k, 24, col=P["warn"])


def stack(c, d, u, t, P):
    _title(c, d.get("title"), u, P)
    ls = (d.get("layers") or [])[:4]
    for i, lab in enumerate(ls):
        k = eo(clamp((u - i * 0.15) / 0.25))
        y = 860 - i * 120 - 60 * (1 - k)
        p = skia.Path()
        p.moveTo(360, y - 50); p.lineTo(560, y); p.lineTo(360, y + 50); p.lineTo(160, y); p.close()
        c.drawPath(p, paint(hexc([P["accent"], P["accent2"], P["ok"], P["highlight"]][i % 4], 0.9 * k)))
        _label(c, lab, 360, y + 10, P, k, 22)


DRAW = {"switch_split": switch_split, "timeline": timeline, "flow": flow, "compare": compare, "machine": machine, "steps": steps,
        "counter": counter, "filter": filter_, "split": split, "stack": stack}


def draw(c, piece, data, u, t, P):
    _bg(c, t, P)
    fn = DRAW.get(piece)
    if fn:
        fn(c, data or {}, u, t, P)
