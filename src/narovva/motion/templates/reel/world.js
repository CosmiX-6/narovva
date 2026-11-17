/* The story world: small 3D dioramas where characters and objects act out what
 * the voice says -- people queue at a door and get turned away, money flows from
 * one building to another, a pile grows or drains, a crowd splits into winners
 * and losers. Everything is built from primitives in code (no models, no
 * textures to license), lit like clay, seen from an isometric camera.
 *
 * Seek-safe by construction: each set piece is `draw(t)`, a pure function of the
 * time into its beat, and the world's frame is a pure function of reel time.
 *
 * window.CUWorld(K) -> { station(host, s, c), start(total) }: each world beat adds its set
 * piece as a station of one continuous world (see "the world builder" at the end), and
 * start() puts the world on screen once every scene is built.
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

  // -- one continuous world ---------------------------------------------------------
  // Every world beat is a station in ONE world: its set piece is built at its own spot on a
  // long floor, and the camera glides from station to station as the story moves on (the
  // places already visited keep their final state, so the world remembers the story).
  // While a piece is being built, stage() hands it its station: a group placed at the
  // station's spot and a camera proxy that records where the piece wants to look.
  let ST = null;
  function stage() { return { scene: ST.group, cam: ST.cam }; }
  // Records the camera the piece wants (`target` in the piece's own coordinates).
  function aim(cam, target, zoom, yaw) {
    cam.state = { x: target.x + cam.off.x, y: target.y, z: target.z + cam.off.z, zoom, yaw: yaw == null ? Math.PI / 4 : yaw };
  }
  // Isometric-ish camera looking at `s` (world coordinates); zoom > 1 moves in.
  function point(cam, s) {
    const r = 30, pitch = 0.6, a = s.yaw;
    cam.position.set(s.x + r * Math.cos(pitch) * Math.sin(a), s.y + r * Math.sin(pitch), s.z + r * Math.cos(pitch) * Math.cos(a));
    cam.zoom = s.zoom; cam.lookAt(s.x, s.y, s.z); cam.updateProjectionMatrix();
  }
  function paint() {} // the world paints once a frame, for every station (see frame())

  // Labels drawn over the 3D frame, anchored to 3D points (tags like "83 / 100").
  function tag(ctx, cam, pos, text, o) {
    cam.labels.push([{ x: pos.x + cam.off.x, y: pos.y, z: pos.z + cam.off.z }, text, o || {}]);
  }
  function drawTag(ctx, cam, pos, text, o, fade) {
    o = Object.assign({}, o, { alpha: (o.alpha == null ? 1 : o.alpha) * fade });
    if (o.alpha <= 0.01) return;
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
        const pt = (s) => { const v = new T3.Vector3(); pans[s].getWorldPosition(v); scene.worldToLocal(v); return { x: v.x, y: v.y + 1.9, z: v.z }; };
        if (d.left) tag(ctx, cam, pt(0), d.left, Object.assign({ alpha: out(prog(t, t1, 0.3)) }, !heavyR && t > t2 + 0.9 ? GREEN : {}));
        if (d.right) tag(ctx, cam, pt(1), d.right, Object.assign({ alpha: out(prog(t, t1 + 0.15, 0.3)) }, heavyR && t > t2 + 0.9 ? GREEN : {}));
      },
    };
  };

  // -- layout in screen terms: `at(sx, sy)` is the ground point sx units to the right of the
  // piece's centre and sy units down the screen (toward the viewer). Rows built with it read
  // straight across the frame instead of along the isometric diagonal.
  const at = (sx, sy) => ({ x: (sx + sy) * Math.SQRT1_2, z: (sy - sx) * Math.SQRT1_2 });
  const put = (o, sx, sy, y) => { const p = at(sx, sy); o.position.set(p.x, y || 0, p.z); return o; };
  const glow = (hex) => new T3.MeshBasicMaterial({ color: hex });
  const LIT = glow(C.accent), UNLIT = mat(C.edge, 0.6);
  const ACROSS = Math.PI / 4; // turns a box so its length runs across the screen
  // When step i of n happens: on its own spoken line when the beat has one per step, else
  // spread evenly from line 1 to most of the way through the beat.
  const stepAt = (cue, end, i, n) => {
    if (cue(i) != null && cue(n - 1) != null) return cue(i);
    const t1 = cue(0) || 0.15;
    return t1 + (i / Math.max(1, n - 1)) * Math.min(Math.max(0.6 * n, (end - t1) * 0.72), Math.max(0.5, end - t1 - 0.8));
  };

  Object.assign(KIT, {
    pill() {
      const g = new T3.Group();
      const a = mesh(new T3.CapsuleGeometry(0.13, 0.32, 4, 12), C.white, 0.4); a.rotation.z = Math.PI / 2; a.position.y = 0.14; g.add(a);
      const b = mesh(new T3.CylinderGeometry(0.135, 0.135, 0.2, 14), C.accent, 0.4); b.rotation.z = Math.PI / 2; b.position.set(0.1, 0.14, 0); g.add(b);
      g.add(blob(0.22)); return g;
    },
    token() { // a word piece: a tile with a lit top
      const g = new T3.Group();
      const b = mesh(new T3.BoxGeometry(0.46, 0.2, 0.46), C.dark, 0.5); b.position.y = 0.1; g.add(b);
      const top = mesh(new T3.BoxGeometry(0.38, 0.03, 0.38), C.accent, 0.4); top.position.y = 0.215; g.add(top);
      g.add(blob(0.3)); return g;
    },
    booth() { // a little station with a lamp on its roof
      const g = new T3.Group();
      const b = mesh(new T3.BoxGeometry(1.5, 1.2, 1.3), C.white, 0.6); b.position.y = 0.6; g.add(b);
      const roof = mesh(new T3.BoxGeometry(1.62, 0.12, 1.42), C.edge); roof.position.y = 1.26; g.add(roof);
      const hole = mesh(new T3.PlaneGeometry(0.8, 0.7), 0x10141f); hole.position.set(0, 0.36, 0.66); g.add(hole);
      const lamp = new T3.Mesh(new T3.SphereGeometry(0.17, 14, 10), UNLIT); lamp.position.y = 1.45; g.add(lamp);
      g.userData.lamp = lamp; g.add(blob(1.0)); return g;
    },
    shelf() {
      const g = new T3.Group();
      const f = mesh(new T3.BoxGeometry(1.8, 2.2, 0.5), 0x3b3f55, 0.8); f.position.y = 1.1; g.add(f);
      const cols = [C.accent, C.gold, 0x14b8a6, C.red, C.white];
      for (let r = 0; r < 3; r++) for (let k = 0; k < 7; k++) {
        const bk = mesh(new T3.BoxGeometry(0.16, 0.5, 0.36), cols[Math.floor(hash(r * 7 + k, 4) * cols.length)], 0.7);
        bk.position.set(-0.66 + k * 0.22, 0.42 + r * 0.66, 0.1); g.add(bk);
      }
      g.add(blob(1.1)); return g;
    },
    desk() {
      const g = new T3.Group();
      const top = mesh(new T3.BoxGeometry(1.6, 0.1, 0.9), 0xb08060, 0.7); top.position.y = 0.8; g.add(top);
      [[-0.7, -0.35], [0.7, -0.35], [-0.7, 0.35], [0.7, 0.35]].forEach(([x, z]) => { const l = mesh(new T3.BoxGeometry(0.08, 0.8, 0.08), 0x7a5a44); l.position.set(x, 0.4, z); g.add(l); });
      g.add(blob(0.9)); return g;
    },
  });
  Object.assign(ITEM, { pills: "pill", tokens: "token" });

  // steps: how something works, step by step -- a parcel travels through 2-4 labelled
  // stations, each lighting up (and changing the parcel) as the voice reaches it.
  // data: {steps: [label, ...], item, result}
  PIECES.steps = (d, cue, end) => {
    const { scene, cam } = stage();
    const labels = (d.steps || []).slice(0, 4), n = labels.length, gap = n > 3 ? 3.0 : 3.5;
    const sx = (i) => (i - (n - 1) / 2) * gap;
    const x0 = sx(0) - 2.6, x1 = sx(n - 1) + 2.6;
    const belt = mesh(new T3.BoxGeometry(x1 - x0 + 1, 0.08, 0.9), 0x1f2740, 0.8); put(belt, 0, 0.9, 0.04); belt.rotation.y = ACROSS; scene.add(belt);
    const booths = labels.map((_, i) => { const b = put(KIT.booth(), sx(i), 0); b.rotation.y = FACE; scene.add(b); return b; });
    const parcel = item(d.item || "data"); scene.add(parcel);
    const T = labels.map((_, i) => stepAt(cue, end, i, n));
    // the parcel rides to each station by that station's time, and waits there
    const px = (t) => {
      if (t < T[0]) return lerp(x0, sx(0), ease(prog(t, T[0] - 0.7, 0.7)));
      for (let i = 0; i < n - 1; i++) if (t < T[i + 1]) return lerp(sx(i), sx(i + 1), ease(prog(t, T[i + 1] - 0.55, 0.55)));
      return lerp(sx(n - 1), x1, ease(prog(t, T[n - 1] + 0.7, 0.6)));
    };
    return {
      draw(t, ctx) {
        const x = px(t);
        aim(cam, Object.assign(at(clamp(x * 0.5, sx(0) * 0.45, sx(n - 1) * 0.45), 0.4), { y: 2.3 }), n > 3 ? 0.98 : 1.08);
        put(parcel, x, 0.9, Math.abs(Math.sin(t * 8)) * 0.05);
        const done = T.filter((ti) => t >= ti).length;
        parcel.scale.setScalar(1.2 + 0.22 * done);
        parcel.rotation.y = t * 1.6;
        booths.forEach((b, i) => {
          b.userData.lamp.material = t >= T[i] ? LIT : UNLIT;
          b.scale.y = 1 + Math.max(0, Math.sin((t - T[i]) * 14)) * 0.07 * (t >= T[i] ? 1 - prog(t, T[i], 0.5) : 0);
        });
        labels.forEach((lab, i) => {
          const live = t >= T[i] && (i === n - 1 || t < T[i + 1]);
          const p = at(sx(i), 0);
          tag(ctx, cam, { x: p.x, y: 2.3 + (i % 2) * 0.6, z: p.z }, lab,
            Object.assign({ alpha: out(prog(t, 0.15 + i * 0.12, 0.3)) * (t >= T[i] ? 1 : 0.6), size: 30 }, live ? GREEN : t >= T[i] ? DARK : {}));
        });
        if (d.result) {
          const ta = T[n - 1] + 1.2, p = at(x1 - 0.4, 0.9);
          tag(ctx, cam, { x: p.x, y: 1.5, z: p.z }, d.result, Object.assign({ alpha: out(prog(t, ta, 0.2)), scale: lerp(0.6, 1, pop(t, ta)), size: 34 }, GREEN));
        }
      },
    };
  };

  // sort: a sorter sends each arriving item into one of 2-3 labelled bins -- a filter, a
  // classifier, triage, a router choosing an expert. data: {sorter, bins: [label, ...], item}
  PIECES.sort = (d, cue, end) => {
    const { scene, cam } = stage();
    const { t1, t2 } = beats(cue, end);
    const bins = (d.bins || []).slice(0, 3), nb = bins.length;
    const S0 = { sx: -0.6, sy: 0.2 };
    const sorter = put(KIT.person({ color: C.accent }), S0.sx, S0.sy); scene.add(sorter);
    const binAt = (j) => ({ sx: 3.6, sy: (j - (nb - 1) / 2) * 2.7 + 0.2 });
    bins.forEach((_, j) => { const b = binAt(j); scene.add(put(KIT.platform({ color: C.edge, r: 1.0 }), b.sx, b.sy)); });
    const belt = mesh(new T3.BoxGeometry(5.2, 0.06, 0.8), 0x1f2740, 0.8); put(belt, -3.6, S0.sy, 0.03); belt.rotation.y = ACROSS; scene.add(belt);
    const spawns = spawnTimes(t1 - 0.6, end - 1.6, 0.55, 18);
    const where = (i) => Math.floor(hash(i, 13) * nb);
    const its = spawns.map(() => { const it = item(d.item || "documents"); scene.add(it); return it; });
    const IN = 1.1, OUT = 0.7;
    return {
      draw(t, ctx) {
        aim(cam, Object.assign(at(0.9, 0.2), { y: 2.3 }), 1.1);
        const counts = bins.map(() => 0);
        let busy = -1;
        its.forEach((it, i) => {
          const s0 = spawns[i], j = where(i), b = binAt(j);
          const fIn = prog(t, s0, IN), fOut = prog(t, s0 + IN + 0.1, OUT);
          it.visible = t >= s0;
          if (fOut <= 0) put(it, lerp(-6.2, S0.sx - 0.5, fIn), S0.sy);
          else {
            const k = fOut >= 1 ? counts[j]++ : counts[j];
            const land = { sx: b.sx + ((k % 3) - 1) * 0.36, sy: b.sy + (Math.floor(k / 3) % 2) * 0.36 };
            put(it, lerp(S0.sx + 0.4, land.sx, ease(fOut)), lerp(S0.sy, land.sy, ease(fOut)), Math.sin(fOut * Math.PI) * 0.9 + (fOut >= 1 ? Math.floor(k / 6) * 0.2 : 0));
          }
          if (fIn >= 1 && fOut < 1) busy = j;
          it.rotation.y = i * 0.9;
        });
        if (busy >= 0) { const b = binAt(busy), p = at(b.sx - S0.sx, b.sy - S0.sy); sorter.rotation.y = Math.atan2(p.x, p.z); pose(sorter, "point", 1); }
        else { sorter.rotation.y = FACE; pose(sorter, "idle"); }
        if (d.sorter) { const p = at(S0.sx, S0.sy); tag(ctx, cam, { x: p.x, y: 2.15, z: p.z }, d.sorter, Object.assign({ alpha: out(prog(t, t1, 0.3)), size: 30 }, DARK)); }
        bins.forEach((lab, j) => {
          const b = binAt(j), p = at(b.sx, b.sy), hot = t > t2 && j === 0;
          tag(ctx, cam, { x: p.x, y: 1.25, z: p.z }, lab, Object.assign({ alpha: out(prog(t, 0.2 + j * 0.12, 0.3)), size: 28 }, hot ? GREEN : {}));
        });
      },
    };
  };

  // cluster: scattered things drift into groups of their own kind; then a newcomer drops in
  // and lands next to the ones most like it -- embeddings, similarity search, recommendations.
  // data: {groups: [label, ...], query}
  PIECES.cluster = (d, cue, end) => {
    const { scene, cam } = stage();
    const { t1, t2 } = beats(cue, end);
    const groups = (d.groups || []).slice(0, 3), ng = groups.length;
    const cols = [C.accent, C.gold, 0x14b8a6];
    const CENTRES = [{ sx: -2.7, sy: -1.0 }, { sx: 2.7, sy: -1.0 }, { sx: 0, sy: 2.0 }];
    const centre = (g) => CENTRES[g];
    const N = 7 * ng;
    const orbs = Array.from({ length: N }, (_, i) => {
      const m = new T3.Mesh(new T3.SphereGeometry(0.24, 16, 12), mat(cols[i % ng], 0.4)); m.position.y = 0.3;
      const g = new T3.Group(); g.add(m); g.add(blob(0.2)); scene.add(g); return g;
    });
    const home = (i) => ({ sx: (hash(i, 21) - 0.5) * 8.4, sy: (hash(i, 22) - 0.5) * 6.0 });
    const spot = (i) => { const c = centre(i % ng), k = Math.floor(i / ng), a = k * 2.4 + i; return { sx: c.sx + Math.cos(a) * 0.55 * Math.sqrt(k + 0.3), sy: c.sy + Math.sin(a) * 0.45 * Math.sqrt(k + 0.3) }; };
    const q = new T3.Group(); const qm = new T3.Mesh(new T3.OctahedronGeometry(0.36), glow(0xffffff)); qm.position.y = 0.45; q.add(qm); q.add(blob(0.3)); scene.add(q);
    const land = { sx: centre(0).sx + 1.05, sy: centre(0).sy + 0.35 };
    const links = [0, 1, 2].map(() => { const l = new T3.Mesh(new T3.BoxGeometry(1, 0.05, 0.05), glow(0xffffff)); scene.add(l); return l; });
    return {
      draw(t, ctx) {
        aim(cam, Object.assign(at(0, 0.3), { y: 2.2 }), lerp(1.0, 1.1, ease(prog(t, t2, 1.2))));
        orbs.forEach((o, i) => {
          const h = home(i), s = spot(i), k = ease(prog(t, t1 + hash(i, 5) * 0.5, 1.3));
          put(o, lerp(h.sx, s.sx, k), lerp(h.sy, s.sy, k), Math.sin(k * Math.PI) * 0.4);
          o.scale.setScalar(Math.max(0.001, out(prog(t, 0.05 + hash(i, 6) * 0.35, 0.3))));
        });
        const kq = prog(t, t2, 0.6), ks = ease(prog(t, t2 + 0.6, 0.8));
        q.visible = t >= t2;
        put(q, lerp(0, land.sx, ks), lerp(0.4, land.sy, ks), (1 - out(kq)) * 5 + Math.sin(ks * Math.PI) * 0.5);
        qm.rotation.y = t * 2;
        // the newcomer's nearest neighbours light up, joined to it
        const lk = prog(t, t2 + 1.4, 0.4);
        links.forEach((l, j) => {
          const a = q.position, b = orbs[j * ng].position;
          const dx = b.x - a.x, dz = b.z - a.z, len = Math.hypot(dx, dz) * lk;
          l.visible = lk > 0;
          l.scale.x = Math.max(0.001, len);
          l.position.set(a.x + dx * lk / 2, 0.42, a.z + dz * lk / 2);
          l.rotation.y = -Math.atan2(dz, dx);
        });
        groups.forEach((lab, g) => {
          const p = at(centre(g).sx, centre(g).sy);
          tag(ctx, cam, { x: p.x, y: 1.5, z: p.z }, lab, Object.assign({ alpha: out(prog(t, t1 + 1.0 + g * 0.15, 0.3)), size: 30 }, g === 0 && t > t2 + 1.4 ? GREEN : {}));
        });
        if (d.query) { const p = at(land.sx, land.sy); tag(ctx, cam, { x: p.x, y: 1.4 + (1 - ks) * 2, z: p.z }, d.query, Object.assign({ alpha: out(prog(t, t2 + 0.2, 0.2)), size: 30 }, DARK)); }
      },
    };
  };

  // hill: a climber steps down a valley toward its lowest point, each step smaller as the
  // slope flattens -- gradient descent, trial and error, getting closer. data: {start, goal}
  PIECES.hill = (d, cue, end) => {
    const { scene, cam } = stage();
    const { t1, t2 } = beats(cue, end);
    const MIN = 1.8, h = (u) => 0.15 * (u - MIN) * (u - MIN) + 0.02;
    const geo = new T3.PlaneGeometry(11, 2.6, 60, 1); geo.rotateX(-Math.PI / 2);
    const P = geo.attributes.position;
    for (let i = 0; i < P.count; i++) P.setY(i, h(P.getX(i)));
    geo.computeVertexNormals();
    // the valley runs across the screen: in `holder`, x is screen-right and z screen-down
    const holder = new T3.Group(); holder.rotation.y = ACROSS; scene.add(holder);
    holder.add(mesh(geo, 0x2b3a5c, 0.85));
    const flag = KIT.flag({ color: C.green }); flag.position.set(MIN, h(MIN), -0.6); holder.add(flag);
    const ball = KIT.person({ color: C.accent }); holder.add(ball);
    // each step moves against the slope, so the steps shrink near the bottom
    const us = [-4.4];
    while (us.length < 9) { const u = us[us.length - 1]; us.push(u - 0.62 * (0.32 * (u - MIN))); }
    const n = us.length - 1, span = Math.max(1.6, Math.min(end - t1 - 0.6, Math.max(2.4, (t2 - t1) * 1.9)));
    const stepT = (k) => t1 + 0.2 + span * (1 - Math.pow(1 - k / n, 1.6));
    return {
      draw(t, ctx) {
        let k = 0; while (k < n && t >= stepT(k + 1)) k++;
        const f = k < n ? ease(prog(t, stepT(k + 1) - 0.32, 0.32)) : 0;
        const u = lerp(us[k], us[Math.min(k + 1, n)], f);
        ball.position.set(u, h(u) + Math.sin(f * Math.PI) * 0.3, 0);
        ball.rotation.y = k >= n ? FACE - ACROSS : Math.PI / 2; // walking along the valley; at the bottom, to the viewer
        pose(ball, k >= n ? "cheer" : f > 0 ? "walk" : "idle", k >= n ? prog(t, stepT(n), 0.4) : 1, t * 8);
        aim(cam, Object.assign(at(lerp(-1.2, 1.0, ease(prog(t, t1, span))), 0), { y: 2.0 }), 1.08);
        const bp = at(u, 0), sp = at(us[0], 0), gp = at(MIN, -0.6);
        if (d.start) tag(ctx, cam, { x: sp.x, y: h(us[0]) + 2.2, z: sp.z }, d.start, { alpha: out(prog(t, 0.2, 0.3)) * (1 - 0.5 * prog(t, t2 + 0.4, 0.3)), size: 30 });
        if (d.goal) tag(ctx, cam, { x: gp.x, y: 2.7, z: gp.z }, d.goal, Object.assign({ alpha: out(prog(t, 0.4, 0.3)), size: 30 }, k >= n ? GREEN : DARK));
        if (t > t1 + 0.2 && k < n) tag(ctx, cam, { x: bp.x, y: h(u) + 1.95, z: bp.z }, "STEP " + (k + 1), { alpha: out(prog(t, t1 + 0.2, 0.2)), size: 26, fill: "#0B0F1C", stroke: "#3A4566", color: "#FACC15" });
      },
    };
  };

  // fetch: a helper runs to the shelves, finds the right page, and brings it back before the
  // answer is given -- retrieval, search, looking it up. data: {asker, shelf, answer}
  PIECES.fetch = (d, cue, end) => {
    const { scene, cam } = stage();
    const { t1, t2 } = beats(cue, end);
    const desk = put(KIT.desk(), -2.6, 1.3); desk.rotation.y = FACE; scene.add(desk);
    const asker = put(KIT.person({ color: C.white }), -3.9, 1.7); asker.rotation.y = FACE; scene.add(asker);
    const helper = KIT.person({ color: C.accent }); scene.add(helper);
    [-0.2, 2.2, 4.6].forEach((sx) => { const s = put(KIT.shelf(), sx, -2.4); s.rotation.y = FACE; scene.add(s); });
    const page = KIT.doc(); scene.add(page);
    const leg = clamp((end - t1 - 1.2) / 2.6, 0.75, 1.3);
    const home = at(-1.6, 1.0), shelfP = at(2.2, -1.4);
    const go = t1 + 0.3, grab = go + leg, back = grab + 0.45, home2 = back + leg;
    const ans = Math.max(home2 + 0.15, Math.min(t2, end - 0.8));
    return {
      draw(t, ctx) {
        const away = ease(prog(t, go, leg)) - ease(prog(t, back, leg));
        aim(cam, Object.assign(at(lerp(-0.8, 1.2, away), 0), { y: 2.3 }), 1.08);
        if (t < back) walk(helper, [[home.x, home.z], [shelfP.x, shelfP.z]], t, go, leg, Math.PI + FACE);
        else walk(helper, [[shelfP.x, shelfP.z], [home.x, home.z]], t, back, leg, FACE);
        const dp = at(-2.6, 1.3), sp = at(2.2, -2.2);
        if (t < grab + 0.2) page.position.set(sp.x, 1.48, sp.z);
        else if (t < home2) page.position.set(helper.position.x, 1.0, helper.position.z);
        else page.position.set(dp.x, 0.86, dp.z);
        page.rotation.y = FACE;
        pose(asker, t >= ans + 0.15 ? "cheer" : "idle", prog(t, ans + 0.15, 0.4), t * 6);
        const ap = at(-3.9, 1.7), sh = at(2.2, -2.4);
        if (d.asker) tag(ctx, cam, { x: ap.x, y: 2.15, z: ap.z }, d.asker, Object.assign({ alpha: out(prog(t, 0.2, 0.3)) * (1 - prog(t, ans - 0.1, 0.1)), size: 28 }, DARK));
        if (d.shelf) tag(ctx, cam, { x: sh.x, y: 3.0, z: sh.z }, d.shelf, { alpha: out(prog(t, t1, 0.3)), size: 30 });
        if (d.answer) tag(ctx, cam, { x: ap.x, y: 2.3, z: ap.z }, d.answer, Object.assign({ alpha: out(prog(t, ans, 0.2)), scale: lerp(0.6, 1, pop(t, ans)), size: 34 }, GREEN));
      },
    };
  };

  // focus: a row of words; one of them looks back at the others, with a beam to each as thick
  // as the attention it pays -- attention, what a model weighs. data: {words, focus, strongest}
  PIECES.focus = (d, cue, end) => {
    const { scene, cam } = stage();
    const { t1, t2 } = beats(cue, end);
    const words = (d.words || []).slice(0, 6), n = words.length;
    const f = clamp(d.focus == null ? n - 1 : d.focus, 0, n - 1);
    let s = clamp(d.strongest == null ? 0 : d.strongest, 0, n - 1); if (s === f) s = f ? 0 : 1;
    const gap = n > 5 ? 1.75 : n > 4 ? 1.95 : 2.2, sx = (i) => (i - (n - 1) / 2) * gap;
    const tiles = words.map((w) => {
      const g = new T3.Group(); g.rotation.y = FACE;
      const face = sign(w, gap * 0.84, 0.8, 0.5); face.position.z = 0; g.add(face); g.add(blob(0.9)); scene.add(g); return g;
    });
    const weight = (i) => (i === s ? 1 : 0.1 + 0.32 * hash(i, 31));
    const COOL = glow(0x8e9bb8), HOT = glow(C.gold);
    const beams = words.map((_, i) => {
      if (i === f) return null;
      const a = at(sx(f), 0), b = at(sx(i), 0);
      const mid = new T3.Vector3((a.x + b.x) / 2, 2.1 + Math.abs(i - f) * 0.42, (a.z + b.z) / 2);
      // from the top of the (raised) looking word to the top of the other
      const curve = new T3.QuadraticBezierCurve3(new T3.Vector3(a.x, 1.42, a.z), mid, new T3.Vector3(b.x, 0.98, b.z));
      const m = new T3.Mesh(new T3.TubeGeometry(curve, 40, 0.025 + 0.11 * weight(i), 8, false), COOL); scene.add(m); return m;
    });
    return {
      draw(t, ctx) {
        aim(cam, Object.assign(at(0, 0.2), { y: 1.9 }), n > 4 ? 1.02 : 1.12);
        tiles.forEach((g, i) => {
          const k = out(prog(t, 0.1 + i * 0.08, 0.35));
          const lift = i === f ? 0.35 * ease(prog(t, t1, 0.4)) : i === s ? 0.25 * back(prog(t, t2 + 0.3, 0.4)) : 0;
          put(g, sx(i), 0, (1 - k) * 2 + lift); g.visible = k > 0;
        });
        beams.forEach((b, i) => {
          if (!b) return;
          const k = ease(prog(t, t1 + 0.35 + Math.abs(i - f) * 0.12, 0.6));
          b.geometry.setDrawRange(0, Math.floor((b.geometry.index.count / 6) * k) * 6);
          b.visible = k > 0;
          b.material = t > t2 + 0.3 && i === s ? HOT : COOL;
        });
        const fp = at(sx(f), 0), sp = at(sx(s), 0);
        if (d.label) tag(ctx, cam, { x: fp.x, y: 2.75, z: fp.z }, d.label, Object.assign({ alpha: out(prog(t, t1 + 0.2, 0.3)), size: 28 }, DARK));
        if (d.strong) tag(ctx, cam, { x: sp.x, y: 2.35, z: sp.z }, d.strong, Object.assign({ alpha: out(prog(t, t2 + 0.5, 0.2)), scale: lerp(0.6, 1, pop(t, t2 + 0.5)), size: 26 }, GREEN));
      },
    };
  };

  // slice: one whole thing is cut into labelled pieces that slide apart -- a sentence into
  // tokens, a document into chunks, a budget into its parts. data: {whole, parts: [label, ...]}
  PIECES.slice = (d, cue, end) => {
    const { scene, cam } = stage();
    const { t1, t2 } = beats(cue, end);
    const parts = (d.parts || []).slice(0, 6), n = parts.length;
    const sizes = parts.map((p) => 0.8 + Math.min(10, p.length) * 0.12), raw = sizes.reduce((a, b) => a + b, 0);
    const k0 = Math.min(1, 8.4 / raw), W = raw * k0;
    const tones = [C.accent, 0x60a5fa, 0x93c5fd, 0x2563eb, 0x38bdf8, 0x1d4ed8];
    let acc = -W / 2;
    const blocks = parts.map((_, i) => {
      const w = sizes[i] * k0, cx = acc + w / 2; acc += w;
      const g = new T3.Group(); g.rotation.y = ACROSS;
      const b = mesh(new T3.BoxGeometry(w - 0.02, 0.9, 1.3), tones[i % tones.length], 0.55); b.position.y = 0.45; g.add(b); scene.add(g);
      return { g, cx, w };
    });
    const cuts = blocks.slice(1).map((bk) => { const c = new T3.Mesh(new T3.BoxGeometry(0.06, 1.05, 1.42), glow(0xffffff)); c.rotation.y = ACROSS; scene.add(c); return { c, x: bk.cx - bk.w / 2 }; });
    const cutAt = (i) => lerp(t1 + 0.4, Math.max(t1 + 0.6, t2 - 0.15), n > 2 ? i / (n - 2) : 0);
    const spread = (i) => (i - (n - 1) / 2) * 0.42;
    return {
      draw(t, ctx) {
        aim(cam, Object.assign(at(0, 0.3), { y: 1.9 }), W > 7 ? 1.12 : 1.28);
        const drop = out(prog(t, 0.05, 0.45)), apart = ease(prog(t, t2, 0.6));
        blocks.forEach((bk, i) => {
          const hop = Math.max(0, Math.sin(clamp((t - t2 - 0.1 - i * 0.08) / 0.4, 0, 1) * Math.PI)) * 0.4;
          put(bk.g, bk.cx + spread(i) * apart, 0, (1 - drop) * 3 + hop);
        });
        cuts.forEach((c, i) => { const k = prog(t, cutAt(i), 0.25); c.c.visible = k > 0 && apart < 0.3; put(c.c, c.x, 0, 0.52 + (1 - out(k)) * 1.6); });
        if (d.whole) { const p = at(0, 0); tag(ctx, cam, { x: p.x, y: 2.1, z: p.z }, d.whole, Object.assign({ alpha: out(prog(t, 0.3, 0.3)) * (1 - prog(t, t2, 0.25)), size: 32 }, DARK)); }
        blocks.forEach((bk, i) => {
          const p = at(bk.cx + spread(i), 0), a = t2 + 0.3 + i * 0.1;
          tag(ctx, cam, { x: p.x, y: 1.55 + (i % 2) * 0.55, z: p.z }, parts[i], Object.assign({ alpha: out(prog(t, a, 0.2)), scale: lerp(0.6, 1, pop(t, a)), size: 30 }, DARK));
        });
      },
    };
  };

  // window: things pass under a frame that only holds a few at a time; the oldest fall off the
  // end and are gone -- a context window, short-term memory, a queue. data: {window, size, item, dropped}
  PIECES.window = (d, cue, end) => {
    const { scene, cam } = stage();
    const { t1, t2 } = beats(cue, end);
    const size = clamp(d.size || 4, 2, 6), slot = 1.05, fw = size * slot;
    const a = -fw / 2, b = fw / 2, u0 = a - 3.4;
    const belt = mesh(new T3.BoxGeometry(fw + 4.8, 0.12, 1.0), 0x1f2740, 0.8); put(belt, -1.7, 0, 0.06); belt.rotation.y = ACROSS; scene.add(belt);
    const frame = new T3.Group(); frame.rotation.y = ACROSS; scene.add(frame);
    const bar = (w, h, x, y) => [0.62, -0.62].forEach((z) => { const m = new T3.Mesh(new T3.BoxGeometry(w, h, 0.1), glow(C.accent)); m.position.set(x, y, z); frame.add(m); });
    bar(fw + 0.2, 0.1, 0, 1.6); bar(0.1, 1.6, a - 0.05, 0.8); bar(0.1, 1.6, b + 0.05, 0.8);
    // the first card reaches the far edge of the frame on the turn
    const speed = (b + 0.7 - u0) / Math.max(0.8, t2 - t1);
    const spawns = spawnTimes(t1, end, slot / speed, 30);
    const cards = spawns.map(() => { const c = item(d.item || "documents"); scene.add(c); return c; });
    return {
      draw(t, ctx) {
        aim(cam, Object.assign(at(0.3, 0.4), { y: 2.0 }), 1.08);
        let gone = 0;
        cards.forEach((c, i) => {
          const u = u0 + (t - spawns[i]) * speed, over = u - (b + 0.7);
          c.visible = t >= spawns[i];
          if (over > 0) { gone++; put(c, b + 0.7 + over * 0.4, 0, 0.12 - over * over * 1.4); c.rotation.z = -over * 1.5; c.visible = c.visible && over < 1.6; }
          else { put(c, u, 0, 0.12); c.rotation.z = 0; }
          c.rotation.y = FACE;
          c.scale.setScalar(u >= a && u <= b ? 1.2 : 0.95);
        });
        const p = at(0, 0);
        if (d.window) tag(ctx, cam, { x: p.x, y: 2.3, z: p.z }, d.window, Object.assign({ alpha: out(prog(t, 0.2, 0.3)), size: 30 }, DARK));
        if (d.dropped && gone > 0) { const q = at(b + 1.4, 0.2); tag(ctx, cam, { x: q.x, y: 1.3, z: q.z }, d.dropped, Object.assign({ alpha: out(prog(t, t2 + 0.2, 0.2)), scale: lerp(0.6, 1, pop(t, t2 + 0.2)), size: 30 }, RED)); }
      },
    };
  };

  // target: someone throws at a target; the first throws scatter, and after the feedback (the
  // turn) each lands closer to the centre -- training, practice, learning from mistakes.
  // data: {thrower, target, result}
  PIECES.target = (d, cue, end) => {
    const { scene, cam } = stage();
    const { t1, t2 } = beats(cue, end);
    const thrower = put(KIT.person({ color: C.accent }), -3.4, 1.6); scene.add(thrower);
    const board = new T3.Group(); put(board, 2.9, -1.3); scene.add(board);
    const face = new T3.Group(); face.position.y = 1.5; board.add(face);
    [[1.1, C.white], [0.85, C.red], [0.6, C.white], [0.35, C.red], [0.13, C.gold]].forEach(([r, c], i) => {
      const ring = mesh(new T3.CylinderGeometry(r, r, 0.08 + i * 0.02, 32), c, 0.6); ring.rotation.x = Math.PI / 2; face.add(ring);
    });
    const leg = mesh(new T3.BoxGeometry(0.14, 1.5, 0.14), C.dark); leg.position.y = 0.75; board.add(leg); board.add(blob(0.8));
    const tp = thrower.position, bp = board.position;
    board.rotation.y = Math.atan2(tp.x - bp.x, tp.z - bp.z);
    thrower.rotation.y = Math.atan2(bp.x - tp.x, bp.z - tp.z);
    scene.updateMatrixWorld(true);
    const shots = spawnTimes(t1, end - 0.9, 0.48, 12);
    const after = shots.filter((x) => x >= t2);
    const err = (i) => (shots[i] < t2 ? 0.7 + 0.35 * hash(i, 41) : Math.max(0.04, 0.6 * Math.pow(0.55, after.indexOf(shots[i]) + 1)));
    const landing = shots.map((_, i) => { const a = hash(i, 42) * Math.PI * 2, r = err(i); const v = new T3.Vector3(Math.cos(a) * r, Math.sin(a) * r, 0.14); face.localToWorld(v); scene.worldToLocal(v); return v; });
    const darts = shots.map(() => { const m = new T3.Mesh(new T3.SphereGeometry(0.09, 10, 8), glow(C.accent)); scene.add(m); return m; });
    return {
      draw(t, ctx) {
        aim(cam, Object.assign(at(-0.1, 0.1), { y: 2.1 }), 1.1);
        let last = -1;
        darts.forEach((m, i) => {
          const f = prog(t, shots[i], 0.4), L = landing[i];
          m.visible = t >= shots[i];
          m.position.set(lerp(tp.x, L.x, f), lerp(1.3, L.y, f) + Math.sin(f * Math.PI) * 0.8, lerp(tp.z, L.z, f));
          if (t >= shots[i]) last = i;
        });
        const won = t > end - 0.8, throwing = last >= 0 && t - shots[last] < 0.25;
        pose(thrower, won ? "cheer" : throwing ? "point" : "idle", won ? prog(t, end - 0.8, 0.3) : 1, t * 6);
        if (d.thrower) { const p = at(-3.4, 1.6); tag(ctx, cam, { x: p.x, y: 2.15, z: p.z }, d.thrower, Object.assign({ alpha: out(prog(t, 0.2, 0.3)), size: 28 }, DARK)); }
        if (d.target) { const p = at(2.9, -1.3); tag(ctx, cam, { x: p.x, y: 3.1, z: p.z }, d.target, { alpha: out(prog(t, 0.35, 0.3)), size: 30 }); }
        if (d.result) { const p = at(2.9, -0.2); tag(ctx, cam, { x: p.x, y: 0.4, z: p.z }, d.result, Object.assign({ alpha: out(prog(t, t2 + 1.2, 0.2)), scale: lerp(0.6, 1, pop(t, t2 + 1.2)), size: 30 }, GREEN)); }
      },
    };
  };

  // -- the world builder ---------------------------------------------------------------
  // Stations sit along a path that turns now and then, so the glides between them run across
  // the screen and diagonally, never always the same way. In screen units (right, down).
  const STEPS = [[16, 0], [12, 9], [16, 0], [12, -9]];
  const spotFor = (k) => {
    let sx = 0, sy = 0;
    for (let j = 0; j < k; j++) { sx += STEPS[j % STEPS.length][0]; sy += STEPS[j % STEPS.length][1]; }
    return at(sx, sy);
  };
  const GLIDE = 0.95; // seconds the camera takes to fly from one station to the next
  const stations = [];
  let world = null;

  function master() {
    if (world) return world;
    const scene = new T3.Scene();
    scene.add(new T3.HemisphereLight(0xdfe8ff, 0x1a2036, 0.75));
    const key = new T3.DirectionalLight(0xfff1dc, 1.05); key.position.set(6, 11, 7); scene.add(key);
    const rim = new T3.DirectionalLight(new T3.Color(DECK.accent || "#3B82F6"), 0.55); rim.position.set(-8, 5, -7); scene.add(rim);
    // the floor's colour is lit up about fourfold by the clay light: this reads as brand navy
    const floor = mesh(new T3.PlaneGeometry(900, 900), 0x080b15, 0.95); floor.rotation.x = -Math.PI / 2; scene.add(floor);
    const grid = new T3.GridHelper(900, 900, 0x1a2238, 0x1a2238); grid.position.y = 0.01; scene.add(grid);
    const PPU = 88; // pixels per world unit at zoom 1: about 12 units across the frame
    const cam = new T3.OrthographicCamera(-W / 2 / PPU, W / 2 / PPU, H / 2 / PPU, -H / 2 / PPU, 0.1, 200);
    world = { scene, cam, ctx: null };
    return world;
  }

  // Add a world beat's set piece as the next station. `host` is the scene's content element,
  // `s` the slide spec (data.piece + its fields), `c` its timing. False if it can't be drawn.
  function station(host, s, c) {
    const d = s.data || {};
    const make = PIECES[d.piece];
    if (!make) return false;
    try { if (!renderer) H = document.getElementById("scenes").offsetHeight; gl(); } catch (e) { // no WebGL: the title alone says it
      console.warn("world: WebGL unavailable", e);
      return false;
    }
    const W0 = master();
    const off = spotFor(stations.length);
    const group = new T3.Group(); group.position.set(off.x, 0, off.z); W0.scene.add(group);
    const cam = { off, state: null, labels: [] };
    const n = parts(s).length;
    const cue = (j) => (j < n ? partAt(s, c, j) - c.t0 : null);
    const end = latest(c) - c.t0;
    ST = { group, cam };
    let piece;
    try { piece = make(d, cue, end); } finally { ST = null; }
    piece.draw(0, null);
    stations.push({ piece, cam, t0: c.t0, dur: c.dur });
    host.parentElement.classList.add("has-world");
    console.log("world: " + d.piece + " station " + stations.length + " built");
    return true;
  }

  // One frame of the whole world at reel time T: every station in its state at T (clamped to
  // its own beat, so places visited keep their ending), the camera on the current station --
  // flying over from the last one as a beat begins -- and the current station's labels.
  function frame(T) {
    const W0 = world;
    stations.forEach((st) => { st.cam.labels = []; st.piece.draw(clamp(T - st.t0, 0, st.dur), null); });
    let i = 0;
    while (i + 1 < stations.length && stations[i + 1].t0 - 0.1 <= T) i++;
    const cur = stations[i], prev = i ? stations[i - 1] : null;
    const w = prev ? ease(prog(T, cur.t0 - 0.1, GLIDE)) : 1;
    const A = cur.cam.state;
    let cs = Object.assign({}, A);
    if (prev && w < 1) {
      const P = prev.cam.state;
      cs = { x: lerp(P.x, A.x, w), y: lerp(P.y, A.y, w), z: lerp(P.z, A.z, w), yaw: A.yaw,
        zoom: lerp(P.zoom, A.zoom, w) * (1 - 0.22 * Math.sin(w * Math.PI)) }; // a lift as it flies
    }
    // past the last beat that is a station (a question, a receipt, the recap), drift back slowly
    const over = T - (cur.t0 + cur.dur);
    if (over > 0) cs.zoom *= lerp(1, 0.8, ease(clamp(over / 6, 0, 1)));
    point(W0.cam, cs);
    const r = gl();
    r.render(W0.scene, W0.cam);
    const ctx = W0.ctx;
    ctx.clearRect(0, 0, W, H);
    ctx.drawImage(r.domElement, 0, 0);
    const show = (st, fade) => st.cam.labels.forEach(([pos, text, o]) => drawTag(ctx, W0.cam, pos, text, o, fade));
    if (prev && w < 1) show(prev, 1 - prog(T, cur.t0 - 0.1, 0.25));
    show(cur, (prev ? out(prog(T, cur.t0 + 0.3, 0.3)) : 1) * (1 - prog(T, cur.t0 + cur.dur - 0.05, 0.25)));
  }

  // After every scene is built: the world's canvas goes in behind the scene window (outside the
  // scenes, so their transitions and punch-ins never move it) and runs on the reel's clock.
  function start(total) {
    if (!stations.length) return null;
    const win = document.getElementById("scenes");
    const box = el("div", "world", null);
    win.parentElement.insertBefore(box, win);
    box.setAttribute("data-layout-allow-overflow", ""); box.setAttribute("data-layout-allow-overlap", "");
    box.style.top = win.offsetTop + "px"; box.style.height = H + "px";
    const cv = el("canvas", null, null, box); cv.width = W; cv.height = H;
    world.ctx = cv.getContext("2d");
    const clock = { t: 0 };
    frame(0);
    tl.fromTo(clock, { t: 0 }, { t: total, duration: total, ease: "none", onUpdate: () => frame(clock.t) }, 0);
    return box;
  }

  return { station, start, pieces: Object.keys(PIECES) };
};
