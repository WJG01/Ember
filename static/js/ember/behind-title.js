/* ember/behind-title.js: "Behind the title" tab. What each title says versus what actually holds attention. */
(() => {
  "use strict";
  const FL = window.FL;
  const { h, state } = FL;

  function table(rows) {
    const box = h("div", {});
    const draw = () => {
      const shown = state.showAllVs ? rows : rows.slice(0, 5);
      const more = rows.length - 5;
      box.replaceChildren(
        h("div", { class: "card vs" },
          h("div", { class: "vs-row head" }, h("span", { text: "What the title says" }), h("span", { text: "What actually holds attention" })),
          shown.map((v) => h("div", { class: "vs-row" }, h("span", { text: FL.cap(v.surface_topic) }), h("span", { text: v.underlying_draw }))),
          more > 0 && h("button", { class: "text-btn vs-more", type: "button", onclick: () => { state.showAllVs = !state.showAllVs; draw(); } },
            state.showAllVs ? "Show fewer" : `Show ${more} more`)));
    };
    draw();
    return box;
  }

  FL.registerSection({
    id: "behind-title", order: 4, label: "Behind the title",
    title: () => "Behind the title",
    desc: () => "A title says what a video is about. Ember watches the video and notes what really holds attention, which is how videos about different things end up in the same interest.",
    render: (r) => {
      const rows = r.videos.filter((v) => v.surface_topic && v.underlying_draw);
      return rows.length ? table(rows) : FL.emptyCard("Nothing to compare yet. Choose Analyse videos to see what each video is really about.");
    },
  });
})();
