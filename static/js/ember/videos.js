/* ember/videos.js: "Videos" tab. Every video with its report and a filter row. */
(() => {
  "use strict";
  const FL = window.FL;
  const { h, state } = FL;

  function videoCard(v) {
    const u = FL.safeVideoUrl(v.url);
    const tile = () => h("div", { class: "thumb", "aria-hidden": "true", text: (v.title || "?").charAt(0).toUpperCase() });
    const t = FL.safeThumb(v.thumbnail);
    let thumb;
    if (t) {
      thumb = h("img", { class: "thumb", src: t, alt: "", loading: "lazy", referrerpolicy: "no-referrer" });
      thumb.addEventListener("error", () => thumb.replaceWith(tile()));
    } else thumb = tile();

    const flags = FL.flagLabels(v);
    const list = (title, items) => items && items.length ? h("div", {}, h("h4", { text: title }), h("ul", {}, items.map((i) => h("li", { text: i })))) : null;
    const para = (title, text) => text ? h("div", {}, h("h4", { text: title }), h("p", { text })) : null;

    return h("article", { class: "video" },
      h("div", { class: "video-top" }, thumb,
        h("div", { class: "video-head" }, h("h3", { text: v.title }),
          h("div", { class: "meta", text: [v.domain_label, v.topic].filter(Boolean).join(", ") }),
          h("div", { class: "meta", text: v.liked_at ? `Liked ${FL.fmtDate(v.liked_at)}` : "" }))),
      h("p", { class: "sum", text: v.summary }),
      h("div", { class: "pills" },
        h("span", { class: "pill", text: `Learning: ${FL.cap(v.educational_value)}` }),
        v.age_suitability && h("span", { class: "pill", text: FL.AGE[v.age_suitability] || v.age_suitability }),
        flags.map((f) => h("span", { class: "pill flag-pill" + (v.parent_flag === "note" ? " note" : ""), text: f }))),
      h("details", {},
        h("summary", {}, "Details and questions", FL.icon("expand")),
        h("div", { class: "detail" },
          list("What happens", v.key_points),
          para("Why the learning rating", v.educational_reasoning),
          list("What they may pick up", v.what_child_may_learn),
          para("Heads up", v.safety_note),
          para("Ask together", v.conversation_starter),
          para("Try it offline", v.follow_up_idea),
          u && h("a", { href: u, target: "_blank", rel: "noopener noreferrer", text: "Open on YouTube" }))));
  }

  function list(r) {
    const box = h("div", {});
    const filters = [
      ["all", "All", () => true],
      ["look", "Worth a look", (v) => v.parent_flag !== "ok"],
      ["learn", "Real learning", (v) => v.educational_value === "high" || v.educational_value === "moderate"],
      ["act", "Could become an activity", (v) => v.transferable],
    ];
    const draw = () => {
      const chips = h("div", { class: "chips", role: "group", "aria-label": "Filter videos" }, filters.map(([key, label, fn]) =>
        h("button", { class: "chip", type: "button", "aria-pressed": String(state.filter === key), onclick: () => { state.filter = key; draw(); } },
          label, h("span", { class: "n", text: r.videos.filter(fn).length }))));
      const fn = filters.find((f) => f[0] === state.filter)[2];
      const shown = r.videos.filter(fn);
      box.replaceChildren(chips,
        shown.length ? h("div", { class: "card video-list" }, shown.map((v) => videoCard(v)))
          : h("div", { class: "card empty", text: "No videos match this filter." }));
    };
    draw();
    return box;
  }

  FL.registerSection({
    id: "videos", order: 6, label: "Videos",
    title: () => "Every video",
    desc: (r) => `${FL.plural(r.videos.length, "video", "videos")} reviewed. Open one to see what happens and what to ask.`,
    render: (r) => r.videos.length ? list(r) : FL.emptyCard("No videos yet. Add a video link or connect YouTube, then choose Analyse videos."),
  });
})();
