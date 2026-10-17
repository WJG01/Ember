/* Family Link web app + Ember integration (plain JS, no build step).
   Everything that comes from YouTube or Gemini is inserted as text, never as HTML. */
(() => {
  "use strict";

  // ------------------------------------------------------------ helpers
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const SVG_NS = "http://www.w3.org/2000/svg";

  function setAttrs(el, attrs) {
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "text") el.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? "" : v);
    }
  }
  function add(el, kids) {
    for (const k of kids.flat(Infinity)) {
      if (k === null || k === undefined || k === false) continue;
      el.append(k.nodeType ? k : document.createTextNode(String(k)));
    }
    return el;
  }
  const h = (tag, attrs, ...kids) => { const el = document.createElement(tag); setAttrs(el, attrs); return add(el, kids); };
  const sv = (tag, attrs, ...kids) => { const el = document.createElementNS(SVG_NS, tag); setAttrs(el, attrs); return add(el, kids); };
  const icon = (name, cls = "") => sv("svg", { class: ("ic " + cls).trim(), "aria-hidden": "true" }, sv("use", { href: "#i-" + name }));

  const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");
  const trunc = (s, n) => (s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s);
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

  function fmtDate(iso) {
    const d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  }
  const safeVideoUrl = (u) => (/^https:\/\/(www\.)?(youtube\.com|youtu\.be)\//.test(u || "") ? u : "");
  const safeThumb = (u) => (/^https:\/\/i\.ytimg\.com\//.test(u || "") ? u : "");

  function wrapWords(text, max, maxLines) {
    const lines = [];
    let line = "";
    for (const w of text.split(/\s+/)) {
      if (line && (line + " " + w).length > max) { lines.push(line); line = w; }
      else line = line ? line + " " + w : w;
    }
    if (line) lines.push(line);
    return lines.slice(0, maxLines);
  }

  const PALETTE = ["#8ab4f8", "#f4a37c", "#7fd3a5", "#f6c453", "#c9a0f5", "#f08fc0"];
  const AGE = { all_ages: "All ages", age_8_plus: "Age 8+", age_13_plus: "Age 13+", age_16_plus: "Age 16+", adult: "Adults" };
  const FLAG = {
    violence_or_gore: "Violence", scary_or_disturbing: "Scary imagery", strong_language: "Strong language",
    mature_themes: "Mature themes", risky_challenge_or_imitable_danger: "Risky to copy",
    heavy_advertising_or_buying_pressure: "Pushes buying", gambling_like_mechanics: "Chance-based rewards",
    misleading_or_false_claims: "Misleading claims", other: "Other",
  };
  const TREND = { rising: "Rising", steady: "Steady", fading: "Fading", unclear: "Too early to tell" };
  const COST = { free: "Free", low: "Low cost", medium: "Medium cost" };
  const EDU = [["high", "High"], ["moderate", "Moderate"], ["low", "Low"], ["none", "None"]];
  const flagLabels = (v) => (v.safety_flags || []).filter((f) => f !== "none").map((f) => FLAG[f] || cap(f.replace(/_/g, " ")));

  // ------------------------------------------------------------ state
  const state = {
    report: null, status: null, loadError: null,
    screen: "home", theme: null, filter: "all", showAllVs: false,
    timer: null, dismissedError: null, toastTimer: null,
  };

  async function api(path, opts = {}) {
    const init = { ...opts };
    if (opts.body) init.headers = { "Content-Type": "application/json" };
    const res = await fetch(path, init);
    let data = null;
    try { data = await res.json(); } catch (_) { /* no body */ }
    if (!res.ok) {
      const d = data && data.detail;
      throw new Error(typeof d === "string" ? d : `Request failed (${res.status})`);
    }
    return data;
  }
  async function loadReport() {
    state.report = await api("/api/report");
    const ids = state.report.themes.map((t) => t.id);
    if (!ids.includes(state.theme)) state.theme = ids[0] || null;
  }
  async function loadStatus() { state.status = await api("/api/status"); }
  const child = () => (state.report && state.report.child) || "Llamie";

  // ------------------------------------------------------------ toast
  function toast(msg) {
    const el = $("#snackbar");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => { el.hidden = true; }, 6000);
  }

  // ------------------------------------------------------------ navigation
  function route() {
    const hash = location.hash;
    show(hash === "#/space/ember" ? "ember" : hash === "#/space" ? "space" : "home");
  }
  function show(screen) {
    state.screen = screen;
    $("#screen-home").hidden = screen !== "home";
    $("#screen-space").hidden = screen !== "space";
    $("#screen-ember").hidden = screen !== "ember";
    $("#homeBar").hidden = screen === "ember";
    $("#emberBar").hidden = screen !== "ember";
    $("#nav").hidden = screen === "ember";
    $$("[data-nav]").forEach((b) => {
      const on = b.dataset.nav === screen;
      b.classList.toggle("active", on);
      if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
    });
    $("#main").scrollTop = 0;
    if (screen === "ember") renderEmber();
    if (screen === "space") renderIntegrations();
  }
  const go = (hash) => { location.hash = hash; };

  function applyChildName() { $$("[data-child-name]").forEach((el) => { el.textContent = child(); }); }

  // drawer
  function openDrawer() { $("#scrim").hidden = false; $("#drawer").hidden = false; $(".drawer-item", $("#drawer")).focus(); }
  function closeDrawer() { $("#scrim").hidden = true; $("#drawer").hidden = true; $("#openDrawer").focus(); }

  // add-link dialog
  function openDialog() {
    $("#addError").hidden = true;
    $("#addInput").value = "";
    $("#dialogScrim").hidden = false;
    $("#addDialog").hidden = false;
    $("#addInput").focus();
  }
  function closeDialog() { $("#dialogScrim").hidden = true; $("#addDialog").hidden = true; }
  async function saveLink() {
    const url = $("#addInput").value.trim();
    const err = $("#addError");
    if (!url) { err.textContent = "Paste a YouTube link first."; err.hidden = false; return; }
    $("#addSave").disabled = true;
    try {
      const r = await api("/api/videos", { method: "POST", body: JSON.stringify({ url }) });
      closeDialog();
      toast(r.duplicate ? "That video is already saved." : "Saved. Choose Analyse videos to include it.");
      await loadStatus();
      refreshLive();
    } catch (e) {
      err.textContent = e.message; err.hidden = false;
    } finally { $("#addSave").disabled = false; }
  }

  // ------------------------------------------------------------ Space
  function renderIntegrations() {
    const list = $("#integrationList");
    const st = state.status;
    const r = state.report;
    let line = "";
    if (r && r.demo) line = "Showing sample data";
    else if (st && st.connected) line = "YouTube connected";
    else if (st) line = "Not connected yet";
    list.replaceChildren(
      h("button", { class: "list-row", type: "button", onclick: () => go("#/space/ember") },
        h("span", { class: "list-icon" }, icon("flame")),
        h("span", { class: "list-text" },
          h("div", { class: "list-title", text: "Ember" }),
          h("div", { class: "list-desc", text: `See what ${child()} likes on YouTube and turn it into weekend activities.` }),
          line && h("div", { class: "list-state", text: line })),
        icon("chevron")));
  }

  // ------------------------------------------------------------ Ember
  function renderEmber() {
    const body = $("#emberBody");
    const r = state.report;
    if (!r && !state.loadError) {
      body.replaceChildren(h("p", { class: "muted", text: "Loading…" }));
      return;
    }
    if (!r) {
      body.replaceChildren(
        h("div", { class: "banner error" }, icon("alert"),
          h("span", { text: state.loadError || "Ember is not responding. Check that the server is running, then reload." })));
      return;
    }
    const sections = [
      h("div", { id: "live", class: "e-section" }),
      r.demo && h("div", { class: "banner" }, icon("info"),
        h("span", { text: `This is sample data for ${r.child}. Add a video link or connect YouTube, then choose Analyse videos to see real results.` })),
      secSummary(r),
      secKpis(r),
      secQuest(r),
      secLook(r),
      secThemes(r),
      secVs(r),
      secCharts(r),
      secVideos(r),
      h("p", { class: "footnote", text: "Ratings, summaries and flags are written by Gemini from the video itself. They are a guide, so open any video that matters." }),
    ];
    body.replaceChildren(...sections.filter(Boolean));
    refreshLive();
  }

  // actions + progress (refreshed on its own while an analysis runs)
  function refreshLive() {
    const live = $("#live");
    if (!live) return;
    const st = state.status || {};
    const running = !!st.running;
    const nodes = [];

    nodes.push(h("div", { class: "card" },
      h("div", { class: "actions" },
        h("button", { class: "btn", type: "button", onclick: openDialog }, "Add a video link"),
        h("button", { class: "btn", type: "button", onclick: connectYouTube }, st.connected ? "Reconnect YouTube" : "Connect YouTube"),
        h("button", { class: "btn primary", type: "button", disabled: running, onclick: analyse },
          running ? "Analysing…" : st.connected ? "Sync and analyse" : "Analyse videos")),
      h("div", { class: "conn" },
        h("span", { class: "dot" + (st.connected ? " on" : "") }),
        h("span", { text: st.connected ? "YouTube is connected" : "YouTube is not connected" }),
        st.connected && h("button", { class: "text-btn", type: "button", onclick: disconnect }, "Disconnect"))));

    if (running) nodes.push(progressCard(st));
    else if (st.error && state.dismissedError !== st.finished_at) {
      nodes.push(h("div", { class: "banner error" }, icon("alert"),
        h("div", {},
          h("div", { text: st.error }),
          h("button", { class: "text-btn", type: "button", onclick: () => { state.dismissedError = st.finished_at; refreshLive(); } }, "Dismiss"))));
    }
    live.replaceChildren(h("div", { style: "display:grid;gap:12px" }, ...nodes));
  }

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
          i < idx ? icon("check") : i === idx ? h("span", { class: "running" }) : h("span", { class: "pending" }),
          l))));
  }

  async function connectYouTube() {
    const st = state.status || {};
    if (!st.has_client_secret) { toast("client_secret.json was not found in the project folder."); return; }
    location.assign("/auth/start");
  }
  async function disconnect() {
    try { await api("/api/disconnect", { method: "POST" }); await loadStatus(); refreshLive(); toast("YouTube disconnected."); }
    catch (e) { toast(e.message); }
  }
  async function analyse() {
    const st = state.status || {};
    if (!st.has_gemini_key) { toast("GEMINI_API_KEY is not set in the terminal that runs Ember."); return; }
    if (!st.connected && !st.has_signals) { toast("Add a video link or connect YouTube first."); return; }
    try {
      await (st.connected
        ? api("/api/sync", { method: "POST", body: JSON.stringify({}) })
        : api("/api/run", { method: "POST", body: JSON.stringify({ sync: false }) }));
    } catch (e) { toast(e.message); return; }
    state.dismissedError = null;
    startPolling();
  }
  function startPolling() { if (!state.timer) { state.timer = setInterval(tick, 1500); tick(); } }
  function stopPolling() { clearInterval(state.timer); state.timer = null; }
  async function tick() {
    try {
      await loadStatus();
      if (state.screen === "ember") refreshLive();
      if (!state.status.running) {
        stopPolling();
        await loadReport();
        applyChildName();
        if (state.screen === "ember") { renderEmber(); $("#main").scrollTop = 0; }
        toast(state.status.error ? "The analysis stopped. The message is at the top of Ember." : "Analysis finished.");
      }
    } catch (_) { /* try again on the next tick */ }
  }

  // ---- summary + KPIs
  function secSummary(r) {
    if (!r.parent_summary) {
      return h("div", { class: "card" }, h("p", { class: "muted", text: "No analysis yet. Add a video link or connect YouTube, then choose Analyse videos." }));
    }
    const subs = (r.subscriptions || []).filter(Boolean).slice(0, 4);
    const meta = [r.generated_at ? `Analysed ${fmtDate(r.generated_at)}.` : "", subs.length ? `Follows ${subs.join(", ")}.` : ""].filter(Boolean).join(" ");
    return h("section", {}, h("p", { class: "summary", text: r.parent_summary }), meta && h("p", { class: "summary-meta", text: meta }));
  }
  function secKpis(r) {
    const t = r.totals;
    const k = (n, label, alert) => h("div", { class: "kpi" + (alert && n > 0 ? " alert" : "") }, h("b", { text: n }), h("span", { text: label }));
    return h("section", { class: "kpis" },
      k(t.videos, "videos reviewed"), k(t.worthwhile, "with real learning in them"),
      k(t.attention, "worth a look", true), k(t.transferable, "could become an activity"));
  }

  // ---- quest card
  function questCard(q, name, forPrint) {
    return h("article", { class: "quest", id: forPrint ? null : "questCard" },
      h("div", { class: "quest-head" },
        h("b", { text: "This week" }),
        h("div", { class: "quest-meta" }, h("b", { text: `${q.duration_minutes} min` }), h("span", { text: COST[q.cost] || cap(q.cost) }))),
      h("div", { class: "quest-body" },
        h("div", {}, h("h3", { text: q.title }), h("p", { class: "grows", text: `Grows: ${q.theme_name}` })),
        h("p", { text: q.why_this }),
        h("div", {}, h("h4", { text: "You will need" }), h("ul", { class: "need" }, (q.materials || []).map((m) => h("li", { text: m })))),
        h("div", {}, h("h4", { text: "Steps" }), h("ol", { class: "how" }, (q.steps || []).map((s) => h("li", { text: s })))),
        h("div", { class: "split" },
          h("div", {}, h("h4", { text: `${name} leads` }), h("p", { text: q.child_role })),
          h("div", {}, h("h4", { text: "You help by" }), h("p", { text: q.parent_role }))),
        h("p", { class: "key" }, h("b", { text: "Ask while you work: " }), q.conversation_prompt),
        h("p", { class: "key" }, h("b", { text: "Done when: " }), q.success_looks_like),
        q.safety_note && h("p", { class: "safe" }, h("b", { text: "Keep safe: " }), q.safety_note)),
      !forPrint && h("div", { class: "quest-foot" },
        h("button", { class: "btn", type: "button", onclick: printQuest }, icon("print"), "Print this card"),
        h("span", { text: "Prints just the card, so the activity happens away from the screen." })));
  }
  function secQuest(r) {
    if (!r.quest) return null;
    return h("section", { class: "e-section" }, h("h2", { text: "This week" }), questCard(r.quest, r.child, false));
  }
  function printQuest() {
    const r = state.report;
    if (!r || !r.quest) return;
    $("#printRoot").replaceChildren(questCard(r.quest, r.child, true));
    document.body.classList.add("printing");
    window.print();
  }
  window.addEventListener("afterprint", () => {
    document.body.classList.remove("printing");
    $("#printRoot").replaceChildren();
  });

  // ---- worth a look
  function secLook(r) {
    const byId = new Map(r.videos.map((v) => [v.video_id, v]));
    const items = r.attention.map((id) => byId.get(id)).filter(Boolean);
    if (!items.length) return null;
    return h("section", { class: "e-section" }, h("h2", { text: "Worth a look" }),
      h("div", { class: "card look" }, items.map((v) => {
        const flags = flagLabels(v).join(", ");
        const kind = v.parent_flag === "review" ? "review" : "note";
        return h("div", { class: "look-item" },
          h("div", { class: "look-flag " + kind }, icon(kind === "review" ? "alert" : "warn"), kind === "review" ? "Review" : "Note"),
          h("div", { class: "look-title", text: v.title }),
          (flags || v.safety_note) && h("p", {}, flags && h("b", { text: flags + ". " }), v.safety_note),
          v.conversation_starter && h("p", {}, h("b", { text: `Ask ${r.child}: ` }), v.conversation_starter));
      })));
  }

  // ---- themes + graph
  function secThemes(r) {
    if (!r.themes.length) return null;
    const box = h("div", {});
    const wrap = h("section", { class: "e-section" }, h("h2", { text: `What draws ${r.child}` }), box);
    renderThemes(box);
    return wrap;
  }
  function renderThemes(box) {
    const r = state.report;
    const active = r.themes.find((t) => t.id === state.theme) || r.themes[0];
    const color = (t) => PALETTE[r.themes.indexOf(t) % PALETTE.length];
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
        h("span", { class: "pill", text: plural(active.video_count, "video", "videos") }),
        h("span", { class: "pill", text: `Confidence: ${active.confidence}` }),
        h("span", { class: "pill", text: `Trend: ${TREND[active.trajectory] || active.trajectory}` }),
        h("span", { class: "pill", text: `Easy to do offline: ${active.transferability}` })),
      h("div", {}, h("h4", { text: "Why these belong together" }), h("p", { text: active.reasoning })),
      h("div", {}, h("h4", { text: "What Ember saw" }), h("ul", {}, (active.evidence || []).map((e) => h("li", { class: "b", text: e })))),
      h("div", {}, h("h4", { text: "Where it could lead" }), h("p", { text: active.growth_direction })),
      h("div", {}, h("h4", { text: "Videos" }), h("ul", { class: "links" }, links.map((v) => {
        const u = safeVideoUrl(v.url);
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
      const lines = wrapWords(nodeLabel, 15, 3);
      const blockH = Math.max(ids.length * rowH, lines.length * 14 + 8, nodeR * 2 + 6);
      const cy = y + blockH / 2;
      const y0 = y + (blockH - ids.length * rowH) / 2;
      const g = sv("g", { class: "g-group" + (dim ? " dim" : ""), onclick: theme ? () => pick(theme) : null });
      ids.forEach((id, i) => {
        const v = byId.get(id);
        const ly = y0 + i * rowH + rowH / 2;
        g.append(sv("path", { d: `M ${nodeX + nodeR} ${cy} C ${nodeX + 50} ${cy}, ${leafX - 50} ${ly}, ${leafX - 7} ${ly}`, fill: "none", stroke, "stroke-width": 1.6, "stroke-opacity": theme ? 1 : 0.5 }));
        g.append(sv("circle", { cx: leafX, cy: ly, r: 4.5, fill: stroke }));
        g.append(sv("text", { class: "g-leaf", x: leafX + 10, y: ly + 4 }, sv("title", { text: v ? v.title : id }), trunc(v ? v.title : id, 24)));
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

  // ---- titles vs what holds attention
  function secVs(r) {
    const rows = r.videos.filter((v) => v.surface_topic && v.underlying_draw);
    if (!rows.length) return null;
    const box = h("div", {});
    const draw = () => {
      const shown = state.showAllVs ? rows : rows.slice(0, 5);
      const more = rows.length - 5;
      box.replaceChildren(
        h("div", { class: "card vs" },
          h("div", { class: "vs-row head" }, h("span", { text: "What the title says" }), h("span", { text: "What holds attention" })),
          shown.map((v) => h("div", { class: "vs-row" }, h("span", { text: cap(v.surface_topic) }), h("span", { text: v.underlying_draw }))),
          more > 0 && h("button", { class: "text-btn vs-more", type: "button", onclick: () => { state.showAllVs = !state.showAllVs; draw(); } },
            state.showAllVs ? "Show fewer" : `Show ${more} more`)));
    };
    draw();
    return h("section", { class: "e-section" },
      h("h2", { text: "Titles versus what holds attention" }),
      h("p", { class: "muted small", style: "margin:-4px 4px 12px", text: "A tool that reads only titles would sort these by subject. Ember watches each video and notes what actually holds the attention, which is how videos about different things end up in the same theme." }),
      box);
  }

  // ---- charts
  function secCharts(r) {
    if (!r.videos.length) return null;
    const max = Math.max(1, ...r.domains.map((d) => d.count));
    const total = Math.max(1, r.videos.length);
    return h("section", { class: "e-section" },
      h("h2", { text: `What ${r.child} watches` }),
      h("div", { style: "display:grid;gap:12px" },
        h("div", { class: "card" }, h("div", { class: "chart-title", text: "By subject" }),
          h("div", { class: "rows" }, r.domains.map((d) =>
            h("div", {}, h("div", { class: "row-label" }, h("span", { text: d.label }), h("b", { text: d.count })),
              h("div", { class: "track" }, h("i", { style: `width:${Math.round((d.count / max) * 100)}%` })))))),
        h("div", { class: "card" }, h("div", { class: "chart-title", text: "How much is learned" }),
          h("div", { class: "stack", role: "img", "aria-label": "Share of videos by learning value" },
            EDU.filter(([k]) => r.education[k]).map(([k]) => h("i", { class: "edu-" + k, style: `flex:${r.education[k] / total}` }))),
          h("ul", { class: "legend" }, EDU.map(([k, label]) =>
            h("li", {}, h("span", { class: "sw edu-" + k }), label, h("b", { text: r.education[k] || 0 })))),
          h("p", { class: "note", text: "High means a child could explain or do something specific afterwards. None is pure entertainment, which is fine in moderation." }))));
  }

  // ---- every video
  function secVideos(r) {
    if (!r.videos.length) return null;
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
      const list = r.videos.filter(fn);
      box.replaceChildren(chips,
        list.length ? h("div", { class: "card", style: "padding-top:0;padding-bottom:0" }, list.map((v) => videoCard(v)))
          : h("div", { class: "card empty", text: "No videos match this filter." }));
    };
    draw();
    return h("section", { class: "e-section" }, h("h2", { text: "Every video" }), box);
  }

  function videoCard(v) {
    const u = safeVideoUrl(v.url);
    const tile = () => h("div", { class: "thumb", "aria-hidden": "true", text: (v.title || "?").charAt(0).toUpperCase() });
    const t = safeThumb(v.thumbnail);
    let thumb;
    if (t) {
      thumb = h("img", { class: "thumb", src: t, alt: "", loading: "lazy", referrerpolicy: "no-referrer" });
      thumb.addEventListener("error", () => thumb.replaceWith(tile()));
    } else thumb = tile();

    const flags = flagLabels(v);
    const list = (title, items) => items && items.length ? h("div", {}, h("h4", { text: title }), h("ul", {}, items.map((i) => h("li", { text: i })))) : null;
    const para = (title, text) => text ? h("div", {}, h("h4", { text: title }), h("p", { text })) : null;

    return h("article", { class: "video" },
      h("div", { class: "video-top" }, thumb,
        h("div", {}, h("h3", { text: v.title }),
          h("div", { class: "meta", text: [v.domain_label, v.topic].filter(Boolean).join(", ") }),
          h("div", { class: "meta", text: v.liked_at ? `Liked ${fmtDate(v.liked_at)}` : "" }))),
      h("p", { class: "sum", text: v.summary }),
      h("div", { class: "pills" },
        h("span", { class: "pill", text: `Learning: ${cap(v.educational_value)}` }),
        v.age_suitability && h("span", { class: "pill", text: AGE[v.age_suitability] || v.age_suitability }),
        flags.map((f) => h("span", { class: "pill flag-pill" + (v.parent_flag === "note" ? " note" : ""), text: f }))),
      h("details", {},
        h("summary", {}, "Details and questions", icon("expand")),
        h("div", { class: "detail" },
          list("What happens", v.key_points),
          para("Why the learning rating", v.educational_reasoning),
          list("What they may pick up", v.what_child_may_learn),
          para("Heads up", v.safety_note),
          para("Ask together", v.conversation_starter),
          para("Try it offline", v.follow_up_idea),
          u && h("a", { href: u, target: "_blank", rel: "noopener noreferrer", text: "Open on YouTube" }))));
  }

  // ------------------------------------------------------------ wiring + start
  function wire() {
    $("#openDrawer").addEventListener("click", openDrawer);
    $("#scrim").addEventListener("click", closeDrawer);
    $("#emberBack").addEventListener("click", () => go("#/space"));
    // Screen time is the home tab, Space is the new tab. Controls and Location stay static.
    $$("[data-nav]").forEach((b) => b.addEventListener("click", () => go(b.dataset.nav === "space" ? "#/space" : "#/")));
    $("#addCancel").addEventListener("click", closeDialog);
    $("#dialogScrim").addEventListener("click", closeDialog);
    $("#addSave").addEventListener("click", saveLink);
    $("#addInput").addEventListener("keydown", (e) => { if (e.key === "Enter") saveLink(); });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape") return;
      if (!$("#addDialog").hidden) closeDialog();
      else if (!$("#drawer").hidden) closeDrawer();
    });
    window.addEventListener("hashchange", route);
  }

  const AUTH_MESSAGES = {
    missing_client_secret: "client_secret.json was not found in the project folder.",
    access_denied: "Access was not allowed, so nothing was connected.",
    expired_session: "The sign-in took too long. Choose Connect YouTube to try again.",
    token_exchange_failed: "Google sign-in did not complete. Choose Connect YouTube to try again.",
  };

  async function init() {
    wire();
    const qs = new URLSearchParams(location.search);
    let message = "";
    if (qs.has("connected")) message = "YouTube connected. Choose Sync and analyse to read the likes.";
    else if (qs.has("auth_error")) message = AUTH_MESSAGES[qs.get("auth_error")] || "Sign-in did not complete.";
    if (message) history.replaceState(null, "", "/#/space/ember");
    route();
    try { await Promise.all([loadReport(), loadStatus()]); }
    catch (e) { state.loadError = e.message; }
    applyChildName();
    route();
    if (message) toast(message);
    if (state.status && state.status.running) startPolling();
  }

  init();
})();
