/* ============================================================
   POLILABS — Connector-token client (bring-your-own-agent)

   Mint / list / revoke the long-lived tokens a researcher pastes
   into their own approved agent (a ChatGPT Action, an MCP client).
   Same Bearer auth as the rest of the app. Exposed on
   window.PolilabsConnector. Loaded after auth.js + backend.js.
   ============================================================ */
(function () {
  const BACKEND =
    window.POLILABS_BACKEND ||
    (window.localStorage && localStorage.getItem("polilabs_backend")) ||
    "https://polilabs-backend.fly.dev";

  function authHeaders() {
    const token = window.PolilabsAuth && window.PolilabsAuth.getToken();
    return token ? { Authorization: "Bearer " + token } : {};
  }

  async function _json(res) {
    let data = {};
    try { data = await res.json(); } catch (e) { /* no body */ }
    if (!res.ok) {
      const detail = data && data.detail;
      throw new Error(typeof detail === "string" ? detail : "Request failed (HTTP " + res.status + ").");
    }
    return data;
  }

  // Mint a new connector token. The plaintext token is returned ONCE.
  async function mint(label) {
    const res = await fetch(BACKEND + "/auth/connector-token", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({ label: label || "" }),
    });
    return _json(res);
  }

  async function list() {
    const res = await fetch(BACKEND + "/auth/connector-tokens", { headers: authHeaders() });
    return _json(res);
  }

  async function revoke(jti) {
    const res = await fetch(BACKEND + "/auth/connector-token/" + encodeURIComponent(jti), {
      method: "DELETE",
      headers: authHeaders(),
    });
    return _json(res);
  }

  // The backend origin, surfaced so the panel can show the OpenAPI URL
  // a user pastes into a ChatGPT Action.
  function backendUrl() { return BACKEND; }

  window.PolilabsConnector = { mint, list, revoke, backendUrl };
})();
