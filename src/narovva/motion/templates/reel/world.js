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
      // arms hang from shoulder pivots, so poses are rotations of the pivots
      const armG = new T3.CapsuleGeometry(0.075, 0.34, 4, 8);
      const arms = [-1, 1].map((sx) => {
        const pivot = new T3.Group(); pivot.position.set(sx * 0.37, 0.98, 0);
        const a = mesh(armG, bodyCol); a.position.y = -0.24; pivot.add(a); body.add(pivot); return pivot;
      });
      g.add(blob(0.36)); g.add(body); g.userData.body = body; g.userData.arms = arms;
      return g;
    },
    orb() { // a packet of data: a small glowing sphere
      const g = new T3.Group();
      const o = new T3.Mesh(new T3.SphereGeometry(0.2, 16, 12), new T3.MeshBasicMaterial({ color: C.accent }));
      o.position.y = 0.35; g.add(o); g.add(blob(0.16)); return g;
    },
    barrel() {
      const g = new T3.Group();
      const b = mesh(new T3.CylinderGeometry(0.24, 0.24, 0.62, 18), 0x334155, 0.6); b.position.y = 0.31; g.add(b);
      [0.14, 0.48].forEach((y) => { const r = mesh(new T3.TorusGeometry(0.245, 0.025, 6, 18), C.gold, 0.5); r.rotation.x = Math.PI / 2; r.position.y = y; g.add(r); });
      g.add(blob(0.3)); return g;
    },
    chip() {
      const g = new T3.Group();
      const b = mesh(new T3.BoxGeometry(0.52, 0.08, 0.52), 0x1f2937, 0.4); b.position.y = 0.06; g.add(b);
      const die = mesh(new T3.BoxGeometry(0.26, 0.04, 0.26), C.accent, 0.3); die.position.y = 0.12; g.add(die);
      const pinG = new T3.BoxGeometry(0.05, 0.03, 0.1);
      for (let k = 0; k < 4; k++) [[-1, 0], [1, 0], [0, -1], [0, 1]].forEach(([sx, sz]) => {
        const p = mesh(pinG, C.grey, 0.4);
        if (sx) { p.position.set(sx * 0.3, 0.04, -0.18 + k * 0.12); p.rotation.y = Math.PI / 2; } else p.position.set(-0.18 + k * 0.12, 0.04, sz * 0.3);
        g.add(p);
      });
      g.add(blob(0.36)); return g;
    },
    doc() {
      const g = new T3.Group();
      const p = mesh(new T3.BoxGeometry(0.42, 0.04, 0.56), C.white, 0.9); p.position.y = 0.05; g.add(p);
      for (let k = 0; k < 4; k++) { const l = mesh(new T3.BoxGeometry(0.28, 0.01, 0.03), C.grey); l.position.set(0, 0.075, -0.18 + k * 0.1); g.add(l); }
      g.add(blob(0.3)); return g;
    },
    platform(o) { // a low glowing pad that a group gathers on
      const g = new T3.Group(), r = (o && o.r) || 1.6;
      const p = mesh(new T3.CylinderGeometry(r, r * 1.04, 0.16, 40), (o && o.color) || C.edge, 0.6); p.position.y = 0.08; g.add(p);
      const ring = new T3.Mesh(new T3.TorusGeometry(r * 0.98, 0.04, 6, 48), new T3.MeshBasicMaterial({ color: (o && o.color) || C.edge }));
      ring.rotation.x = Math.PI / 2; ring.position.y = 0.17; g.add(ring);
      return g;
    },
    flag(o) {
      const g = new T3.Group();
      const pole = mesh(new T3.CylinderGeometry(0.04, 0.04, 1.9, 8), C.grey); pole.position.y = 0.95; g.add(pole);
      const f = mesh(new T3.BoxGeometry(0.62, 0.4, 0.03), (o && o.color) || C.accent); f.position.set(0.33, 1.68, 0); g.add(f);
      g.add(blob(0.2)); return g;
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

  // Repaint a character's clothes (torso and arms).
  function tint(p, hex) {
    const m = mat(hex), b = p.userData.body;
    b.children[0].material = m;
    (p.userData.arms || []).forEach((a) => { a.children[0].material = m; });
  }

  // The camera sits at +x +z, so this yaw turns a character to face the viewer.
  const FACE = Math.PI / 4;

  // A pose, blended in by k (0..1): "idle", "walk" (arms swing with phase ph), "cheer" (arms up,
  // a hop), "slump" (head and shoulders drop), "point" (one arm out).
  function pose(p, kind, k, ph) {
    const [L, R] = p.userData.arms || [], b = p.userData.body;
    if (!L) return;
    k = clamp(k == null ? 1 : k, 0, 1);
    L.rotation.set(0, 0, 0); R.rotation.set(0, 0, 0); b.rotation.x = 0;
    if (kind === "walk") { const s = Math.sin(ph || 0) * 0.7 * k; L.rotation.x = s; R.rotation.x = -s; }
    else if (kind === "cheer") {
      L.rotation.z = -2.6 * k; R.rotation.z = 2.6 * k;
      const wave = Math.sin((ph || 0) * 1.5) * 0.25 * k; L.rotation.z -= wave; R.rotation.z += wave;
      b.position.y = Math.abs(Math.sin((ph || 0) * 1.2)) * 0.18 * k;
    } else if (kind === "slump") { b.rotation.x = 0.28 * k; L.rotation.z = 0.15 * k; R.rotation.z = -0.15 * k; }
    else if (kind === "point") { R.rotation.x = -1.4 * k; }
  }

  // A walker: who moves along `path` from time a for d seconds (bobbing and swinging its
  // arms while moving), then turns to face `face` (or the viewer) once it arrives.
  function walk(p, path, t, a, d, face) {
    const k = ease(prog(t, a, d)), pt = along(path, k);
    p.position.set(pt.x, 0, pt.z);
    const moving = k > 0 && k < 1;
    const settle = out(prog(t, a + d, 0.4));
    const goal = face != null ? face : FACE;
    p.rotation.y = k >= 1 ? lerp(pt.dir, goal, settle) : pt.dir;
    const ph = (t - a) * 9;
    p.userData.body.position.y = moving ? Math.abs(Math.sin(ph)) * 0.08 : 0;
    p.userData.body.rotation.z = moving ? Math.sin(ph) * 0.06 : 0;
    pose(p, moving ? "walk" : "idle", 1, ph);
    return k;
  }

  // Items that travel along a path: spawn times `spawns`, each taking `d` seconds; returns per
  // item {f, alive} at time t (f = 0..1 along the path).
  const travel = (spawns, t, d) => spawns.map((s) => { const f = (t - s) / d; return { f: clamp(f, 0, 1), alive: f >= 0 && f <= 1 }; });
  const spawnTimes = (a, b, gap, max) => { const out = []; for (let s = a; s < b && out.length < max; s += gap) out.push(s); return out; };

  // A text label for an item kind; the object to build for it.
  const ITEM = { money: "coin", goods: "box", data: "orb", people: "person", oil: "barrel", chips: "chip", documents: "doc" };
  const item = (kind, o) => (kind === "people" ? KIT.person(Object.assign({ color: C.white }, o)) : KIT[ITEM[kind] || "box"](o));

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

  // Shared timing: line 1 starts the action, line 2 (or halfway through) is the turn.
  const beats = (cue, end) => {
    const t1 = cue(0) || 0.15;
    const t2 = cue(1) != null ? cue(1) : t1 + Math.max(1.4, (end - t1) * 0.5);
    return { t1, t2 };
  };
  const pop = (t, a) => back(prog(t, a, 0.35)); // a label's scale as it lands
  const GREEN = { fill: "#16A34A", stroke: "#16A34A", color: "#FFFFFF" }, RED = { fill: "#F43F5E", stroke: "#F43F5E", color: "#FFFFFF" };
  const DARK = { fill: "#0B0F1C", stroke: "#3A4566", color: "#FFFFFF" };

  // flow: things travel from one place to another -- money to a company, chips to a
  // country, data to a server. At the turn the flow grows, stops at a barrier, or reverses.
  // data: {from, to, item, amount, change: "grows" | "stops" | "reverses" | "none"}
  PIECES.flow = (d, cue, end) => {
    const { scene, cam } = stage();
    const A = { x: -3.6, z: 1.6 }, B = { x: 3.4, z: -1.8 };
    const ba = KIT.building({ w: 2.0, h: 2.0 }); ba.position.set(A.x - 1.3, 0, A.z); scene.add(ba);
    const bb = KIT.building({ w: 2.2, h: 3.2, color: 0xc9d4ea }); bb.position.set(B.x + 1.3, 0, B.z); scene.add(bb);
    const road = mesh(new T3.BoxGeometry(9.2, 0.04, 1.1), 0x1f2740, 0.9);
    road.position.set((A.x + B.x) / 2, 0.02, (A.z + B.z) / 2); road.rotation.y = -Math.atan2(B.z - A.z, B.x - A.x); scene.add(road);
    const { t1, t2 } = beats(cue, end);
    const change = d.change || "none", D = 2.2;
    const gap1 = 0.42, gap2 = change === "grows" ? 0.18 : gap1;
    let spawns = spawnTimes(t1 - 0.2, Math.min(t2, end), gap1, 40);
    if (change === "grows" || change === "none") spawns = spawns.concat(spawnTimes(t2, end, gap2, 40));
    const back2 = change === "reverses" ? spawnTimes(t2 + 0.2, end, gap1, 20) : [];
    const items = spawns.concat(back2).map(() => { const it = item(d.item); scene.add(it); return it; });
    const fb = 0.55; // where a stopping barrier stands along the road
    let wall = null;
    if (change === "stops") {
      wall = mesh(new T3.BoxGeometry(0.25, 1.1, 1.5), C.red, 0.6);
      wall.position.set(lerp(A.x, B.x, fb), 0.55, lerp(A.z, B.z, fb)); wall.rotation.y = road.rotation.y; scene.add(wall);
    }
    return {
      draw(t, ctx) {
        aim(cam, { x: 0.2, y: 2.4, z: 0 }, lerp(0.92, 1.0, out(prog(t, 0, 1.2))) * lerp(1, 1.08, ease(prog(t, t2, 1.2))));
        let blocked = 0;
        items.forEach((it, i) => {
          const rev = i >= spawns.length, s = rev ? back2[i - spawns.length] : spawns[i];
          let f = (t - s) / D;
          if (change === "stops" && !rev && s + D * fb > t2) { // reaches the barrier after it is up: queue at it
            const rank = blocked++;
            f = Math.min(f, fb - 0.04 - rank * 0.045);
          }
          it.visible = f >= 0 && f <= 1;
          if (!it.visible) return;
          const k = rev ? 1 - f : f, hop = Math.sin(clamp(f, 0, 1) * Math.PI * 6) * 0.04;
          it.position.set(lerp(A.x, B.x, k), Math.abs(hop), lerp(A.z, B.z, k));
          if (d.item === "people") { it.rotation.y = rev ? Math.PI * 0.75 : -Math.PI * 0.25; pose(it, "walk", 1, t * 9 + i); }
          else it.rotation.y = t * 1.5 + i;
        });
        if (wall) { const k = back(prog(t, t2, 0.4)); wall.scale.set(1, Math.max(0.001, k), 1); wall.position.y = 0.55 * k; }
        paint(ctx, scene, cam);
        if (d.from) tag(ctx, cam, { x: A.x - 1.3, y: 2.9, z: A.z }, d.from, { alpha: out(prog(t, 0.2, 0.3)) });
        if (d.to) tag(ctx, cam, { x: B.x + 1.3, y: 4.0, z: B.z }, d.to, { alpha: out(prog(t, 0.35, 0.3)) });
        if (d.amount) {
          const at = change === "none" ? t1 + 0.6 : t2 + 0.3;
          const o = change === "stops" ? RED : change === "grows" ? GREEN : DARK;
          tag(ctx, cam, { x: (A.x + B.x) / 2, y: 2.1, z: (A.z + B.z) / 2 }, d.amount, Object.assign({ alpha: out(prog(t, at, 0.2)), scale: lerp(0.6, 1, pop(t, at)), size: 40 }, o));
        }
      },
    };
  };

  // pile: a stock of something grows or drains -- reserves, inventory, prices as coins.
  // data: {item, label, start, end, ratio (end / start), trend: "up" | "down"}
  PIECES.pile = (d, cue, end) => {
    const { scene, cam } = stage();
    const { t1, t2 } = beats(cue, end);
    const up = d.trend !== "down";
    const n0 = up ? 8 : 24;
    const n1 = clamp(Math.round(n0 * (d.ratio || (up ? 2.2 : 0.35))), 1, 36);
    const N = Math.max(n0, n1);
    const kind = d.item || "money", h = kind === "money" ? 0.1 : kind === "goods" ? 0.5 : kind === "oil" ? 0.64 : 0.12;
    const cols = 3, stacks = 9;
    const slot = (i) => { const s = i % stacks, lvl = Math.floor(i / stacks); return { x: (s % cols - 1) * 0.72, z: (Math.floor(s / cols) - 1) * 0.72, y: lvl * h }; };
    const items = Array.from({ length: N }, () => { const it = item(kind); scene.add(it); return it; });
    const watcher = KIT.person({ color: C.ink }); watcher.position.set(2.2, 0, 1.4); watcher.rotation.y = -Math.PI * 0.6; scene.add(watcher);
    const inAt = (i) => t1 + 0.1 + (i / n0) * Math.min(1.6, (t2 - t1) * 0.8);
    const changeAt = (i) => t2 + 0.1 + ((i - (up ? n0 : n1)) / Math.max(1, Math.abs(n1 - n0))) * Math.min(1.8, (end - t2) * 0.7);
    return {
      draw(t, ctx) {
        aim(cam, { x: 0.3, y: 2.6, z: 0.4 }, lerp(1.25, 1.4, ease(prog(t, 0, end))));
        items.forEach((it, i) => {
          const p = slot(i);
          let k = 0, gone = 0;
          if (i < n0) k = prog(t, inAt(i), 0.35);
          if (up && i >= n0) k = prog(t, changeAt(i), 0.35);
          if (!up && i >= n1 && i < n0) gone = prog(t, t2 + 0.1 + ((n0 - 1 - i) / Math.max(1, n0 - n1)) * Math.min(1.8, (end - t2) * 0.7), 0.4);
          it.visible = k > 0 && gone < 1;
          const drop = (1 - out(k)) * 2.2 + out(gone) * 2.5;
          it.position.set(p.x, p.y + drop, p.z);
          it.rotation.y = (i * 0.7) % 1;
          it.scale.setScalar(1 - gone * 0.6);
        });
        pose(watcher, up ? "cheer" : "slump", prog(t, t2 + 0.5, 0.5), t * 6);
        paint(ctx, scene, cam);
        if (d.label) tag(ctx, cam, { x: 0, y: 1.9 + (up ? 0.6 : 0), z: 0 }, d.label, { alpha: out(prog(t, t1, 0.3)) });
        const before = d.start, after = d.end;
        if (before && t < t2 + 0.3) tag(ctx, cam, { x: -1.5, y: 1.2, z: 1.5 }, before, Object.assign({ alpha: out(prog(t, t1 + 0.5, 0.25)), size: 42 }, DARK));
        if (after && t >= t2 + 0.3) tag(ctx, cam, { x: -1.5, y: 1.2, z: 1.5 }, after, Object.assign({ scale: lerp(0.5, 1, pop(t, t2 + 0.3)), size: 46 }, up ? GREEN : RED));
      },
    };
  };

  // race: two or three rivals run; the leader pulls away and crosses the line first.
  // data: {lanes: [label, ...], leader: index}
  PIECES.race = (d, cue, end) => {
    const { scene, cam } = stage();
    const { t1, t2 } = beats(cue, end);
    const lanes = (d.lanes || []).slice(0, 3), n = lanes.length, lead = clamp(d.leader || 0, 0, n - 1);
    const x0 = -4.4, x1 = 3.8, laneZ = (i) => (i - (n - 1) / 2) * 1.5;
    for (let i = 0; i <= n; i++) { const l = mesh(new T3.BoxGeometry(9.6, 0.03, 0.06), C.edge); l.position.set(-0.3, 0.02, laneZ(i) - 0.75); scene.add(l); }
    const fin = mesh(new T3.BoxGeometry(0.18, 0.04, n * 1.5), C.white); fin.position.set(x1, 0.03, 0); scene.add(fin);
    const fl = KIT.flag({ color: C.accent }); fl.position.set(x1 + 0.3, 0, laneZ(n - 1) + 0.9); scene.add(fl);
    const runners = lanes.map((_, i) => { const p = KIT.person({ color: i === lead ? C.accent : C.white }); scene.add(p); return p; });
    const speed = (i) => (i === lead ? 1 : 0.55 + 0.25 * hash(i, 11));
    return {
      draw(t, ctx) {
        aim(cam, { x: lerp(-1.2, 1.4, ease(prog(t, t1, end - t1))), y: 2.4, z: 0 }, 1.1);
        runners.forEach((p, i) => {
          const k = prog(t, t1, Math.max(1, t2 + 0.4 - t1)), dist = ease(k) * speed(i);
          p.position.set(lerp(x0, x1 + 0.6, dist), 0, laneZ(i));
          const running = k > 0 && k < 1;
          p.rotation.y = running ? Math.PI / 2 : FACE;
          const ph = t * 11 + i;
          p.userData.body.position.y = running ? Math.abs(Math.sin(ph)) * 0.12 : 0;
          if (running) pose(p, "walk", 1, ph);
          else pose(p, i === lead ? "cheer" : k >= 1 ? "slump" : "idle", prog(t, t2 + 0.4, 0.4), ph);
        });
        paint(ctx, scene, cam);
        runners.forEach((p, i) => tag(ctx, cam, { x: p.position.x, y: 2.1, z: p.position.z }, lanes[i],
          Object.assign({ alpha: out(prog(t, 0.2 + i * 0.1, 0.3)), size: 30 }, i === lead && t > t2 + 0.4 ? GREEN : {})));
      },
    };
  };

  // split: one crowd divides into the side that wins and the side that pays.
  // data: {crowd, win, lose, share (of the crowd that wins, 0.2-0.8)}
  PIECES.split = (d, cue, end) => {
    const { scene, cam } = stage();
    const { t1, t2 } = beats(cue, end);
    const L = KIT.platform({ color: 0x15803d, r: 1.7 }); L.position.set(-3.0, 0, 1.4); scene.add(L);
    const R = KIT.platform({ color: 0xbe123c, r: 1.7 }); R.position.set(3.0, 0, -1.4); scene.add(R);
    const N = 12, wins = clamp(Math.round(N * (d.share || 0.5)), 2, N - 2);
    const people = Array.from({ length: N }, () => { const p = KIT.person({ color: C.white }); scene.add(p); return p; });
    const home = (i) => [(hash(i, 1) - 0.5) * 2.2, (hash(i, 2) - 0.5) * 2.2];
    const dest = (i) => { const w = i < wins, j = w ? i : i - wins, c = w ? [-3.0, 1.4] : [3.0, -1.4], a = j * 2.4; return [c[0] + Math.cos(a) * 0.4 * Math.sqrt(j), c[1] + Math.sin(a) * 0.4 * Math.sqrt(j)]; };
    return {
      draw(t, ctx) {
        aim(cam, { x: 0, y: 2.4, z: 0 }, lerp(1.25, 1.05, ease(prog(t, t2, 1.2))));
        people.forEach((p, i) => {
          const h = home(i);
          const k = walk(p, [h, dest(i)], t, t2 + 0.05 + hash(i, 5) * 0.4, 1.1, FACE);
          if (k <= 0) { p.position.set(h[0], 0, h[1]); p.rotation.y = FACE + (hash(i, 9) - 0.5) * 0.8; pose(p, "idle"); }
          if (k >= 1) pose(p, i < wins ? "cheer" : "slump", prog(t, t2 + 1.4, 0.4), t * 6 + i);
          tint(p, k >= 1 ? (i < wins ? C.green : C.red) : C.white); // set every frame: seek-safe
        });
        paint(ctx, scene, cam);
        if (d.crowd) tag(ctx, cam, { x: 0, y: 2.2, z: 0 }, d.crowd, { alpha: out(prog(t, t1, 0.3)) * (1 - prog(t, t2, 0.3)) });
        if (d.win) tag(ctx, cam, { x: -3.0, y: 2.4, z: 1.4 }, d.win, Object.assign({ alpha: out(prog(t, t2 + 0.9, 0.2)), scale: lerp(0.6, 1, pop(t, t2 + 0.9)) }, GREEN));
        if (d.lose) tag(ctx, cam, { x: 3.0, y: 2.4, z: -1.4 }, d.lose, Object.assign({ alpha: out(prog(t, t2 + 1.1, 0.2)), scale: lerp(0.6, 1, pop(t, t2 + 1.1)) }, RED));
      },
    };
  };

  // machine: inputs go in one side, outputs come out the other -- how a product, a law or a
  // market turns one thing into another. data: {input, machine, output, in_item, out_item}
  PIECES.machine = (d, cue, end) => {
    const { scene, cam } = stage();
    const { t1, t2 } = beats(cue, end);
    const belt = mesh(new T3.BoxGeometry(10, 0.3, 1.1), 0x1f2740, 0.7); belt.position.set(0, 0.15, 0); scene.add(belt);
    const box = mesh(new T3.BoxGeometry(2.4, 2.2, 1.9), C.white, 0.6); box.position.set(0, 1.1, 0); scene.add(box);
    const s = sign(String(d.machine || "").toUpperCase().slice(0, 18), 2.4, 0.6, 2.6); s.position.z = 0.96; scene.add(s);
    const lights = [-0.6, 0, 0.6].map((x) => { const l = new T3.Mesh(new T3.SphereGeometry(0.11, 12, 8), new T3.MeshBasicMaterial({ color: C.accent })); l.position.set(x, 1.6, 0.97); scene.add(l); return l; });
    const gear = mesh(new T3.TorusGeometry(0.34, 0.09, 6, 10), C.edge, 0.5); gear.position.set(0, 0.85, 0.98); scene.add(gear);
    const D = 2.0, ins = spawnTimes(t1 - 0.4, end, 0.55, 30), outs = ins.map((s2) => s2 + D + 0.25);
    const inItems = ins.map(() => { const it = item(d.in_item || "goods"); scene.add(it); return it; });
    const outItems = outs.map(() => { const it = item(d.out_item || "money"); scene.add(it); return it; });
    return {
      draw(t, ctx) {
        aim(cam, { x: lerp(-1.2, 1.2, ease(prog(t, t1, end - t1))), y: 2.6, z: 0 }, 1.12);
        inItems.forEach((it, i) => { const f = (t - ins[i]) / D; it.visible = f >= 0 && f < 1; it.position.set(lerp(-5, -0.4, f), 0.3, 0); });
        outItems.forEach((it, i) => { const f = (t - outs[i]) / D; it.visible = f >= 0 && f < 1 && outs[i] >= t2 - D * 0.5; it.position.set(lerp(0.4, 5, f), 0.3, 0); });
        lights.forEach((l, i) => { l.visible = Math.floor(t * 4 + i) % 3 !== 0; });
        gear.rotation.z = -t * 3;
        box.scale.set(1, 1 + Math.max(0, Math.sin(t * 9)) * 0.02 * prog(t, t1, 0.3), 1);
        paint(ctx, scene, cam);
        if (d.input) tag(ctx, cam, { x: -3.6, y: 1.5, z: 0 }, d.input, { alpha: out(prog(t, t1, 0.3)) });
        if (d.output) tag(ctx, cam, { x: 3.6, y: 1.5, z: 0 }, d.output, Object.assign({ alpha: out(prog(t, t2, 0.25)), scale: lerp(0.6, 1, pop(t, t2)) }, GREEN));
      },
    };
  };

  // wall: traffic crosses freely, then a wall goes up and stops it -- a ban, a tariff, sanctions.
  // data: {left, right, wall, item}
  PIECES.wall = (d, cue, end) => {
    const { scene, cam } = stage();
    const { t1, t2 } = beats(cue, end);
    const A = KIT.platform({ color: C.edge, r: 1.6 }); A.position.set(-3.4, 0, 1.4); scene.add(A);
    const B = KIT.platform({ color: C.edge, r: 1.6 }); B.position.set(3.4, 0, -1.4); scene.add(B);
    const w = mesh(new T3.BoxGeometry(0.35, 2.0, 4.6), 0x64748b, 0.7); w.rotation.y = Math.atan2(2.8, 6.8); scene.add(w);
    const ws = sign(String(d.wall || "").toUpperCase().slice(0, 16), 3.2, 0.62, 2.45); ws.rotation.y = w.rotation.y + Math.PI / 2; ws.position.x = 0.24; scene.add(ws);
    const D = 2.4, spawns = spawnTimes(t1 - 0.3, end, 0.5, 28);
    const items = spawns.map(() => { const it = item(d.item || "goods"); scene.add(it); return it; });
    return {
      draw(t, ctx) {
        aim(cam, { x: 0, y: 2.4, z: 0 }, lerp(1.0, 1.15, ease(prog(t, t2, 1.2))));
        const k = back(prog(t, t2, 0.5));
        w.scale.set(1, Math.max(0.001, k), 1); w.position.y = k; ws.visible = k > 0.6; ws.position.y = 2.45 * k / 1.0;
        let q = 0;
        items.forEach((it, i) => {
          let f = (t - spawns[i]) / D;
          if (spawns[i] + D * 0.5 > t2 + 0.2) f = Math.min(f, 0.42 - (q++) * 0.05); // stuck behind the wall
          it.visible = f >= 0 && f <= 1 && f > -0.3;
          it.position.set(lerp(-3.4, 3.4, f), 0.17, lerp(1.4, -1.4, f));
          if (d.item === "people") { it.rotation.y = -Math.PI * 0.35; pose(it, f < 0.42 || f >= 1 ? "walk" : "idle", 1, t * 9 + i); }
          else it.rotation.y = i;
        });
        paint(ctx, scene, cam);
        if (d.left) tag(ctx, cam, { x: -3.4, y: 1.6, z: 1.4 }, d.left, { alpha: out(prog(t, 0.2, 0.3)) });
        if (d.right) tag(ctx, cam, { x: 3.4, y: 1.6, z: -1.4 }, d.right, { alpha: out(prog(t, 0.35, 0.3)) });
      },
    };
  };

  // balance: two sides weighed against each other; the scale tips to the heavier one.
  // data: {left, right, heavier: "left" | "right"}
  PIECES.balance = (d, cue, end) => {
    const { scene, cam } = stage();
    const { t1, t2 } = beats(cue, end);
    const base = mesh(new T3.ConeGeometry(0.6, 1.4, 4), C.edge, 0.6); base.position.y = 0.7; scene.add(base);
    // the beam runs across the screen (perpendicular to the view), so level reads as level
    const holder = new T3.Group(); holder.rotation.y = Math.PI / 4; scene.add(holder);
    const beam = new T3.Group(); beam.position.y = 1.45; holder.add(beam);
    const bar = mesh(new T3.BoxGeometry(6.4, 0.16, 0.3), C.white, 0.5); beam.add(bar);
    const pans = [-1, 1].map((sx) => { const p = new T3.Group(); p.position.x = sx * 3.0; const pl = mesh(new T3.CylinderGeometry(0.95, 0.8, 0.12, 28), C.white, 0.5); pl.position.y = 0.12; p.add(pl); beam.add(p); return p; });
    const heavyR = d.heavier === "right", side = heavyR ? 1 : 0;
    const weights = [0, 1].map((s) => Array.from({ length: s === side ? 5 : 2 }, (_, i) => { const b = KIT.box({ s: 0.42, color: s === 0 ? C.accent : 0xc9d4ea }); pans[s].add(b); b.position.set((i % 2 - 0.5) * 0.48, 0.18 + Math.floor(i / 2) * 0.42, 0); return b; }));
    return {
      draw(t, ctx) {
        aim(cam, { x: 0, y: 2.6, z: 0 }, 1.18);
        weights.forEach((ws2, s) => ws2.forEach((b, i) => {
          const at = i < 2 ? t1 + 0.15 + (s * 2 + i) * 0.18 : t2 + (i - 2) * 0.22;
          const k = prog(t, at, 0.35);
          b.visible = k > 0; b.position.y = 0.18 + Math.floor(i / 2) * 0.42 + (1 - out(k)) * 2.5;
        }));
        const tilt = 0.32 * back(prog(t, t2 + 0.5, 0.8)) * (heavyR ? -1 : 1);
        beam.rotation.z = tilt; pans.forEach((p) => { p.rotation.z = -tilt; });
        paint(ctx, scene, cam);
        const pt = (s) => { const v = new T3.Vector3(); pans[s].getWorldPosition(v); return { x: v.x, y: v.y + 1.9, z: v.z }; };
        if (d.left) tag(ctx, cam, pt(0), d.left, Object.assign({ alpha: out(prog(t, t1, 0.3)) }, !heavyR && t > t2 + 0.9 ? GREEN : {}));
        if (d.right) tag(ctx, cam, pt(1), d.right, Object.assign({ alpha: out(prog(t, t1 + 0.15, 0.3)) }, heavyR && t > t2 + 0.9 ? GREEN : {}));
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
