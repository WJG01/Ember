/* ember/watch-mix.js: "Watch mix" tab. The two charts: by subject, and how much is learned. */
(() => {
  "use strict";
  const FL = window.FL;
  const { h } = FL;

  function charts(r) {
    const max = Math.max(1, ...r.domains.map((d) => d.count));
    const total = Math.max(1, r.videos.length);
    return h("div", { class: "stack-v" },
      h("div", { class: "card" }, h("div", { class: "chart-title", text: "By subject" }),
        h("div", { class: "rows" }, r.domains.map((d) =>
          h("div", {}, h("div", { class: "row-label" }, h("span", { text: d.label }), h("b", { text: d.count })),
            h("div", { class: "track" }, h("i", { style: `width:${Math.round((d.count / max) * 100)}%` })))))),
      h("div", { class: "card" }, h("div", { class: "chart-title", text: "How much is learned" }),
        h("div", { class: "stack", role: "img", "aria-label": "Share of videos by learning value" },
          FL.EDU.filter(([k]) => r.education[k]).map(([k]) => h("i", { class: "edu-" + k, style: `flex:${r.education[k] / total}` }))),
        h("ul", { class: "legend" }, FL.EDU.map(([k, label]) =>
          h("li", {}, h("span", { class: "sw edu-" + k }), label, h("b", { text: r.education[k] || 0 })))),
        h("p", { class: "note", text: "High means a child could explain or do something specific afterwards. None is pure entertainment, which is fine in moderation." })));
  }

  FL.registerSection({
    id: "watch-mix", order: 5, label: "Watch mix",
    title: (r) => `What ${r.child} watches`,
    desc: () => "The mix of subjects, and how much of it teaches something.",
    render: (r) => r.videos.length ? charts(r) : FL.emptyCard("No charts yet. Choose Analyse videos to see the mix."),
  });
})();
