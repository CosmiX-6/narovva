/* Chart builders for the motion reel's data scenes. They draw what
 * narovva.motion.dataviz parsed out of the article (see `viz` on a slide
 * spec) -- nothing is parsed or invented here. SVG and transforms only, and
 * every tween is a fromTo so a frame looks the same however it is reached.
 */
window.CUViz = function (tl, el) {
  const NS = "http://www.w3.org/2000/svg";

  /* A metric's number at value `v`, formatted the way it reads at rest. */
  function format(m, v) {
    const n = m.grouped
      ? v.toLocaleString("en-US", { minimumFractionDigits: m.decimals, maximumFractionDigits: m.decimals })
      : v.toFixed(m.decimals);
    return m.prefix + n + m.suffix;
  }

  function countUp(node, m, at, duration) {
    const o = { v: 0 };
    tl.fromTo(o, { v: 0 }, {
      v: m.value, duration, ease: "power3.out",
      onUpdate: () => { node.textContent = format(m, o.v); },
    }, at);
  }

  /* A percentage as an arc that fills while the number counts up inside it. */
  function ring(parent, m, size, at, duration) {
    const box = el("div", "ring-box", null, parent);
    box.style.width = box.style.height = size + "px";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 100 100");
    const circle = (cls) => {
      const c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", "50"); c.setAttribute("cy", "50"); c.setAttribute("r", "42");
      c.setAttribute("class", cls);
      svg.appendChild(c);
      return c;
    };
    circle("ring-track");
    const arc = circle("ring-arc");
    const C = 2 * Math.PI * 42;
    arc.style.strokeDasharray = C;
    box.appendChild(svg);
    const num = el("div", "ring-num", m.text, box);
    num.style.fontSize = Math.round(size * 0.25) + "px";
    tl.fromTo(arc, { strokeDashoffset: C }, { strokeDashoffset: C * (1 - m.frac), duration, ease: "power3.out" }, at);
    countUp(num, m, at, duration);
    return box;
  }

  /* A horizontal bar filled to `m.frac` of the track (scale shared with its siblings). */
  function bar(parent, m, at, duration) {
    const track = el("div", "strack", null, parent);
    const fill = el("i", null, null, track);
    fill.style.width = m.frac * 100 + "%";
    tl.fromTo(fill, { scaleX: 0 }, { scaleX: 1, duration, ease: "expo.out" }, at);
    return track;
  }

  return { format, countUp, ring, bar };
};
