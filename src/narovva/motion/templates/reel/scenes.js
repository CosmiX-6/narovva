/* The explainer storyboard's scenes (narovva.motion.storyboard): each one SHOWS
 * what its spoken lines say -- a date track whose focus moves with the voice, a
 * cause-and-effect chain that draws itself, a grid of players with stamps, a
 * number that counts up, a quote whose key words get highlighted, a log typed
 * out, a takeaway checklist, an end card.
 *
 * A scene's `parts` say when each of its lines is spoken (seconds into the
 * scene); elements arrive on those times so the picture moves with the voice.
 * Everything is a pure function of timeline time: tweens are fromTo, later
 * changes to an element use immediateRender:false, nothing reads the clock.
 */
window.CUScenes = function (K) {
  const { tl, el, image, fit, figures, phraseAt, heading, kick, introHead, barIn, V, mh, SH, OV, PHOTO, DECK, UI, opener } = K;
  const NS = "http://www.w3.org/2000/svg";
  const ICONS = window.CU_ICONS || {};
  const GREEN = "#22C55E", RED = "#F43F5E";

  // -- shared pieces ---------------------------------------------------------
  function icon(name, size, parent) {
    const svg = document.createElementNS(NS, "svg");
    for (const [k, v] of Object.entries({ viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor",
      "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round" })) svg.setAttribute(k, v);
    svg.innerHTML = ICONS[name] || ICONS["circle-help"] || "";
    svg.classList.add("ico");
    parent.appendChild(svg);
    return svg;
  }
  // The icon draws itself on, stroke by stroke.
  function drawOn(svg, at, dur) {
    svg.querySelectorAll("path, circle, rect, line, polyline, polygon, ellipse").forEach((p) => {
      const len = Math.ceil(p.getTotalLength ? p.getTotalLength() : 60) + 2;
      p.style.strokeDasharray = len;
      tl.fromTo(p, { strokeDashoffset: len }, { strokeDashoffset: 0, duration: dur, ease: "power2.inOut" }, at);
    });
  }
  function badge(parent, name, size, at, cls) {
    const b = el("div", "badge" + (cls ? " " + cls : ""), null, parent);
    b.style.width = b.style.height = size + "px";
    const svg = icon(name, Math.round(size * 0.5), b);
    tl.fromTo(b, { opacity: 0, scale: 0.4 }, { opacity: 1, scale: 1, duration: 0.32, ease: "back.out(2.2)" }, at);
    drawOn(svg, at + 0.08, 0.6);
    return b;
  }
  const fitW = (node, maxW, start, min, step) => {
    let s = start;
    node.style.fontSize = s + "px";
    while (node.scrollWidth > maxW && s > min) { s -= step || 4; node.style.fontSize = s + "px"; }
    return s;
  };
  const title = (sc, d, size, maxH) => (d.title ? heading(sc, d.title, size || 74, maxH || mh(200), d.mark) : null);

  // When the scene's lines are spoken. Without a voice-over the storyboard still sets estimated parts.
  const parts = (s) => (s.parts && s.parts.length ? s.parts : [{ at: 0.15, voice: Math.max(0.8, s.duration - 0.8) }]);
  const partAt = (s, c, j) => c.t0 + parts(s)[Math.max(0, Math.min(j, parts(s).length - 1))].at;
  const latest = (c) => c.t0 + c.dur - OV - 0.55;
  // When item i of n arrives: items are shared out over the lines from `from` on; items that
  // share a line arrive one after another across it.
  const itemAt = (s, c, i, n, from) => {
    const ps = parts(s), f = Math.min(from || 0, ps.length - 1), P = ps.length - f;
    const j = Math.min(P - 1, Math.floor((i * P) / n));
    const first = Math.ceil((j * n) / P), count = Math.max(1, Math.ceil(((j + 1) * n) / P) - first);
    const p = ps[f + j];
    const span = Math.min(p.voice * 0.75, 0.42 * (count - 1));
    const t = c.t0 + p.at + 0.06 + (count > 1 ? (span * (i - first)) / (count - 1) : 0);
    return Math.min(t, latest(c));
  };
  // A small verdict stamp slammed onto one item; the item jolts.
  function miniStamp(host, st, at, cls) {
    if (!st || !st.text) return;
    const m = el("div", "stamp " + (cls || "mini"), st.text, host);
    m.style.setProperty("--stamp", st.color || RED);
    tl.fromTo(m, { opacity: 0, scale: 2.4, rotation: -16 }, { opacity: 1, scale: 1, rotation: -8, duration: 0.16, ease: "power4.in" }, at);
    tl.fromTo(host, { x: 9 }, { x: 0, duration: 0.35, ease: "elastic.out(1, 0.3)", immediateRender: false }, at + 0.16);
  }
  const initials = (who) => String(who || "?").replace(/[,(].*$/, "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

  const S = {};

  // -- headline: a statement, with an icon that draws itself on ---------------
  S.headline = (sc, s, c) => {
    const d = s.data || {}, { a, D } = c;
    if (PHOTO && PHOTO.mode === "full" && c.i === opener) { // the opener sits on the article's own photo
      sc.parentElement.style.justifyContent = "flex-end";
      sc.parentElement.style.paddingBottom = "60px";
      kick(sc, s); heading(sc, d.text, 118, mh(560), d.mark); introHead(sc, a, D, true); barIn(sc, a, D, 0.2);
      if (PHOTO.credit) {
        const cr = el("div", "credit", PHOTO.credit, sc); cr.style.cssText = "text-align:left;margin:28px 0 0";
        tl.fromTo(cr, { opacity: 0 }, { opacity: 1, duration: 0.3 }, a(0.5));
      }
      return;
    }
    if (d.icon) badge(sc, d.icon, 132, a(0));
    kick(sc, s); heading(sc, d.text, 116, mh(d.sub ? 460 : 600), d.mark); introHead(sc, a, D, true); barIn(sc, a, D, 0.2);
    if (d.sub) {
      const p = el("p", "body", null, sc); figures(p, d.sub); fit(p, 220, 46, 30);
      tl.fromTo(p, { opacity: 0, y: 24 }, { opacity: 1, y: 0, duration: 0.3, ease: "power3.out" }, Math.min(latest(c), partAt(s, c, 1) - 0.05));
    }
  };

  // -- number: one figure, counted up (from the figure before, when given) -----
  S.number = (sc, s, c) => {
    const d = s.data, m = d.metric;
    sc.classList.add("centered");
    kick(sc, s);
    const burst = el("div", "burst", null, sc);
    const row = el("div", "bignum-row", null, sc);
    const num = el("div", "bignum" + (d.down ? " down" : ""), null, row);
    const sign = /^[-−]/.test(String(d.value).trim()) ? "−" : "";
    const fmt = (v) => sign + V.format(m, v);
    const unit = d.unit ? el("div", "bigunit", d.unit, row) : null;
    num.textContent = fmt(m.value);
    let size = 300;
    const sizeTo = (px) => { num.style.fontSize = px + "px"; if (unit) unit.style.fontSize = Math.round(px * 0.34) + "px"; };
    sizeTo(size);
    while (row.scrollWidth > 858 && size > 110) { size -= 10; sizeTo(size); }
    const lab = el("div", "biglabel", null, sc);
    if (d.down || d.from) icon(d.down ? "trending-down" : "trending-up", 54, lab).classList.add(d.down ? "dn" : "up");
    figures(el("span", null, null, lab), d.label);
    fit(lab, 240, 54, 34);
    const T = c.a(0.06), run = Math.min(1.5, Math.max(0.7, parts(s)[0].voice * 0.55));
    const start = d.from ? d.from.value : 0, o = { v: start };
    num.textContent = fmt(start);
    tl.fromTo(row, { opacity: 0, scale: 0.55 }, { opacity: 1, scale: 1, duration: 0.38, ease: "back.out(1.7)" }, T);
    tl.fromTo(o, { v: start }, { v: m.value, duration: run, ease: "power3.out", onUpdate: () => { num.textContent = fmt(o.v); } }, T);
    tl.fromTo(burst, { opacity: 0.85, scale: 0.25 }, { opacity: 0, scale: 1.7, duration: 1.0, ease: "power2.out" }, T + run * 0.85);
    tl.fromTo(lab, { opacity: 0, y: 30 }, { opacity: 1, y: 0, duration: 0.3, ease: "power3.out" }, T + Math.min(0.45, run * 0.5));
    if (d.from) {
      const fr = el("div", "bigfrom", "up from " + V.format(d.from, d.from.value), sc);
      if (d.down) fr.textContent = "down from " + V.format(d.from, d.from.value);
      tl.fromTo(fr, { opacity: 0 }, { opacity: 1, duration: 0.3 }, T + run);
    }
    c.stampTarget = row; c.stampAt = T + run + 0.3;
  };

  // -- question: the big question the next beats answer -----------------------
  S.question = (sc, s, c) => {
    const d = s.data, { a } = c;
    sc.classList.add("centered");
    kick(sc, s);
    const q = el("div", "qtext", null, sc);
    const text = String(d.text).toUpperCase(), asks = text.endsWith("?");
    const glyphs = [...(asks ? text.slice(0, -1) : text)].map((ch) => el("span", null, ch === " " ? " " : ch, q));
    const qm = asks ? el("span", "qm", "?", q) : null;
    fitW(q, 858, 200, 90, 6);
    tl.fromTo(glyphs, { opacity: 0, scale: 1.9, y: -24 }, { opacity: 1, scale: 1, y: 0, duration: 0.24, ease: "power4.out", stagger: Math.min(0.05, 0.3 / glyphs.length) }, a(0));
    if (qm) tl.fromTo(qm, { opacity: 0, rotation: -35, scale: 0.3 }, { opacity: 1, rotation: 0, scale: 1, duration: 0.45, ease: "back.out(3)" }, a(0.26));
    const b = badge(sc, d.icon, 230, a(0.3), "big hl");
    const bob = Math.max(1, Math.ceil(c.dur / 1.1));
    tl.fromTo(b, { y: -10 }, { y: 10, duration: 1.1, ease: "sine.inOut", repeat: bob, yoyo: true, immediateRender: false }, a(0.65));
    c.stampTarget = q; c.stampAt = a(0.9);
  };

  // -- dates: a track of dates; the focus moves on with each spoken line ------
  S.dates = (sc, s, c) => {
    const d = s.data, ev = d.events, N = ev.length;
    kick(sc, s); title(sc, d, 70, mh(170));
    const track = el("div", "dtrack", null, sc);
    const fill = el("i", null, null, el("div", "drail", null, track));
    const marks = ev.map((e, k) => {
      const x = N > 1 ? (k / (N - 1)) * 100 : 0;
      const dot = el("div", "ddot", null, track); dot.style.left = x + "%";
      const glow = el("b", null, null, dot);
      const lab = el("div", "dlab", e.when, track); lab.style.left = x + "%";
      lab.style.transform = k === 0 ? "translateX(-18px)" : k === N - 1 ? "translateX(calc(-100% + 18px))" : "translateX(-50%)";
      return { dot, glow, lab };
    });
    const panel = el("div", "dpanel", null, sc);
    const cards = ev.map((e) => {
      const card = el("div", "dcard", null, panel);
      fitW(el("div", "dwhen", e.when, card), 858, 150, 64, 6);
      if (e.what) figures(el("div", "dwhat", null, card), e.what);
      return card;
    });
    const P = parts(s).length, first = partAt(s, c, 0);
    const step = Math.max(0.55, Math.min(1.6, (latest(c) - first) / N));
    const times = ev.map((_, k) => Math.min(latest(c), P >= N ? partAt(s, c, k) : first + k * step));
    tl.fromTo(track, { opacity: 0, y: -24 }, { opacity: 1, y: 0, duration: 0.3, ease: "power3.out" }, c.a(0));
    let was = 0;
    times.forEach((T, k) => {
      const frac = N > 1 ? k / (N - 1) : 1;
      tl.fromTo(fill, { scaleX: was }, { scaleX: frac, duration: 0.45, ease: "power2.inOut", immediateRender: k === 0 }, T);
      was = frac;
      tl.fromTo(marks[k].glow, { opacity: 0, scale: 0.4 }, { opacity: 1, scale: 1, duration: 0.3, ease: "back.out(3)" }, T + 0.3);
      tl.fromTo(marks[k].lab, { color: "rgb(154,163,186)" }, { color: "rgb(243,245,250)", duration: 0.2, immediateRender: false }, T + 0.3);
      tl.fromTo(cards[k], { opacity: 0, y: 50 }, { opacity: 1, y: 0, duration: 0.35, ease: "power4.out" }, T + 0.12);
      if (k > 0) tl.fromTo(cards[k - 1], { opacity: 1, y: 0 }, { opacity: 0, y: -40, duration: 0.24, ease: "power2.in", immediateRender: false }, T);
    });
    c.stampTarget = cards[N - 1]; c.stampAt = times[N - 1] + 0.7;
  };

  // -- chain: how it works / how one thing led to another; a link can break ----
  const CHAIN_ICONS = ["link", "zap", "target", "flag"];
  S.chain = (sc, s, c) => {
    const d = s.data, nodes = d.nodes, N = nodes.length;
    kick(sc, s); title(sc, d, 70, mh(170));
    const wrap = el("div", "chain", null, sc);
    let last = null, lastT = 0;
    nodes.forEach((n, k) => {
      const T = Math.max(c.a(0.1) + (k ? 0.32 : 0), itemAt(s, c, k, N));
      if (k > 0) {
        const broken = d.broken === k;
        const link = el("div", "clink" + (broken ? " broken" : ""), null, wrap);
        const stem = el("i", "cstem", null, link);
        const pulse = el("b", "cpulse", null, link);
        tl.set(pulse, { opacity: 0 }, 0);
        tl.fromTo(stem, { scaleY: 0 }, { scaleY: 1, duration: 0.26, ease: "power2.out" }, T - 0.34);
        if (broken) {
          const hz = el("div", "hazard", null, link);
          const x = el("div", "cx", null, link); icon("x", 30, x);
          tl.fromTo(pulse, { y: 0, opacity: 1, scale: 1 }, { y: 26, opacity: 1, scale: 1, duration: 0.18, ease: "power2.in", immediateRender: false }, T - 0.3);
          tl.fromTo(pulse, { opacity: 1, scale: 1 }, { opacity: 0, scale: 2.8, duration: 0.25, ease: "power2.out", immediateRender: false }, T - 0.12);
          tl.fromTo(hz, { scaleX: 0, opacity: 0 }, { scaleX: 1, opacity: 1, duration: 0.22, ease: "back.out(2)" }, T - 0.12);
          tl.fromTo(x, { scale: 0, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.26, ease: "back.out(3)" }, T - 0.04);
        } else {
          tl.fromTo(pulse, { y: 0, opacity: 1 }, { y: 70, opacity: 1, duration: 0.28, ease: "power1.in", immediateRender: false }, T - 0.3);
          tl.fromTo(pulse, { opacity: 1 }, { opacity: 0, duration: 0.1, immediateRender: false }, T - 0.02);
        }
      }
      const dead = d.broken != null && k >= d.broken;
      const node = el("div", "cnode" + (dead ? " dead" : ""), null, wrap);
      const svg = icon(n.icon || CHAIN_ICONS[k % CHAIN_ICONS.length], 60, el("div", "cicon", null, node));
      const tx = el("div", "ctext", null, node);
      el("div", "clabel", n.label, tx);
      if (n.sub) figures(el("div", "csub", null, tx), n.sub);
      tl.fromTo(node, { opacity: 0, x: -50 }, { opacity: 1, x: 0, duration: 0.3, ease: "power4.out" }, T);
      drawOn(svg, T + 0.05, 0.5);
      last = node; lastT = T;
    });
    c.stampTarget = last; c.stampAt = lastT + 0.6;
  };

  // -- grid: the players / products / places, and what happened to each --------
  S.grid = (sc, s, c) => {
    const d = s.data, items = d.items, n = items.length;
    const cols = n <= 4 ? 2 : n <= 6 ? 3 : 4;
    kick(sc, s); title(sc, d, 70, mh(170));
    const g = el("div", "tgrid c" + cols, null, sc);
    const tiles = [];
    let lastT = 0;
    items.forEach((it, i) => {
      const t = el("div", "tile", null, g);
      const svg = icon(it.icon || "sparkles", cols === 2 ? 84 : cols === 3 ? 64 : 52, el("div", "ticon", null, t));
      el("div", "tlabel", it.label, t);
      if (it.sub) el("div", "tsub", it.sub, t);
      const T = itemAt(s, c, i, n);
      tl.fromTo(t, { opacity: 0, scale: 0.7, y: 30 }, { opacity: 1, scale: 1, y: 0, duration: 0.3, ease: "back.out(1.8)" }, T);
      drawOn(svg, T + 0.05, 0.45);
      tiles.push(t); lastT = Math.max(lastT, T);
    });
    let k = 0;
    items.forEach((it, i) => {
      if (it.stamp) { miniStamp(tiles[i], it.stamp, Math.min(latest(c), lastT + 0.45 + k * 0.16)); k++; }
    });
    c.stampTarget = g; c.stampAt = lastT + 0.55 + k * 0.16;
  };

  // -- cards: the evidence, one card per line, each with its own verdict -------
  S.cards = (sc, s, c) => {
    const d = s.data, items = d.items, n = items.length;
    kick(sc, s); title(sc, d, 74, mh(190));
    const box = el("div", "ecards", null, sc);
    const size = n > 2 ? 40 : 46;
    let prev = null, T = c.a(0.1);
    items.forEach((it, i) => {
      const card = el("div", "ecard", null, box);
      if (it.tag) el("div", "etag", it.tag, card);
      const tx = el("div", "etxt", null, card); tx.style.fontSize = size + "px"; figures(tx, it.text);
      T = itemAt(s, c, i, n);
      tl.fromTo(card, { opacity: 0, y: 46 }, { opacity: 1, y: 0, duration: 0.3, ease: "power4.out" }, T);
      if (prev) tl.fromTo(prev, { opacity: 1 }, { opacity: 0.72, duration: 0.2, ease: "power2.out", immediateRender: false }, T);
      if (it.stamp) miniStamp(card, it.stamp, Math.min(latest(c), T + 0.6), "card");
      prev = card;
    });
    c.stampTarget = prev; c.stampAt = T + 0.65;
  };

  // -- split: who wins, who pays ---------------------------------------------
  S.split = (sc, s, c) => {
    const d = s.data;
    kick(sc, s); title(sc, d, 74, mh(190));
    const w = el("div", "split", null, sc);
    const seq = [];
    [["left", GREEN, "trending-up", "arrow-up"], ["right", RED, "trending-down", "arrow-down"]].forEach(([key, tone, headIcon, rowIcon]) => {
      const side = d[key], col = el("div", "scol2", null, w);
      col.style.setProperty("--tone", tone);
      const hd = el("div", "shead", null, col); icon(headIcon, 54, hd); el("span", null, side.title, hd);
      seq.push(hd);
      side.items.forEach((t) => { const row = el("div", "sitem", null, col); icon(rowIcon, 38, row); figures(el("span", null, null, row), t); seq.push(row); });
    });
    seq.forEach((node, i) => {
      tl.fromTo(node, { opacity: 0, x: node.classList.contains("shead") ? 0 : -30, scale: node.classList.contains("shead") ? 0.8 : 1 },
        { opacity: 1, x: 0, scale: 1, duration: 0.28, ease: "back.out(1.6)" }, itemAt(s, c, i, seq.length));
    });
    c.stampTarget = w; c.stampAt = itemAt(s, c, seq.length - 1, seq.length) + 0.6;
  };

  // -- excerpt: a real quote, its key words highlighted as they are said -------
  S.excerpt = (sc, s, c) => {
    const d = s.data, { a } = c;
    kick(sc, s);
    const card = el("div", "xcard", null, sc);
    const head = el("div", "xhead", null, card);
    el("div", "xav", initials(d.who), head);
    const meta = el("div", "xmeta", null, head);
    el("div", "xwho", d.who, meta); el("div", "xsrc", "ON THE RECORD", meta);
    const q = el("div", "xtext", null, card);
    const toks = String(d.text).split(/\s+/), hit = phraseAt(toks, d.mark);
    let mark = null;
    toks.forEach((w, j) => {
      if (j) (hit.has(j) && hit.has(j - 1) ? mark : q).appendChild(document.createTextNode(" "));
      if (hit.has(j)) { if (!mark) mark = el("span", "xmark", null, q); mark.appendChild(document.createTextNode(w)); }
      else q.appendChild(document.createTextNode(w));
    });
    q.insertBefore(document.createTextNode("“"), q.firstChild); q.appendChild(document.createTextNode("”"));
    fit(q, mh(440), 62, 34);
    tl.fromTo(card, { opacity: 0, y: 70, rotationX: -16, transformPerspective: 1100 }, { opacity: 1, y: 0, rotationX: 0, duration: 0.45, ease: "power3.out" }, a(0));
    tl.fromTo(q, { opacity: 0 }, { opacity: 1, duration: 0.3 }, a(0.2));
    const Tm = Math.min(latest(c), parts(s).length > 1 ? partAt(s, c, 1) : a(0.2) + Math.min(1.2, parts(s)[0].voice * 0.5));
    if (mark) tl.fromTo(mark, { backgroundSize: "0% 100%" }, { backgroundSize: "100% 100%", duration: 0.6, ease: "power2.inOut" }, Tm);
    c.stampTarget = card; c.stampAt = Tm + 0.7;
  };

  // -- terminal: facts typed out like a log ------------------------------------
  S.terminal = (sc, s, c) => {
    const d = s.data, n = d.lines.length;
    kick(sc, s);
    const w = el("div", "term", null, sc);
    const bar = el("div", "tbar", null, w);
    ["#FF5F57", "#FEBC2E", "#28C840"].forEach((col) => { el("i", null, null, bar).style.background = col; });
    el("span", "ttl", String(d.title || "log").toLowerCase(), bar);
    const body = el("div", "tbody", null, w);
    let end = c.a(0.2), lastRow = null;
    d.lines.forEach((ln, i) => {
      const row = el("div", "tline", null, body);
      el("span", "tp", ">", row);
      const tx = el("span", "tx", null, row);
      const glyphs = [];
      String(ln).split(/(\s+)/).forEach((part) => {
        const host = /\d/.test(part) ? el("span", "acc", null, tx) : tx;
        [...part].forEach((ch) => glyphs.push(el("span", null, ch, host)));
      });
      const T = Math.max(c.a(0.3), itemAt(s, c, i, n)), run = Math.min(1.0, 0.028 * glyphs.length);
      tl.fromTo(row, { opacity: 0 }, { opacity: 1, duration: 0.01 }, T);
      tl.fromTo(glyphs, { opacity: 0 }, { opacity: 1, duration: 0.01, stagger: run / Math.max(1, glyphs.length) }, T);
      end = T + run; lastRow = tx;
    });
    const caret = el("span", "caret", null, lastRow);
    tl.fromTo(caret, { opacity: 1 }, { opacity: 0, duration: 0.45, ease: "steps(1)", repeat: Math.ceil(c.dur / 0.45), yoyo: true }, c.t0);
    tl.fromTo(w, { opacity: 0, scale: 0.94, y: 30 }, { opacity: 1, scale: 1, y: 0, duration: 0.35, ease: "power3.out" }, c.a(0));
    c.stampTarget = w; c.stampAt = end + 0.4;
  };

  // -- checklist: the takeaway, or what to watch next --------------------------
  S.checklist = (sc, s, c) => {
    const d = s.data, { a, D } = c, n = d.items.length;
    if (d.icon) badge(sc, d.icon, 120, a(0), "hl");
    kick(sc, s);
    const h = heading(sc, d.title, 80, mh(330), d.mark);
    h.classList.add("vtitle");
    fit(h, mh(330), 80, 44);
    introHead(sc, a, D);
    const list = el("div", "checks", null, sc);
    d.items.forEach((t, i) => {
      const row = el("div", "check", null, list);
      const svg = icon("circle-check", 56, row);
      figures(el("span", null, null, row), t);
      const T = Math.max(a(0.45), itemAt(s, c, i, n, parts(s).length > 1 ? 1 : 0));
      tl.fromTo(row, { opacity: 0, x: -40 }, { opacity: 1, x: 0, duration: 0.3, ease: "power4.out" }, T);
      drawOn(svg, T + 0.05, 0.45);
    });
  };

  // When each word of line j is said (spread over the line in proportion to its length,
  // as the captions do).
  const wordTimes = (s, c, j, toks) => {
    const p = parts(s)[Math.min(j, parts(s).length - 1)], chars = toks.reduce((n, w) => n + w.length + 1, 0);
    let done = 0;
    return toks.map((w) => { const t = c.t0 + p.at + p.voice * (done / chars); done += w.length + 1; return t; });
  };

  // -- ask: the viewer cuts in with the question they would ask right now ------
  // A message bubble from "you": three typing dots, then the words land as the second
  // voice says them. The bubble is the caption for this beat.
  S.ask = (sc, s, c) => {
    const d = s.data, { a } = c;
    sc.classList.add("askwrap");
    const ghost = el("div", "askghost", "?", sc);
    const who = el("div", "askwho", null, sc);
    icon("user", 40, el("div", "askav", null, who));
    el("span", null, "YOU", who);
    const bubble = el("div", "askbub", null, sc);
    const dots = el("div", "askdots", null, bubble);
    const dd = [el("i", null, null, dots), el("i", null, null, dots), el("i", null, null, dots)];
    const txt = el("div", "asktxt", null, bubble);
    const toks = String(d.text).split(/\s+/);
    const spans = toks.map((w, j) => { const sp = el("span", null, w, txt); if (j < toks.length - 1) txt.appendChild(document.createTextNode(" ")); return sp; });
    fit(txt, mh(520), 76, 44);
    const at = wordTimes(s, c, 0, toks);
    const T = a(0);
    tl.fromTo(ghost, { opacity: 0, scale: 0.6, rotation: -20 }, { opacity: 0.55, scale: 1, rotation: 10, duration: 0.5, ease: "expo.out" }, T);
    tl.fromTo(who, { opacity: 0, x: -30 }, { opacity: 1, x: 0, duration: 0.25, ease: "power3.out" }, T);
    tl.fromTo(bubble, { opacity: 0, scale: 0.6, y: 40 }, { opacity: 1, scale: 1, y: 0, duration: 0.32, ease: "back.out(1.8)" }, T + 0.06);
    // typing dots until the first word, then the words
    const typingEnd = Math.max(T + 0.3, at[0] - 0.02);
    dd.forEach((dot, k) => tl.fromTo(dot, { y: 0 }, { y: -12, duration: 0.18, ease: "sine.inOut", yoyo: true, repeat: Math.max(1, Math.round((typingEnd - T) / 0.36) * 2 - 1) }, T + 0.1 + k * 0.08));
    tl.set(dots, { display: "none" }, typingEnd);
    tl.set(txt, { opacity: 0 }, 0);
    tl.set(txt, { opacity: 1 }, typingEnd);
    spans.forEach((sp, j) => tl.fromTo(sp, { opacity: 0, filter: "blur(6px)" }, { opacity: 1, filter: "blur(0px)", duration: 0.14, ease: "power2.out" }, Math.max(typingEnd, at[j])));
  };

  // -- source: the receipt -- the article's own words on a paper card ---------
  // The world behind dims (index.html), the card lands, and a marker sweeps over the
  // key phrase as the voice reaches it.
  S.source = (sc, s, c) => {
    const d = s.data, { a } = c;
    kick(sc, s);
    const card = el("div", "srccard", null, sc);
    const head = el("div", "srchead", null, card);
    const pub = d.publisher || "The report";
    el("div", "srclogo", pub.replace(/^the\s+/i, "").charAt(0).toUpperCase(), head);
    el("div", "srcpub", pub, head);
    const q = el("div", "srctext", null, card);
    const toks = String(d.text).split(/\s+/), hit = phraseAt(toks, d.mark);
    let mark = null;
    toks.forEach((w, j) => {
      if (j) (hit.has(j) && hit.has(j - 1) ? mark : q).appendChild(document.createTextNode(" "));
      if (hit.has(j)) { if (!mark) mark = el("span", "srcmark", null, q); mark.appendChild(document.createTextNode(w)); }
      else q.appendChild(document.createTextNode(w));
    });
    fit(q, mh(560), 50, 32);
    const foot = el("div", "srcfoot", (pub + " · " + ((UI.hud && UI.hud.date) || "")).replace(/ · $/, ""), card);
    const T = a(0);
    tl.fromTo(card, { opacity: 0, y: 90, rotation: 2.5, scale: 0.94 }, { opacity: 1, y: 0, rotation: 0, scale: 1, duration: 0.5, ease: "expo.out" }, T);
    tl.fromTo(foot, { opacity: 0 }, { opacity: 1, duration: 0.3 }, T + 0.3);
    // the marker: when the line that says it starts (or partway through a single line)
    const Tm = Math.min(latest(c), parts(s).length > 1 ? partAt(s, c, 1) : a(0.25) + Math.min(1.1, parts(s)[0].voice * 0.45));
    if (mark) tl.fromTo(mark, { backgroundSize: "0% 100%" }, { backgroundSize: "100% 100%", duration: 0.55, ease: "power2.inOut" }, Tm);
    c.stampTarget = card; c.stampAt = Tm + 0.6;
  };

  // -- recap: the short version, one row per option / player / takeaway -------
  S.recap = (sc, s, c) => {
    const d = s.data, rows = d.rows, n = rows.length;
    kick(sc, s); title(sc, d, 70, mh(170));
    const box = el("div", "recap", null, sc);
    const els = rows.map((r) => {
      const row = el("div", "rrow", null, box);
      el("div", "rlab", r.label, row);
      if (r.note) figures(el("div", "rnote", null, row), r.note);
      return row;
    });
    let prev = null, lastT = c.a(0.1);
    els.forEach((row, i) => {
      const T = Math.max(c.a(0.1) + i * 0.12, itemAt(s, c, i, n));
      tl.fromTo(row, { opacity: 0, x: -50 }, { opacity: 1, x: 0, duration: 0.32, ease: "expo.out" }, T);
      tl.fromTo(row, { "--lit": 0 }, { "--lit": 1, duration: 0.25, ease: "power2.out" }, T + 0.05);
      if (prev) tl.fromTo(prev, { "--lit": 1, opacity: 1 }, { "--lit": 0, opacity: 0.6, duration: 0.25, ease: "power2.out", immediateRender: false }, T);
      prev = row; lastT = T;
    });
    // the last row stays lit; the earlier ones come back up once they're all in
    els.slice(0, -1).forEach((row) => tl.fromTo(row, { opacity: 0.6 }, { opacity: 1, duration: 0.3, immediateRender: false }, Math.min(latest(c), lastT + 0.9)));
    c.stampTarget = box; c.stampAt = lastT + 0.6;
  };

  // -- compose: a picture built for this beat (story-first mode) ----------------------
  // The beat's own actors, laid out by `layout`, and what the lines say happens to them, each step on the time
  // its line is spoken: a link drawn with a pulse running down it, a token travelling between two actors, an
  // actor growing or shrinking (its figure counting to the new value), a red strike, a highlight, a count-up.
  const numParts = (v) => { const m = String(v || "").match(/^([^\d-]*)(-?[\d][\d,]*\.?\d*)(.*)$/); return m ? { pre: m[1], n: parseFloat(m[2].replace(/,/g, "")), dec: (m[2].split(".")[1] || "").length, post: m[3], comma: m[2].includes(",") } : null; };
  const fmtNum = (p, x) => { let s = x.toFixed(p.dec); if (p.comma) s = Number(s).toLocaleString("en-US", { minimumFractionDigits: p.dec, maximumFractionDigits: p.dec }); return p.pre + s + p.post; };
  S.compose = (sc, s, c) => {
    const d = s.data || {}, A = d.actors || [], n = A.length, L = d.layout || "row";
    kick(sc, s); title(sc, d, 70, mh(170));
    // the whole scene window below the kicker and title (about 880px with captions on)
    const W = 858, H = Math.max(560, mh(860) - (d.title ? 190 : 0) - (s.kicker ? 90 : 0));
    const stage = el("div", "comp comp-" + L, null, sc);
    stage.style.height = H + "px";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`); svg.setAttribute("width", W); svg.setAttribute("height", H);
    svg.classList.add("compsvg"); stage.appendChild(svg);
    // centres of the actors, by layout (stage pixels)
    const P = A.map((_, k) => {
      if (L === "versus") return [W * (k ? 0.76 : 0.24), H * 0.46];
      if (L === "stack") return [W / 2, H * (n > 1 ? 0.1 + (0.8 * k) / (n - 1) : 0.5)];
      if (L === "flow") return [W * (n > 1 ? 0.15 + (0.7 * k) / (n - 1) : 0.5), H * (n > 3 ? (k % 2 ? 0.62 : 0.3) : 0.42)];
      if (L === "hub") {
        if (!k) return [W / 2, H / 2];
        // an ellipse that uses the tall stage, turned half a step so no satellite sits right on the core's label
        const ang = -Math.PI / 2 + ((k - 0.5) * 2 * Math.PI) / (n - 1);
        return [W / 2 + Math.cos(ang) * W * 0.38, H / 2 + Math.sin(ang) * H * 0.42];
      }
      return [W * (n > 1 ? 0.13 + (0.74 * k) / (n - 1) : 0.5), H * 0.46];   // row
    });
    // one actor fills the stage; more share it
    const size = L === "stack" ? 0 : L === "hub" ? 150 : ({ 1: 300, 2: 230, 3: 190, 4: 150, 5: 130 })[n] * (L === "flow" ? 0.9 : 1);
    const nodes = A.map((a, k) => {
      const nd = el("div", "cnode2" + (L === "stack" ? " wide" : "") + (L === "hub" && !k ? " core" : ""), null, stage);
      nd.style.left = P[k][0] + "px"; nd.style.top = P[k][1] + "px";
      const disc = el("div", "cdisc", null, nd);
      const sz = L === "stack" ? 104 : L === "hub" && !k ? 180 : size;
      if (n === 1) nd.classList.add("solo");
      disc.style.width = disc.style.height = sz + "px";
      const ic = icon(a.icon || "sparkles",Math.round(sz * 0.5), disc);
      const tx = el("div", "ctx", null, nd);
      const lab = el("div", "clab", a.label, tx);
      if (L !== "stack") {
        // shrink to fit on one line; only a label that still does not fit wraps, and only between words
        // the stage is not laid out yet here, so size from the text: about 0.72em per uppercase glyph
        const maxW = Math.max(200, W / Math.max(2, n) - 20), em = 0.72, txt = String(a.label);
        const longest = Math.max(...txt.split(/\s+/).map((w) => w.length), 1);
        let fs = Math.min(n === 1 ? 66 : 46, maxW / (txt.length * em));
        if (fs < 34 && /\s/.test(txt)) fs = Math.min(n === 1 ? 66 : 46, maxW / (longest * em));   // two lines, whole words
        else lab.style.whiteSpace = "nowrap";
        lab.style.fontSize = Math.max(24, Math.floor(fs)) + "px";
        lab.style.maxWidth = maxW + "px";
      }
      const val = a.value ? el("div", "cval", a.value, tx) : null;
      if (a.note) figures(el("div", "cnote", null, tx), a.note);
      return { nd, disc, ic, val, a };
    });
    const R = (k) => (L === "stack" ? 64 : (L === "hub" && !k ? 180 : size) / 2 + 10);
    // when each step happens: on its line if given, else spread over the lines; steps on one line follow each other
    const steps = d.steps || [];
    const seen = {};
    const at = steps.map((st, i) => {
      const base = st.line != null ? partAt(s, c, st.line) + 0.1 : itemAt(s, c, i, steps.length);
      const key = String(st.line != null ? st.line : "auto" + i);
      const T = base + 0.45 * (seen[key] = (seen[key] || 0) + 1) - 0.45;
      return Math.min(T, latest(c));
    });
    // arrival: an actor with an "appear" step arrives then; the others come in at the start, one after another
    const firstAt = A.map((_, k) => { const i = steps.findIndex((st) => st.do === "appear" && st.who === k); return i >= 0 ? at[i] : null; });
    nodes.forEach((o, k) => {
      const T = firstAt[k] != null ? firstAt[k] : c.a(0.05) + k * 0.14;
      tl.fromTo(o.nd, { opacity: 0, scale: 0.4, xPercent: -50, yPercent: -50 }, { opacity: 1, scale: 1, xPercent: -50, yPercent: -50, duration: 0.34, ease: "back.out(2)" }, T);
      drawOn(o.ic, T + 0.06, 0.5);
      o.arrive = T;
    });
    if (L === "versus") {
      const vs = el("div", "cvs", "VS", stage);
      tl.fromTo(vs, { opacity: 0, scale: 0.3, xPercent: -50, yPercent: -50 }, { opacity: 1, scale: 1, xPercent: -50, yPercent: -50, duration: 0.3, ease: "back.out(3)" }, c.a(0.3));
    }
    const links = {};
    function link(i, j, T, red) {
      const key = i + ">" + j;
      if (links[key]) return links[key];
      const [x1, y1] = P[i], [x2, y2] = P[j], dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1;
      const ax = x1 + (dx / len) * R(i), ay = y1 + (dy / len) * R(i), bx = x2 - (dx / len) * R(j), by = y2 - (dy / len) * R(j);
      const ln = document.createElementNS(NS, "line");
      for (const [k2, v] of Object.entries({ x1: ax, y1: ay, x2: bx, y2: by })) ln.setAttribute(k2, v);
      ln.classList.add("clink2"); if (red) ln.classList.add("red"); svg.appendChild(ln);
      const L2 = Math.hypot(bx - ax, by - ay);
      ln.style.strokeDasharray = L2;
      tl.fromTo(ln, { strokeDashoffset: L2 }, { strokeDashoffset: 0, duration: 0.4, ease: "power2.inOut" }, T);
      return (links[key] = { ln, ax, ay, bx, by });
    }
    const dim = (except, T) => nodes.forEach((o, k) => { if (k !== except) tl.fromTo(o.nd, { opacity: 1 }, { opacity: 0.35, duration: 0.25, immediateRender: false }, T); });
    steps.forEach((st, i) => {
      const T = Math.max(at[i], nodes[st.who].arrive + 0.2), o = nodes[st.who];
      if (st.do === "connect" || st.do === "move") {
        const lk = link(st.who, st.to, T, false);
        if (st.do === "connect") {
          const pulse = document.createElementNS(NS, "circle"); pulse.setAttribute("r", 12); pulse.classList.add("cpulse2"); svg.appendChild(pulse);
          tl.fromTo(pulse, { attr: { cx: lk.ax, cy: lk.ay }, opacity: 1 }, { attr: { cx: lk.bx, cy: lk.by }, opacity: 1, duration: 0.6, ease: "power1.inOut" }, T + 0.35);
          tl.fromTo(pulse, { opacity: 1 }, { opacity: 0, duration: 0.2, immediateRender: false }, T + 0.95);
          tl.set(pulse, { opacity: 0 }, 0);
          if (st.label) {
            const tag = el("div", "ctag", st.label, stage);
            // beside the link, not on it (perpendicular offset), so it never covers a label
            const ux = lk.bx - lk.ax, uy = lk.by - lk.ay, ul = Math.hypot(ux, uy) || 1;
            tag.style.left = (lk.ax + lk.bx) / 2 + (-uy / ul) * 46 + "px"; tag.style.top = (lk.ay + lk.by) / 2 + (ux / ul) * 46 - (Math.abs(uy) < 1 ? 46 : 0) + "px";
            tl.fromTo(tag, { opacity: 0, scale: 0.6, xPercent: -50, yPercent: -50 }, { opacity: 1, scale: 1, xPercent: -50, yPercent: -50, duration: 0.25, ease: "back.out(2)" }, T + 0.3);
          }
        } else {
          const tok = el("div", "ctok", st.label || st.value || "", stage);
          if (!st.label && !st.value) tok.classList.add("dot");
          tok.style.left = lk.ax + "px"; tok.style.top = lk.ay + "px";
          tl.set(tok, { opacity: 0 }, 0);
          tl.fromTo(tok, { opacity: 0, x: 0, y: 0, xPercent: -50, yPercent: -50, scale: 0.5 }, { opacity: 1, scale: 1, x: 0, y: 0, xPercent: -50, yPercent: -50, duration: 0.2, immediateRender: false }, T + 0.3);
          tl.fromTo(tok, { x: 0, y: 0 }, { x: lk.bx - lk.ax, y: lk.by - lk.ay, duration: 0.9, ease: "power2.inOut", immediateRender: false }, T + 0.45);
          tl.fromTo(tok, { opacity: 1 }, { opacity: 0, scale: 0.4, duration: 0.25, ease: "power2.in", immediateRender: false }, T + 1.3);   // delivered
          tl.fromTo(nodes[st.to].disc, { scale: 1 }, { scale: 1.12, duration: 0.15, yoyo: true, repeat: 1, immediateRender: false }, T + 1.3);
        }
      } else if (st.do === "grow" || st.do === "shrink") {
        tl.fromTo(o.disc, { scale: 1 }, { scale: st.do === "grow" ? 1.22 : 0.72, duration: 0.6, ease: "power3.inOut", immediateRender: false }, T);
        if (st.value) {
          const val = o.val || (o.val = el("div", "cval", "", o.nd.querySelector(".ctx")));
          const p1 = numParts(o.a.value), p2 = numParts(st.value);
          if (p1 && p2 && p1.pre === p2.pre) {
            const box = { v: p1.n };
            tl.fromTo(box, { v: p1.n }, { v: p2.n, duration: 0.8, ease: "power2.out", immediateRender: false, onUpdate: () => { val.textContent = fmtNum(p2, box.v); } }, T);
          } else {
            tl.set(val, { textContent: st.value }, T + 0.3);
          }
          val.classList.add(st.do === "grow" ? "up" : "down");
        }
      } else if (st.do === "block") {
        if (st.to != null) {
          const lk = link(st.who, st.to, T - 0.3, false);
          tl.set(lk.ln, { attr: { class: "clink2 red" } }, T);
          const x = el("div", "cblock", null, stage); icon("x", 46, x);
          x.style.left = (lk.ax + lk.bx) / 2 + "px"; x.style.top = (lk.ay + lk.by) / 2 + "px";
          tl.fromTo(x, { opacity: 0, scale: 2.2, xPercent: -50, yPercent: -50 }, { opacity: 1, scale: 1, xPercent: -50, yPercent: -50, duration: 0.2, ease: "power4.in" }, T);
        } else {
          const bar = el("div", "cstrike", null, o.nd);
          tl.fromTo(bar, { scaleX: 0 }, { scaleX: 1, duration: 0.22, ease: "power4.out" }, T);
          tl.fromTo(o.nd, { x: 10 }, { x: 0, duration: 0.35, ease: "elastic.out(1, 0.3)", immediateRender: false }, T + 0.2);
        }
        if (st.label) { const st2 = el("div", "stamp mini", st.label, o.nd); tl.fromTo(st2, { opacity: 0, scale: 2.2, rotation: -16 }, { opacity: 1, scale: 1, rotation: -8, duration: 0.16, ease: "power4.in" }, T + 0.15); }
      } else if (st.do === "highlight") {
        tl.fromTo(o.disc, { "--glow": 0 }, { "--glow": 1, duration: 0.3, ease: "power2.out", immediateRender: false }, T);
        tl.fromTo(o.nd, { scale: 1 }, { scale: 1.08, duration: 0.3, ease: "back.out(2)", immediateRender: false }, T);
        dim(st.who, T);
        if (st.label) { const t2 = el("div", "ctag hl", st.label, o.nd); tl.fromTo(t2, { opacity: 0, y: -14 }, { opacity: 1, y: 0, duration: 0.25 }, T + 0.1); }
      } else if (st.do === "count") {
        const target = st.value || o.a.value, p = numParts(target);
        const val = o.val || (o.val = el("div", "cval", target || "", o.nd.querySelector(".ctx")));
        if (p) { const box = { v: 0 }; tl.fromTo(box, { v: 0 }, { v: p.n, duration: 1.0, ease: "power3.out", immediateRender: false, onUpdate: () => { val.textContent = fmtNum(p, box.v); } }, T); }
        tl.fromTo(val, { scale: 0.6 }, { scale: 1, duration: 0.4, ease: "back.out(2)", immediateRender: false }, T);
      }
    });
    c.stampTarget = stage; c.stampAt = Math.min(latest(c), (at.length ? Math.max(...at) : c.a(0.4)) + 0.6);
  };

  // -- world: a station of the 3D world where characters and objects act the story out
  // (world.js). The scene itself only carries the title; the world sits behind the window.
  const WORLD = window.CUWorld ? window.CUWorld({ tl, el, DECK, parts, partAt, latest, SH }) : null;
  S.world = (sc, s, c) => {
    const d = s.data || {};
    kick(sc, s);
    if (d.title) heading(sc, d.title, c.i === 0 ? 84 : 66, mh(c.i === 0 ? 260 : 150), d.mark); // the first beat's title is the hook
    c.a && introHead(sc, c.a, c.D, c.i === 0);
    if (!WORLD || !WORLD.station(sc, s, c)) { // no WebGL: the title alone still says it
      if (!d.title) heading(sc, (s.screens && s.screens[0]) || "", 96, mh(500));
    }
  };
  S._world = WORLD;

  // -- end card: logo, name, handle, the follow button ------------------------
  S.endcard = (sc, s, c) => {
    const { a } = c;
    sc.classList.add("centered", "endcard");
    const box = el("div", "elogo", null, sc);
    const rings = [el("div", "ering", null, box), el("div", "ering", null, box)];
    const img = image("assets/logo.png", box);
    const brand = el("div", "ebrand", DECK.brand, sc); fitW(brand, 858, 70, 40);
    const handle = el("div", "ehandle", "@" + DECK.handle, sc);
    const btn = el("div", "ebtn", ((s.screens && s.screens[0]) || "Follow for more").replace(/[.!]+$/, ""), sc);
    fit(btn, 150, 38, 26);
    tl.fromTo(img, { opacity: 0, scale: 0.3, rotation: -12 }, { opacity: 1, scale: 1, rotation: 0, duration: 0.45, ease: "back.out(2)" }, a(0));
    rings.forEach((r, i) => tl.fromTo(r, { opacity: 0.9, scale: 0.85 }, { opacity: 0, scale: 1.35, duration: 1.1, ease: "power1.out", repeat: Math.ceil(c.dur / 1.1), immediateRender: false }, a(0.25) + i * 0.55));
    tl.fromTo(brand, { opacity: 0, y: 30 }, { opacity: 1, y: 0, duration: 0.3, ease: "power3.out" }, a(0.2));
    tl.fromTo(handle, { opacity: 0 }, { opacity: 1, duration: 0.3 }, a(0.35));
    tl.fromTo(btn, { opacity: 0, y: 40, scale: 0.9 }, { opacity: 1, y: 0, scale: 1, duration: 0.35, ease: "back.out(2)" }, a(0.5));
  };

  return S;
};
