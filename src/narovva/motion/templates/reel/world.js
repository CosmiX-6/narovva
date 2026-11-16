/* The story world: small 3D dioramas where characters and objects act out what
 * the voice says -- people queue at a door and get turned away, money flows from
 * one building to another, a pile grows or drains, a crowd splits into winners
 * and losers. Everything is built from primitives in code (no models, no
 * textures to license), lit like clay, seen from an isometric camera.
 *
 * Seek-safe by construction: each set piece is `render(t)`, a pure function of
 * the time into its scene. One WebGL context is shared; each world scene draws
 * into its own 2D canvas, so any number of them can be on screen in transitions.
 *
 * window.CUWorld(K) -> { build(host, s, c) } where `host` is the scene's inner
 * element, `s` the slide spec (data.piece + its fields) and `c` the timing.
 */
window.CUWorld = function (K) {
  const { tl, el, DECK, parts, partAt, latest, SH } = K;
  const T3 = window.THREE;
  if (!T3) return null;

  const W = 1080;
  let H = 960; // set to the scene window's height on first use
  // One WebGL context for every world scene, made on first use (each scene copies its frame
  // into its own 2D canvas, so scenes on screen together in a transition never fight over it).
  let renderer = null;
  const gl = () => {
    if (!renderer) {
      renderer = new T3.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
      renderer.setPixelRatio(1);
      renderer.setSize(W, H, false);
      renderer.setClearColor(0x000000, 0);
      renderer.outputEncoding = T3.sRGBEncoding;
    }
    return renderer;
  };

  // -- palette: a clay world on a pale stage; ink for people, the story's accent for what matters
  const C = {
    ground: 0x141a2b, grid: 0x222b44, edge: 0x3a4566, ink: 0x2a3350, skin: 0xf4f1ec, white: 0xdfe5f0,
    grey: 0x8e9bb8, dark: 0x1b2135, red: 0xf43f5e, green: 0x22c55e, gold: 0xf5b301, glass: 0x7f9cc9,
    accent: new T3.Color(DECK.accent || "#3B82F6").getHex(),
  };
  const mats = {};
  const mat = (hex, rough) => {
    const key = hex + ":" + (rough || 0.85);
    if (!mats[key]) mats[key] = new T3.MeshStandardMaterial({ color: hex, roughness: rough || 0.85, metalness: 0 });
    return mats[key];
  };

  // -- deterministic helpers ----------------------------------------------------
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const lerp = (a, b, k) => a + (b - a) * k;
  const ease = (k) => (k <= 0 ? 0 : k >= 1 ? 1 : k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);
  const out = (k) => (k <= 0 ? 0 : k >= 1 ? 1 : 1 - Math.pow(1 - k, 3));
  const back = (k) => { if (k <= 0) return 0; if (k >= 1) return 1; const c1 = 1.70158, c3 = c1 + 1; return 1 + c3 * Math.pow(k - 1, 3) + c1 * Math.pow(k - 1, 2); };
  const prog = (t, a, d) => clamp((t - a) / Math.max(d, 1e-3), 0, 1);
  const hash = (i, s) => { let h = (i * 374761393 + (s || 0) * 668265263) | 0; h = Math.imul(h ^ (h >>> 13), 1274126177); return ((h ^ (h >>> 16)) >>> 0) / 4294967296; };

  // A point along a polyline (array of [x, z]) at fraction k of its length.
  const along = (pts, k) => {
    const seg = [];
    let total = 0;
    for (let i = 1; i < pts.length; i++) { const d = Math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]); seg.push(d); total += d; }
    let at = clamp(k, 0, 1) * total;
    for (let i = 0; i < seg.length; i++) {
      if (at <= seg[i] || i === seg.length - 1) {
        const f = seg[i] ? clamp(at / seg[i], 0, 1) : 0;
        return { x: lerp(pts[i][0], pts[i + 1][0], f), z: lerp(pts[i][1], pts[i + 1][1], f), dir: Math.atan2(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) };
      }
      at -= seg[i];
    }
    return { x: pts[0][0], z: pts[0][1], dir: 0 };
  };

  // -- the kit: every object is a THREE.Group standing on y = 0 --------------------
  const mesh = (geo, hex, rough) => { const m = new T3.Mesh(geo, mat(hex, rough)); return m; };
  const blob = (r) => { // a soft contact shadow (real shadows cost too much on CPU renders)
    const m = new T3.Mesh(new T3.CircleGeometry(r, 24), new T3.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.35, depthWrite: false }));
    m.rotation.x = -Math.PI / 2; m.position.y = 0.005; return m;
  };
  const KIT = {
    person(o) {
      o = o || {};
      const g = new T3.Group(), body = new T3.Group();
      const bodyCol = o.color != null ? o.color : C.ink;
      const torso = mesh(new T3.CapsuleGeometry(0.3, 0.42, 6, 14), bodyCol); torso.position.y = 0.62; body.add(torso);
      const head = mesh(new T3.SphereGeometry(0.27, 22, 16), o.head != null ? o.head : C.skin); head.position.y = 1.28; body.add(head);
      const eyeG = new T3.SphereGeometry(0.045, 10, 8);
      [-0.1, 0.1].forEach((x) => { const e = mesh(eyeG, C.ink, 0.4); e.position.set(x, 1.31, 0.245); body.add(e); });
      if (o.shades) { const s = mesh(new T3.BoxGeometry(0.42, 0.09, 0.06), 0x0b0e16, 0.3); s.position.set(0, 1.32, 0.25); body.add(s); }
      if (o.hat) { const h = mesh(new T3.CylinderGeometry(0.2, 0.24, 0.16, 18), o.hat); h.position.y = 1.55; body.add(h); }
      g.add(blob(0.36)); g.add(body); g.userData.body = body;
      return g;
    },
    building(o) {
      o = o || {};
      const g = new T3.Group(), w = o.w || 2.2, d = o.d || 1.8, h = o.h || 2.6;
      const b = mesh(new T3.BoxGeometry(w, h, d), o.color != null ? o.color : C.white); b.position.y = h / 2; g.add(b);
      const roof = mesh(new T3.BoxGeometry(w + 0.12, 0.14, d + 0.12), C.edge); roof.position.y = h + 0.07; g.add(roof);
      const winG = new T3.BoxGeometry(0.34, 0.42, 0.04);
      for (let r = 0; r < Math.floor(h / 0.8); r++) for (let k = 0; k < Math.floor(w / 0.6); k++) {
        const wdw = mesh(winG, C.glass, 0.3); wdw.position.set(-w / 2 + 0.38 + k * 0.6, 0.55 + r * 0.8, d / 2 + 0.01); g.add(wdw);
      }
      g.add(blob(Math.max(w, d) * 0.75));
      return g;
    },
    door(o) { // a doorway with a sign; the opening faces +z
      o = o || {};
      const g = new T3.Group();
      const postG = new T3.BoxGeometry(0.22, 2.2, 0.3);
      [-0.75, 0.75].forEach((x) => { const p = mesh(postG, C.dark); p.position.set(x, 1.1, 0); g.add(p); });
      const lintel = mesh(new T3.BoxGeometry(1.72, 0.24, 0.32), C.dark); lintel.position.y = 2.3; g.add(lintel);
      const wall = mesh(new T3.BoxGeometry(5.2, 2.42, 0.2), C.white); wall.position.set(0, 1.21, -0.25); g.add(wall);
      const hole = mesh(new T3.PlaneGeometry(1.28, 2.2), 0x10141f); hole.position.set(0, 1.1, -0.14); g.add(hole);
      if (o.sign) g.add(sign(o.sign, 2.6, 0.62, 3.0));
      g.add(blob(2.2));
      return g;
    },
    bar(o) { // a barrier arm that drops across the doorway
      const g = new T3.Group(), arm = new T3.Group();
      const post = mesh(new T3.BoxGeometry(0.2, 1.0, 0.2), C.dark); post.position.y = 0.5; g.add(post);
      const a = mesh(new T3.BoxGeometry(1.7, 0.14, 0.14), (o && o.color) || C.red); a.position.x = 0.85; arm.add(a);
      arm.position.y = 0.95; g.add(arm); g.userData.arm = arm;
      return g;
    },
    coin() { const g = new T3.Group(); const c = mesh(new T3.CylinderGeometry(0.26, 0.26, 0.09, 24), C.gold, 0.45); c.position.y = 0.045; g.add(c); return g; },
    box(o) { const g = new T3.Group(), s = (o && o.s) || 0.5; const b = mesh(new T3.BoxGeometry(s, s, s), (o && o.color) || 0xd9a066); b.position.y = s / 2; g.add(b); g.add(blob(s * 0.7)); return g; },
  };

  // A sign board: text painted onto a canvas texture.
  function sign(text, w, h, y) {
    const cv = document.createElement("canvas"); cv.width = 1024; cv.height = Math.round(1024 * h / w);
    const x = cv.getContext("2d");
    x.fillStyle = "#0B0F1C"; x.fillRect(0, 0, cv.width, cv.height);
    x.strokeStyle = DECK.accent || "#3B82F6"; x.lineWidth = 18; x.strokeRect(9, 9, cv.width - 18, cv.height - 18);
    let size = Math.round(cv.height * 0.56);
    x.font = `400 ${size}px "Archivo Black"`;
    while (x.measureText(text).width > cv.width * 0.86 && size > 20) { size -= 4; x.font = `400 ${size}px "Archivo Black"`; }
    x.fillStyle = "#FFFFFF"; x.textAlign = "center"; x.textBaseline = "middle"; x.fillText(text, cv.width / 2, cv.height / 2 + size * 0.04);
    const tex = new T3.CanvasTexture(cv); tex.encoding = T3.sRGBEncoding; tex.anisotropy = 4;
    const m = new T3.Mesh(new T3.BoxGeometry(w, h, 0.1), [mat(C.dark), mat(C.dark), mat(C.dark), mat(C.dark), new T3.MeshBasicMaterial({ map: tex }), mat(C.dark)]);
    m.position.set(0, y, 0.12);
    return m;
  }

  // -- the stage: a floating diorama tile, iso camera, clay light -------------------
  function stage() {
    const scene = new T3.Scene();
    scene.add(new T3.HemisphereLight(0xdfe8ff, 0x1a2036, 0.75));
    const key = new T3.DirectionalLight(0xfff1dc, 1.05); key.position.set(6, 11, 7); scene.add(key);
    const rim = new T3.DirectionalLight(new T3.Color(DECK.accent || "#3B82F6"), 0.55); rim.position.set(-8, 5, -7); scene.add(rim);
    const floor = mesh(new T3.PlaneGeometry(80, 80), C.ground, 0.95); floor.rotation.x = -Math.PI / 2; scene.add(floor);
    const grid = new T3.GridHelper(80, 80, C.grid, C.grid); grid.position.y = 0.003; scene.add(grid);
    const PPU = 88; // pixels per world unit at zoom 1: about 12 units across the frame
    const cam = new T3.OrthographicCamera(-W / 2 / PPU, W / 2 / PPU, H / 2 / PPU, -H / 2 / PPU, 0.1, 200);
    return { scene, cam };
  }
  // Isometric-ish camera looking at `target`; `zoom` > 1 moves in.
  function aim(cam, target, zoom, yaw) {
    const r = 30, pitch = 0.6, a = yaw == null ? Math.PI / 4 : yaw;
    cam.position.set(target.x + r * Math.cos(pitch) * Math.sin(a), target.y + r * Math.sin(pitch), target.z + r * Math.cos(pitch) * Math.cos(a));
    cam.zoom = zoom; cam.lookAt(target.x, target.y, target.z); cam.updateProjectionMatrix();
  }

  function paint(ctx, scene, cam) {
    const r = gl();
    r.render(scene, cam);
    ctx.clearRect(0, 0, W, H);
    ctx.drawImage(r.domElement, 0, 0);
  }

  // Labels drawn over the 3D frame, anchored to 3D points (tags like "83 / 100").
  function tag(ctx, cam, pos, text, o) {
    o = o || {};
    const v = new T3.Vector3(pos.x, pos.y, pos.z).project(cam);
    const x = (v.x * 0.5 + 0.5) * W, y = (-v.y * 0.5 + 0.5) * H;
    const size = o.size || 34;
    ctx.font = `700 ${size}px Inter`;
    const tw = ctx.measureText(text).width, pw = tw + size * 0.9, ph = size * 1.55;
    ctx.save();
    ctx.globalAlpha = o.alpha == null ? 1 : o.alpha;
    ctx.translate(x, y); const sc = o.scale == null ? 1 : o.scale; ctx.scale(sc, sc);
    ctx.fillStyle = o.fill || "#FFFFFF"; ctx.strokeStyle = o.stroke || "#1E2433"; ctx.lineWidth = 4;
    const r = 12, L = -pw / 2, Tp = -ph;
    ctx.beginPath(); ctx.moveTo(L + r, Tp); ctx.arcTo(L + pw, Tp, L + pw, Tp + ph, r); ctx.arcTo(L + pw, Tp + ph, L, Tp + ph, r);
    ctx.arcTo(L, Tp + ph, L, Tp, r); ctx.arcTo(L, Tp, L + pw, Tp, r); ctx.closePath(); ctx.fill(); ctx.stroke();
    ctx.fillStyle = o.color || "#1E2433"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(text, 0, Tp + ph / 2 + 1);
    ctx.restore();
  }

  // A walker: who moves along `path` from time a for d seconds (bobbing while moving).
  function walk(p, path, t, a, d, face) {
    const k = ease(prog(t, a, d)), pt = along(path, k);
    p.position.set(pt.x, 0, pt.z);
    p.rotation.y = face != null ? face : pt.dir;
    const moving = k > 0 && k < 1;
    const ph = (t - a) * 9;
    p.userData.body.position.y = moving ? Math.abs(Math.sin(ph)) * 0.08 : 0;
    p.userData.body.rotation.z = moving ? Math.sin(ph) * 0.06 : 0;
    return k;
  }

  // -- set pieces ------------------------------------------------------------
  // Each returns { draw(t, ctx) } with t = seconds into the scene; `cue(j)` is when
  // line j is spoken (seconds into the scene), `end` the last moment worth animating.
  const PIECES = {};

  // gate: a keeper lets the first few through a door, then the bar drops and the rest are
  // turned away. data: {gate: sign text, crowd: label on the queue, keeper: label on the
  // keeper, allowed: label on the way in, blocked: label on the turned-away, count: how many get in}
  PIECES.gate = (d, cue, end) => {
    const { scene, cam } = stage();
    const door = KIT.door({ sign: String(d.gate || "").toUpperCase().slice(0, 18) }); door.position.set(0, 0, -2.6); scene.add(door);
    const keeper = KIT.person({ color: 0x0b0e16, shades: true }); keeper.position.set(1.5, 0, -1.6); keeper.rotation.y = -0.5; scene.add(keeper);
    const bar = KIT.bar(); bar.position.set(-0.85, 0, -1.9); scene.add(bar);
    const N = 9, allowed = clamp(d.count || 3, 1, 6);
    const people = [];
    for (let i = 0; i < N; i++) {
      const p = KIT.person({ color: i < allowed ? C.accent : C.white, head: C.skin });
      scene.add(p); people.push(p);
    }
    const qx = (i) => -0.1 + (hash(i, 7) - 0.5) * 0.25;
    const slot = (i) => [qx(i), 0.2 + i * 0.95]; // the queue runs toward the camera from the door
    const t1 = cue(0), t2 = cue(1) != null ? cue(1) : t1 + Math.max(1.4, (end - t1) * 0.5);
    const gap = Math.max(0.25, Math.min(0.55, (t2 - t1 - 0.4) / allowed));
    const enterAt = (i) => t1 + 0.2 + i * gap;
    return {
      draw(t, ctx) {
        // camera: settles in from wide, then eases toward the door as the line plays out
        // camera: settles in, glides from the queue up to the door, pushes in when the bar drops
        const zIn = lerp(0.9, 1.0, out(prog(t, 0, 1.2))) * lerp(1, 1.15, ease(prog(t, t2, 1.4)));
        aim(cam, { x: 0.3, y: 2.2, z: lerp(2.8, 0.6, ease(prog(t, 0.3, Math.max(1, t2 - 0.3)))) }, zIn);
        people.forEach((p, i) => {
          const queued = slot(i);
          if (i < allowed) {
            // the allowed walk up, through the door and vanish into the dark
            const a = enterAt(i);
            walk(p, [queued, [0, -1.6], [0, -2.9]], t, a, 1.0);
            p.visible = t < a + 1.0;
          } else {
            // the rest shuffle up the queue, then bounce off the bar and turn away
            const j = i - allowed, shuffle = prog(t, t1 + 0.3, 1.2);
            const from = queued, to = slot(j);
            const z0 = lerp(from[1], to[1], ease(shuffle));
            const turned = prog(t, t2 + 0.35 + j * 0.08, 0.9);
            const side = j % 2 ? 1 : -1;
            const bump = Math.sin(clamp((t - t2 - 0.15) / 0.3, 0, 1) * Math.PI) * 0.35 * (j === 0 ? 1 : 0);
            p.position.set(lerp(to[0], to[0] + side * (1.6 + j * 0.3), ease(turned)), 0, z0 + bump + ease(turned) * (1.2 + hash(j, 3)));
            p.rotation.y = turned > 0 ? lerp(Math.PI, side * Math.PI / 2 + Math.PI, ease(turned)) : Math.PI;
            p.userData.body.position.y = shuffle > 0 && shuffle < 1 ? Math.abs(Math.sin(t * 9 + j)) * 0.06 : 0;
          }
        });
        // the bar drops on the second line
        bar.userData.arm.rotation.z = lerp(Math.PI / 2.1, 0, back(prog(t, t2, 0.45)));
        paint(ctx, scene, cam);
        const fadeIn = (a) => out(prog(t, a, 0.3));
        if (d.crowd) tag(ctx, cam, { x: 0, y: 2.0, z: 4.6 }, d.crowd, { alpha: fadeIn(0.4) });
        if (d.keeper) tag(ctx, cam, { x: 1.5, y: 2.1, z: -1.6 }, d.keeper, { alpha: fadeIn(t1), fill: "#1E2433", color: "#FFFFFF" });
        const inside = people.filter((p, i) => i < allowed && t >= enterAt(i) + 1.0).length;
        if (t > t1) tag(ctx, cam, { x: -1.6, y: 2.9, z: -2.4 }, `${d.allowed ? d.allowed + " " : "IN "}${inside}/${allowed}`, { alpha: fadeIn(t1 + 0.4), color: "#16A34A" });
        if (d.blocked && t > t2) tag(ctx, cam, { x: -2.2, y: 1.9, z: 2.2 }, d.blocked, { alpha: fadeIn(t2 + 0.5), fill: "#F43F5E", stroke: "#F43F5E", color: "#FFFFFF", scale: lerp(0.6, 1, back(prog(t, t2 + 0.5, 0.35))) });
      },
    };
  };

  // -- the scene builder ---------------------------------------------------------------
  function build(host, s, c) {
    const d = s.data || {};
    const make = PIECES[d.piece];
    if (!make) return false;
    try { gl(); } catch (e) { // no WebGL in this browser: the scene falls back to its title
      console.warn("world: WebGL unavailable", e);
      return false;
    }
    // The world fills the whole scene window behind the scene's title (a sibling of the
    // content, so the content's punch-ins don't scale it; it has its own camera).
    const win = document.getElementById("scenes");
    if (!renderer) H = win.offsetHeight;
    const box = el("div", "world", null);
    host.parentElement.insertBefore(box, host);
    host.parentElement.classList.add("has-world");
    box.setAttribute("data-layout-allow-overflow", ""); box.setAttribute("data-layout-allow-overlap", "");
    box.style.height = H + "px";
    const cv = el("canvas", null, null, box); cv.width = W; cv.height = H;
    const ctx = cv.getContext("2d");
    const n = parts(s).length;
    const cue = (j) => (j < n ? partAt(s, c, j) - c.t0 : null);
    const end = latest(c) - c.t0;
    const piece = make(d, cue, end);
    console.log("world: " + d.piece + " scene built (WebGL " + gl().capabilities.isWebGL2 + ")");
    const clock = { t: 0 };
    piece.draw(0, ctx);
    tl.fromTo(clock, { t: 0 }, { t: c.dur, duration: c.dur, ease: "none", onUpdate: () => piece.draw(clock.t, ctx) }, c.t0);
    tl.fromTo(box, { opacity: 0, y: 40 }, { opacity: 1, y: 0, duration: 0.4, ease: "power3.out" }, c.t0);
    return true;
  }

  return { build, pieces: Object.keys(PIECES) };
};
