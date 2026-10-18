/* core.js: helpers, constants, shared state and API calls.
   Loaded first. Every other script hangs off window.FL (plain scripts, no ES modules). */
(() => {
  "use strict";
  const FL = (window.FL = window.FL || {});

  // ------------------------------------------------------------ DOM helpers
  const SVG_NS = "http://www.w3.org/2000/svg";
  FL.$ = (sel, root = document) => root.querySelector(sel);
  FL.$$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

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
  // Everything from YouTube or Gemini goes in as text, never as HTML.
  FL.h = (tag, attrs, ...kids) => { const el = document.createElement(tag); setAttrs(el, attrs); return add(el, kids); };
  FL.sv = (tag, attrs, ...kids) => { const el = document.createElementNS(SVG_NS, tag); setAttrs(el, attrs); return add(el, kids); };
  FL.icon = (name, cls = "") =>
    FL.sv("svg", { class: ("ic " + cls).trim(), "aria-hidden": "true" }, FL.sv("use", { href: "#i-" + name }));

  // ------------------------------------------------------------ text + url helpers
  FL.cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : "");
  FL.trunc = (s, n) => (s.length > n ? s.slice(0, n - 1).trimEnd() + "…" : s);
  FL.plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  FL.fmtDate = (iso) => {
    const d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
  };
  FL.safeVideoUrl = (u) => (/^https:\/\/(www\.)?(youtube\.com|youtu\.be)\//.test(u || "") ? u : "");
  FL.safeThumb = (u) => (/^https:\/\/i\.ytimg\.com\//.test(u || "") ? u : "");
  FL.wrapWords = (text, max, maxLines) => {
    const lines = [];
    let line = "";
    for (const w of text.split(/\s+/)) {
      if (line && (line + " " + w).length > max) { lines.push(line); line = w; }
      else line = line ? line + " " + w : w;
    }
    if (line) lines.push(line);
    return lines.slice(0, maxLines);
  };

  // ------------------------------------------------------------ labels
  FL.PALETTE = ["#8ab4f8", "#f4a37c", "#7fd3a5", "#f6c453", "#c9a0f5", "#f08fc0"];
  FL.AGE = { all_ages: "All ages", age_8_plus: "Age 8+", age_13_plus: "Age 13+", age_16_plus: "Age 16+", adult: "Adults" };
  FL.FLAG = {
    violence_or_gore: "Violence", scary_or_disturbing: "Scary imagery", strong_language: "Strong language",
    mature_themes: "Mature themes", risky_challenge_or_imitable_danger: "Risky to copy",
    heavy_advertising_or_buying_pressure: "Pushes buying", gambling_like_mechanics: "Chance-based rewards",
    misleading_or_false_claims: "Misleading claims", other: "Other",
  };
  FL.TREND = { rising: "Rising", steady: "Steady", fading: "Fading", unclear: "Too early to tell" };
  FL.COST = { free: "Free", low: "Low cost", medium: "Medium cost" };
  FL.EDU = [["high", "High"], ["moderate", "Moderate"], ["low", "Low"], ["none", "None"]];
  FL.flagLabels = (v) =>
    (v.safety_flags || []).filter((f) => f !== "none").map((f) => FL.FLAG[f] || FL.cap(f.replace(/_/g, " ")));

  // ------------------------------------------------------------ state + API
  FL.state = {
    report: null, status: null, loadError: null,
    screen: "home",          // "home" (Screen time) or "ember"
    tab: "overview",         // which Ember section is open
    theme: null, filter: "all", showAllVs: false,
    timer: null, dismissedError: null, toastTimer: null,
  };

  FL.api = async (path, opts = {}) => {
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
  };
  FL.loadReport = async () => {
    FL.state.report = await FL.api("/api/report");
    const ids = FL.state.report.themes.map((t) => t.id);
    if (!ids.includes(FL.state.theme)) FL.state.theme = ids[0] || null;
  };
  FL.loadStatus = async () => { FL.state.status = await FL.api("/api/status"); };
  FL.child = () => (FL.state.report && FL.state.report.child) || "Llamie";

  // ------------------------------------------------------------ section registry
  // Each Ember section file calls FL.registerSection({ id, order, label, title(r), desc(r), render(r) }).
  // The tab bar and the page are built from this list, so adding a section is one new file.
  FL.sections = [];
  FL.registerSection = (def) => {
    FL.sections.push(def);
    FL.sections.sort((a, b) => a.order - b.order);
  };
  // A friendly card for a section that has nothing to show yet.
  FL.emptyCard = (text) => FL.h("div", { class: "card empty", text });
})();
