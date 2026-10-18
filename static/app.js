/* app.js: start-up only. All the real work lives in static/js/ (core, shell, ember/*).
   Load order is set in index.html: core.js, shell.js, ember/*.js, then this file. */
(() => {
  "use strict";
  const FL = window.FL;
  const { state } = FL;

  const AUTH_MESSAGES = {
    missing_client_secret: "client_secret.json was not found in the project folder.",
    access_denied: "Access was not allowed, so nothing was connected.",
    expired_session: "The sign-in took too long. Choose Connect YouTube to try again.",
    token_exchange_failed: "Google sign-in did not complete. Choose Connect YouTube to try again.",
  };

  async function init() {
    FL.wireShell();

    // Coming back from Google sign-in: /?connected=1 or /?auth_error=...
    const qs = new URLSearchParams(location.search);
    let message = "";
    if (qs.has("connected")) message = "YouTube connected. Choose Sync and analyse to read the likes.";
    else if (qs.has("auth_error")) message = AUTH_MESSAGES[qs.get("auth_error")] || "Sign-in did not complete.";
    if (message) history.replaceState(null, "", "/#/ember");

    FL.route();   // draws "Loading…" if we are on Ember
    try { await Promise.all([FL.loadReport(), FL.loadStatus()]); }
    catch (e) { state.loadError = e.message; }
    FL.applyChildName();
    FL.route();   // draws the real page now that the data is in
    if (message) FL.toast(message);
    if (state.status && state.status.running) FL.startPolling();
  }

  init();
})();
