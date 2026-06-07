/* ============================================================
   POLILABS — Annotations client (plain JS, no build step)

   Per-user, in-bill highlights + notes. Talks to the gated
   /api/annotations REST surface (server.py), carrying the same
   Bearer token as backend.js. Loaded after backend.js so both
   window.POLILABS_BACKEND and window.PolilabsAuth are ready.

   Backend contract (server.py):
     GET    /api/annotations?bill_id=...        -> [row, ...]
     POST   /api/annotations  {bill_id, section_id, quote, body, color}
                                                -> row
     PATCH  /api/annotations/{id} {body?, color?}
                                                -> row
     DELETE /api/annotations/{id}               -> {ok: true}

   A row: { id, bill_id, section_id, quote, body, color, source,
            created_at, updated_at }.

   Exposed on window.PolilabsAnnotations.
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
      throw new Error(
        typeof detail === "string"
          ? detail
          : "Request failed (HTTP " + res.status + ").",
      );
    }
    return data;
  }

  // List every annotation the signed-in user has on one bill.
  async function list(billId) {
    const res = await fetch(
      BACKEND + "/api/annotations?bill_id=" + encodeURIComponent(billId),
      { headers: authHeaders() },
    );
    return _json(res);
  }

  // Create a highlight + note. `section_id` may be null (bill-level).
  async function create({ bill_id, section_id, quote, body, color }) {
    const res = await fetch(BACKEND + "/api/annotations", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        bill_id,
        section_id: section_id || null,
        quote: quote || "",
        body: body || "",
        color: color || "yellow",
      }),
    });
    return _json(res);
  }

  // Patch note text and/or colour. Only provided fields change.
  async function update(id, patch) {
    const res = await fetch(BACKEND + "/api/annotations/" + id, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify(patch || {}),
    });
    return _json(res);
  }

  async function remove(id) {
    const res = await fetch(BACKEND + "/api/annotations/" + id, {
      method: "DELETE",
      headers: authHeaders(),
    });
    return _json(res);
  }

  // Every annotation the signed-in user has, across all bills (most
  // recent first). Powers the "all notes" view. Same endpoint as list(),
  // just without a bill_id filter.
  async function listAll() {
    const res = await fetch(BACKEND + "/api/annotations", {
      headers: authHeaders(),
    });
    return _json(res);
  }

  window.PolilabsAnnotations = { list, listAll, create, update, remove };
})();
