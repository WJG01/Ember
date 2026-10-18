/* ember/interests.js: "Interests" tab. The theme graph, theme chips and the detail for one theme. */
(() => {
  "use strict";
  const FL = window.FL;
  const { h, sv, state } = FL;

  function renderThemes(box) {
    const r = state.report;
    const active = r.themes.find((t) => t.id === state.theme) || r.themes[0];
    const color = (t) => FL.PALETTE[r.themes.indexOf(t) % FL.PALETTE.length];
    const pick = (t) => { state.theme = t.id; renderThemes(box); };

    const chips = h("div", { class: "chips", role: "group", "aria-label": "Themes" }, r.themes.map((t) =>
      h("button", { class: "chip", type: "button", "aria-pressed": String(t === active), onclick: () => pick(t) },
        h("span", { class: "swatch", style: `background:${color(t)}` }), t.name)));

    const byId = new Map(r.videos.map((v) => [v.video_id, v]));
    const links = active.video_ids.map((id) => byId.get(id)).filter(Boolean);
    const detail = h("div", { class: "theme", style: `--c:${color(active)}` },
      h("h3", { text: active.name }),
      h("p", { class: "lead", text: active.insight }),
      h("div", { class: "pills" },
        h("span", { class: "pill", text: FL.plural(active.video_count, "video", "videos") }),
        h("span", { class: "pill", text: `Confidence: ${active.confidence}` }),
        h("span", { class: "pill", text: `Trend: ${FL.TREND[active.trajectory] || active.trajectory}` }),
        h("span", { class: "pill", text: `Easy to do offline: ${active.transferability}` })),
      h("div", {}, h("h4", { text: "Why these belong together" }), h("p", { text: active.reasoning })),
      h("div", {}, h("h4", { text: "What Ember saw" }), h("ul", {}, (active.evidence || []).map((e) => h("li", { class: "b", text: e })))),
      h("div", {}, h("h4", { text: "Where it could lead" }), h("p", { text: active.growth_direction })),
      h("div", {}, h("h4", { text: "Videos" }), h("ul", { class: "links" }, links.map((v) => {
        const u = FL.safeVideoUrl(v.url);
        return h("li", {}, u ? h("a", { href: u, target: "_blank", rel: "noopener noreferrer", text: v.title }) : v.title);
      }))));

    box.replaceChildren(chips, h("div", { class: "graph" }, drawGraph(r, active, color, pick)), detail);
  }

  function drawGraph(r, active, color, pick) {
    const byId = new Map(r.videos.map((v) => [v.video_id, v]));
    const W = 360, nodeX = 124, nodeR = 12, leafX = 184, rowH = 22, gap = 18;
    let y = 10;
    const groups = [];

    const block = (ids, nodeLabel, theme, stroke, dim) => {
      const lines = FL.wrapWords(nodeLabel, 15, 3);
      const blockH = Math.max(ids.length * rowH, lines.length * 14 + 8, nodeR * 2 + 6);
      const cy = y + blockH / 2;
      const y0 = y + (blockH - ids.length * rowH) / 2;
      const g = sv("g", { class: "g-group" + (dim ? " dim" : ""), onclick: theme ? () => pick(theme) : null });
      ids.forEach((id, i) => {
        const v = byId.get(id);
        const ly = y0 + i * rowH + rowH / 2;
        g.append(sv("path", { d: `M ${nodeX + nodeR} ${cy} C ${nodeX + 50} ${cy}, ${leafX - 50} ${ly}, ${leafX - 7} ${ly}`, fill: "none", stroke, "stroke-width": 1.6, "stroke-opacity": theme ? 1 : 0.5 }));
        g.append(sv("circle", { cx: leafX, cy: ly, r: 4.5, fill: stroke }));
        g.append(sv("text", { class: "g-leaf", x: leafX + 10, y: ly + 4 }, sv("title", { text: v ? v.title : id }), FL.trunc(v ? v.title : id, 24)));
      });
      if (theme) {
        g.append(sv("circle", { cx: nodeX, cy, r: nodeR, fill: stroke }));
        g.append(sv("text", { class: "g-count", x: nodeX, y: cy + 4.2, text: ids.length }));
        const lx = nodeX - nodeR - 8;
        const label = sv("text", { class: "g-label", x: lx, y: cy - ((lines.length - 1) * 14) / 2 + 4, "text-anchor": "end" });
        lines.forEach((ln, i) => label.append(sv("tspan", { x: lx, dy: i ? 14 : 0, text: ln })));
        g.append(label);
      } else {
        g.append(sv("text", { class: "g-none", x: nodeX + nodeR, y: cy + 4, text: nodeLabel }));
      }
      groups.push(g);
      y += blockH + gap;
    };

    r.themes.forEach((t) => block(t.video_ids, t.name, t, color(t), t !== active));
    if (r.unassigned_video_ids.length) block(r.unassigned_video_ids, "Fits no theme", null, "#6b7078", true);

    const svg = sv("svg", { viewBox: `0 0 ${W} ${Math.max(y - gap + 10, 60)}`, role: "img", "aria-label": `Videos grouped by what draws ${r.child}` });
    groups.forEach((g) => svg.append(g));
    return svg;
  }

  FL.registerSection({
    id: "interests", order: 3, label: "Interests",
    title: (r) => `What draws ${r.child}`,
    desc: () => "Videos grouped by what holds attention, not by topic.",
    render: (r) => {
      if (!r.themes.length) {
        return FL.emptyCard(`Interests appear after the analysis runs. They group the videos by what holds ${r.child}'s attention, which is often different from what the videos are about.`);
      }
      const box = h("div", {});
      renderThemes(box);
      return box;
    },
  });
})();
