/* Generative background for the motion reel: a drifting field of light streaks.
 *
 * HyperFrames renders by seeking to arbitrary frames, so nothing here keeps
 * state between frames: every particle's position is a closed-form function
 * of time, and all randomness comes from a PRNG seeded per story. The same
 * story always renders the same field; no two stories share one.
 */
(function () {
  function rng(seed) { // mulberry32
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function hexRgb(hex) {
    const h = String(hex || "#3B82F6").replace("#", "");
    const full = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
    const n = parseInt(full, 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  const smooth = (x) => { x = Math.min(1, Math.max(0, x)); return x * x * (3 - 2 * x); };
  const wrap = (v, m) => ((v % m) + m) % m;

  /* opts: { seed, accent, cuts: [scene start times], dim: 0..1 overall strength }
   * Returns draw(t). The field turns a little and flares at every cut, so the
   * background answers each scene change, then settles while the text is read. */
  function createField(canvas, opts) {
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    const S = Math.ceil(Math.hypot(W, H)) + 40; // square big enough to cover the frame at any rotation
    const cx = W / 2, cy = H / 2;
    const rand = rng(opts.seed);
    const [ar, ag, ab] = hexRgb(opts.accent);
    const dim = opts.dim == null ? 1 : opts.dim;

    const particles = [];
    for (let i = 0; i < 420; i++) {
      const depth = 0.3 + rand() * 0.7; // nearer = faster, longer, brighter
      particles.push({
        x: rand() * S, y: rand() * S, depth,
        vx: (rand() - 0.5) * 16 * depth, vy: -(8 + rand() * 30) * depth,
        amp: 8 + rand() * 30, freq: 0.2 + rand() * 0.55, phase: rand() * 6.2832, k: 0.004 + rand() * 0.007,
        white: rand() < 0.32, twPhase: rand() * 6.2832, twFreq: 0.5 + rand() * 1.6,
      });
    }
    const cuts = (opts.cuts || []).filter((t) => t > 0);
    const turns = cuts.map(() => (rand() < 0.5 ? -1 : 1) * (0.16 + rand() * 0.22));

    function rotation(t) {
      let r = 0.05 * t; // a slow constant turn so the field is never still
      for (let i = 0; i < cuts.length; i++) r += turns[i] * smooth((t - cuts[i] + 0.15) / 0.6);
      return r;
    }
    function locate(p, t) {
      const x = wrap(p.x + p.vx * t + p.amp * Math.sin(p.freq * t + p.phase + p.y * p.k), S) - S / 2;
      const y = wrap(p.y + p.vy * t + p.amp * Math.cos(p.freq * 0.8 * t + p.phase + p.x * p.k), S) - S / 2;
      const r = rotation(t), c = Math.cos(r), s = Math.sin(r);
      return [cx + x * c - y * s, cy + x * s + y * c];
    }

    return function draw(t) {
      let energy = 0;
      for (let i = 0; i < cuts.length; i++) { const d = t - cuts[i]; energy += Math.exp(-(d * d) / 0.09); }
      energy = Math.min(energy, 1.2);
      const trail = 0.05 + 0.2 * energy;       // seconds of motion each streak covers
      const fadeIn = smooth(t / 0.6);
      ctx.clearRect(0, 0, W, H);
      ctx.lineCap = "round";
      for (const p of particles) {
        const [x1, y1] = locate(p, t);
        if (x1 < -40 || x1 > W + 40 || y1 < -40 || y1 > H + 40) continue;
        let [x0, y0] = locate(p, t - trail);
        if (Math.hypot(x1 - x0, y1 - y0) > 160) continue; // wrapped around the field edge mid-streak
        if (Math.hypot(x1 - x0, y1 - y0) < 1.2) { x0 = x1 - 0.6; y0 = y1 - 1; } // resting particles read as dots
        const twinkle = 0.6 + 0.4 * Math.sin(p.twPhase + p.twFreq * t);
        const alpha = Math.min(0.9, (0.1 + 0.42 * p.depth) * twinkle * (1 + 0.9 * energy) * dim * fadeIn);
        ctx.strokeStyle = p.white ? `rgba(243,245,250,${alpha})` : `rgba(${ar},${ag},${ab},${alpha})`;
        ctx.lineWidth = 0.7 + p.depth * 1.3;
        ctx.beginPath(); ctx.moveTo(x0, y0); ctx.lineTo(x1, y1); ctx.stroke();
      }
    };
  }

  window.CUAmbient = { rng, createField };
})();
