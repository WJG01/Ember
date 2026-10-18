/* shell.js: the Family Link frame around Ember. Routing, bottom bar, drawer,
   add-link dialog and the snackbar. */
(() => {
  "use strict";
  const FL = window.FL;
  const { $, $$, state } = FL;

  // ------------------------------------------------------------ snackbar
  FL.toast = (msg) => {
    const el = $("#snackbar");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => { el.hidden = true; }, 6000);
  };

  // ------------------------------------------------------------ routing
  // #/            Screen time
  // #/ember       Ember (Overview)
  // #/ember/quest Ember, a specific section
  // The old #/space and #/space/ember links still land on Ember.
  FL.route = () => {
    const m = location.hash.match(/^#\/(?:ember|space(?:\/ember)?)(?:\/([a-z-]+))?$/);
    if (m) {
      if (m[1] && FL.sections.some((s) => s.id === m[1])) state.tab = m[1];
      FL.show("ember");
    } else {
      FL.show("home");
    }
  };

  FL.show = (screen) => {
    const changed = state.screen !== screen;
    state.screen = screen;
    $("#screen-home").hidden = screen !== "home";
    $("#screen-ember").hidden = screen !== "ember";
    $$("[data-nav]").forEach((b) => {
      const on = b.dataset.nav === screen;
      b.classList.toggle("active", on);
      if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
    if (changed) $("#main").scrollTop = 0;
    if (screen === "ember") FL.renderEmber();
  };

  FL.go = (hash) => { location.hash = hash; };

  FL.applyChildName = () => { $$("[data-child-name]").forEach((el) => { el.textContent = FL.child(); }); };

  // ------------------------------------------------------------ drawer
  const openDrawer = () => { $("#scrim").hidden = false; $("#drawer").hidden = false; $(".drawer-item", $("#drawer")).focus(); };
  const closeDrawer = () => { $("#scrim").hidden = true; $("#drawer").hidden = true; $("#openDrawer").focus(); };

  // ------------------------------------------------------------ add-link dialog
  FL.openDialog = () => {
    $("#addError").hidden = true;
    $("#addInput").value = "";
    $("#dialogScrim").hidden = false;
    $("#addDialog").hidden = false;
    $("#addInput").focus();
  };
  const closeDialog = () => { $("#dialogScrim").hidden = true; $("#addDialog").hidden = true; };

  async function saveLink() {
    const url = $("#addInput").value.trim();
    const err = $("#addError");
    if (!url) { err.textContent = "Paste a YouTube link first."; err.hidden = false; return; }
    $("#addSave").disabled = true;
    try {
      const r = await FL.api("/api/videos", { method: "POST", body: JSON.stringify({ url }) });
      closeDialog();
      const next = state.status && state.status.connected ? "Sync and analyse" : "Analyse videos";
      FL.toast(r.duplicate ? "That video is already saved." : `Saved. Choose ${next} to include it.`);
      await FL.loadStatus();
      FL.refreshLive();
    } catch (e) {
      err.textContent = e.message; err.hidden = false;
    } finally { $("#addSave").disabled = false; }
  }

  // ------------------------------------------------------------ wiring
  FL.wireShell = () => {
    $("#openDrawer").addEventListener("click", openDrawer);
    $("#scrim").addEventListener("click", closeDrawer);
    // Screen time is home, Ember is the second real tab. Controls and Location stay static.
    $$("[data-nav]").forEach((b) => b.addEventListener("click", () => {
      const hash = b.dataset.nav === "ember" ? "#/ember" : "#/";
      if (location.hash === hash || (hash === "#/" && !location.hash)) $("#main").scrollTop = 0;
      else FL.go(hash);
    }));
    $("#addCancel").addEventListener("click", closeDialog);
    $("#dialogScrim").addEventListener("click", closeDialog);
    $("#addSave").addEventListener("click", saveLink);
    $("#addInput").addEventListener("keydown", (e) => { if (e.key === "Enter") saveLink(); });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (!$("#addDialog").hidden) closeDialog();
      else if (!$("#drawer").hidden) closeDrawer();
    });
    window.addEventListener("hashchange", FL.route);
  };
})();
