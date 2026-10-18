/* ember/page.js: the Ember page. Connection card, section tabs, and one section at a time.
   Sections register themselves with FL.registerSection (see core.js), so the tabs are
   built from whatever section files are loaded. */
(() => {
  "use strict";
  const FL = window.FL;
  const { $, h, state } = FL;

  FL.renderEmber = () => {
    const body = $("#emberBody");
    const r = state.report;
    if (!r && !state.loadError) {
      body.replaceChildren(h("p", { class: "muted", text: "Loading…" }));
      return;
    }
    if (!r) {
      body.replaceChildren(
        h("div", { class: "banner error" }, FL.icon("alert"),
          h("span", { text: state.loadError || "Ember is not responding. Check that the server is running, then reload." })));
      return;
    }
    if (!FL.sections.some((s) => s.id === state.tab)) state.tab = (FL.sections[0] || {}).id;

    body.replaceChildren(...[
      h("div", { id: "live" }),
      r.demo && h("div", { class: "banner" }, FL.icon("info"),
        h("span", { text: `This is sample data for ${r.child}. Add a video link or connect YouTube, then choose Analyse videos to see real results.` })),
      tabBar(),
      h("section", { id: "emberSection", class: "e-section", role: "tabpanel" }),
      h("p", { class: "footnote", text: "Ratings, summaries and flags are written by Gemini from the video itself. They are a guide, so open any video that matters." }),
    ].filter(Boolean));
    renderSection();
    FL.refreshLive();
  };

  function tabBar() {
    const bar = h("div", { id: "emberTabs", class: "tabs", role: "tablist", "aria-label": "Ember sections" },
      FL.sections.map((s) =>
        h("button", {
          class: "tab", type: "button", role: "tab", id: "tab-" + s.id, "aria-controls": "emberSection",
          "aria-selected": String(s.id === state.tab), tabindex: s.id === state.tab ? "0" : "-1",
          onclick: () => FL.setTab(s.id),
        }, s.label)));
    bar.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const i = FL.sections.findIndex((s) => s.id === state.tab);
      const n = FL.sections.length;
      const next = FL.sections[(i + (e.key === "ArrowRight" ? 1 : n - 1)) % n];
      FL.setTab(next.id);
      $("#tab-" + next.id).focus();
      e.preventDefault();
    });
    return bar;
  }

  function renderSection() {
    const r = state.report;
    const def = FL.sections.find((s) => s.id === state.tab);
    const box = $("#emberSection");
    if (!def || !box) return;
    box.setAttribute("aria-labelledby", "tab-" + def.id);
    box.replaceChildren(
      h("div", { class: "sec-head" },
        h("h2", { text: def.title(r) }),
        def.desc && h("p", { class: "sec-desc", text: def.desc(r) })),
      ...[].concat(def.render(r)).filter(Boolean));
  }

  FL.setTab = (id) => {
    if (id === state.tab) return;
    state.tab = id;
    FL.$$("#emberTabs .tab").forEach((b) => {
      const on = b.id === "tab-" + id;
      b.setAttribute("aria-selected", String(on));
      b.tabIndex = on ? 0 : -1;
    });
    renderSection();
    history.replaceState(null, "", "#/ember/" + id);
    // If the tab bar has scrolled out of view, bring it back to the top.
    const main = $("#main");
    const gap = $("#emberTabs").getBoundingClientRect().top - main.getBoundingClientRect().top;
    if (gap < 0) main.scrollTop += gap - 8;
  };
})();
