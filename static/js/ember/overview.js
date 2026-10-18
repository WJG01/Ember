/* ember/overview.js: "Overview" tab. Summary, the four headline numbers, and the videos worth a look. */
(() => {
  "use strict";
  const FL = window.FL;
  const { h } = FL;

  function summary(r) {
    if (!r.parent_summary) {
      return h("div", { class: "card" },
        h("p", { class: "muted", text: "No analysis yet. Add a video link or connect YouTube, then choose Analyse videos." }));
    }
    const subs = (r.subscriptions || []).filter(Boolean).slice(0, 4);
    const meta = [
      r.generated_at ? `Analysed ${FL.fmtDate(r.generated_at)}.` : "",
      subs.length ? `Follows ${subs.join(", ")}.` : "",
    ].filter(Boolean).join(" ");
    return h("div", {},
      h("p", { class: "summary", text: r.parent_summary }),
      meta && h("p", { class: "summary-meta", text: meta }));
  }

  function kpis(r) {
    const t = r.totals;
    const k = (n, label, alert) =>
      h("div", { class: "kpi" + (alert && n > 0 ? " alert" : "") }, h("b", { text: n }), h("span", { text: label }));
    return h("div", { class: "kpis" },
      k(t.videos, "videos reviewed"), k(t.worthwhile, "with real learning in them"),
      k(t.attention, "worth a look", true), k(t.transferable, "could become an activity"));
  }

  function worthALook(r) {
    if (!r.videos.length) return null;
    const byId = new Map(r.videos.map((v) => [v.video_id, v]));
    const items = r.attention.map((id) => byId.get(id)).filter(Boolean);
    const head = h("h3", { class: "sub-h", text: "Worth a look" });
    if (!items.length) {
      return h("div", {}, head, h("div", { class: "card good-note" }, FL.icon("check"),
        h("span", { text: `Nothing in these ${r.videos.length} videos needs your attention.` })));
    }
    return h("div", {}, head,
      h("div", { class: "card look" }, items.map((v) => {
        const flags = FL.flagLabels(v).join(", ");
        const kind = v.parent_flag === "review" ? "review" : "note";
        return h("div", { class: "look-item" },
          h("div", { class: "look-flag " + kind }, FL.icon(kind === "review" ? "alert" : "warn"), kind === "review" ? "Review" : "Note"),
          h("div", { class: "look-title", text: v.title }),
          (flags || v.safety_note) && h("p", {}, flags && h("b", { text: flags + ". " }), v.safety_note),
          v.conversation_starter && h("p", {}, h("b", { text: `Ask ${r.child}: ` }), v.conversation_starter));
      })));
  }

  FL.registerSection({
    id: "overview", order: 1, label: "Overview",
    title: () => "Overview",
    desc: null,
    render: (r) => h("div", { class: "stack-v" }, summary(r), r.videos.length ? kpis(r) : null, worthALook(r)),
  });
})();
