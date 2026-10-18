/* ember/live.js: the connection card at the top of Ember (YouTube status, Disconnect,
   Add a video link, Reconnect YouTube, Sync and analyse) and the progress card
   shown while an analysis runs. */
(() => {
  "use strict";
  const FL = window.FL;
  const { $, h, state } = FL;

  FL.refreshLive = () => {
    const live = $("#live");
    if (!live) return;
    const st = state.status || {};
    const running = !!st.running;
    const nodes = [];

    nodes.push(h("div", { class: "card conn-card" },
      h("div", { class: "conn" },
        h("span", { class: "dot" + (st.connected ? " on" : "") }),
        h("span", { class: "conn-text", text: st.connected ? "YouTube is connected" : "YouTube is not connected" }),
        st.connected && h("button", { class: "text-btn", type: "button", onclick: disconnect }, "Disconnect")),
      h("div", { class: "actions" },
        h("button", { class: "btn", type: "button", onclick: FL.openDialog }, "Add a video link"),
        h("button", { class: "btn", type: "button", onclick: connectYouTube }, st.connected ? "Reconnect YouTube" : "Connect YouTube"),
        h("button", { class: "btn primary", type: "button", disabled: running, onclick: analyse },
          running ? "Analysing…" : st.connected ? "Sync and analyse" : "Analyse videos"))));

    if (running) {
      nodes.push(progressCard(st));
    } else if (st.error && state.dismissedError !== st.finished_at) {
      nodes.push(h("div", { class: "banner error" }, FL.icon("alert"),
        h("div", {},
          h("div", { text: st.error }),
          h("button", { class: "text-btn", type: "button", onclick: () => { state.dismissedError = st.finished_at; FL.refreshLive(); } }, "Dismiss"))));
    }
    live.replaceChildren(h("div", { class: "live-stack" }, ...nodes));
  };

  function progressCard(st) {
    const labels = st.labels || [];
    const idx = Math.max(0, st.step_index || 0);
    const p = st.progress;
    const watching = labels[idx] === "Watching the videos" && p && p.total;
    const title = (labels[idx] || "Working") + (watching ? `: ${p.done} of ${p.total}` : "");
    const bar = h("div", { class: "bar" + (watching ? "" : " indeterminate"), role: "progressbar", "aria-label": title },
      h("i", { style: watching ? `width:${Math.round((p.done / p.total) * 100)}%` : null }));
    return h("div", { class: "card progress" },
      h("h3", { text: title }), bar,
      h("ul", { class: "steps" }, labels.map((l, i) =>
        h("li", { class: i < idx ? "done" : i === idx ? "now" : "" },
          i < idx ? FL.icon("check") : i === idx ? h("span", { class: "running" }) : h("span", { class: "pending" }),
          l))));
  }

  // ------------------------------------------------------------ actions
  function connectYouTube() {
    const st = state.status || {};
    if (!st.has_client_secret) { FL.toast("client_secret.json was not found in the project folder."); return; }
    location.assign("/auth/start");
  }

  async function disconnect() {
    try {
      await FL.api("/api/disconnect", { method: "POST" });
      await FL.loadStatus();
      FL.refreshLive();
      FL.toast("YouTube disconnected.");
    } catch (e) { FL.toast(e.message); }
  }

  async function analyse() {
    const st = state.status || {};
    if (!st.has_gemini_key) { FL.toast("GEMINI_API_KEY is not set in the terminal that runs Ember."); return; }
    if (!st.connected && !st.has_signals) { FL.toast("Add a video link or connect YouTube first."); return; }
    try {
      await (st.connected
        ? FL.api("/api/sync", { method: "POST", body: JSON.stringify({}) })
        : FL.api("/api/run", { method: "POST", body: JSON.stringify({ sync: false }) }));
    } catch (e) { FL.toast(e.message); return; }
    state.dismissedError = null;
    FL.startPolling();
  }

  // ------------------------------------------------------------ polling while a run is going
  FL.startPolling = () => { if (!state.timer) { state.timer = setInterval(tick, 1500); tick(); } };
  const stopPolling = () => { clearInterval(state.timer); state.timer = null; };

  async function tick() {
    try {
      await FL.loadStatus();
      if (state.screen === "ember") FL.refreshLive();
      if (!state.status.running) {
        stopPolling();
        await FL.loadReport();
        FL.applyChildName();
        if (state.screen === "ember") { FL.renderEmber(); $("#main").scrollTop = 0; }
        FL.toast(state.status.error ? "The analysis stopped. The message is at the top of Ember." : "Analysis finished.");
      }
    } catch (_) { /* try again on the next tick */ }
  }
})();
