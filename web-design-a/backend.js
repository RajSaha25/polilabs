/* ============================================================
   POLILABS — Backend adapter
   Connects the Claude-Design prototype to the real FastAPI
   backend (server.py). Replaces the static data.js mock.

   Backend contract (server.py):
     POST /chat                       SSE: text | tool_call | tool_result | done | error
     GET  /api/bill/{id}              bill metadata + top-level ToC
     GET  /api/bill/{id}/sections     full nested section tree (verbatim text)
     GET  /api/bill/{id}/defined_terms
     GET  /api/bill/{id}/amendments
     GET  /api/citation_graph?section_id=...

   Everything here is plain JS on `window` — no build step. The
   mappers translate backend JSON into the shapes the design's
   components (left-rail / text-panel / decomp-panel) consume.
   ============================================================ */

// Backend origin. CORS is open on server.py, so an absolute URL works
// even when this prototype is served from a different port.
window.POLILABS_BACKEND =
  (window.localStorage && localStorage.getItem("polilabs_backend")) ||
  "https://consulting-theaters-barnes-compare.trycloudflare.com";

(function () {
  const BACKEND = window.POLILABS_BACKEND;

  // ── auth: every /chat and /api/* call carries the Bearer token ──────
  function authHeaders() {
    const token = window.PolilabsAuth && window.PolilabsAuth.getToken();
    return token ? { Authorization: "Bearer " + token } : {};
  }

  // A 401 means the session token is missing/expired. Drop it and reload
  // — Root (app.jsx) then falls back to the sign-in screen.
  function handleUnauthorized() {
    if (window.PolilabsAuth) window.PolilabsAuth.logout();
    window.location.reload();
  }

  // ── SSE: stream a chat turn from POST /chat ─────────────────────────
  async function streamChat(message, history, onEvent, signal) {
    let res;
    try {
      res = await fetch(BACKEND + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...authHeaders() },
        body: JSON.stringify({ message, history: history || [] }),
        signal,
      });
    } catch (e) {
      onEvent({ type: "error", message: "request failed: " + e });
      return;
    }
    if (res.status === 401) {
      handleUnauthorized();
      return;
    }
    if (!res.ok || !res.body) {
      onEvent({ type: "error", message: "backend returned HTTP " + res.status });
      return;
    }
    const reader = res.body.getReader();
    const dec = new TextDecoder("utf-8");
    let buf = "";
    while (true) {
      let chunk;
      try {
        chunk = await reader.read();
      } catch (e) {
        onEvent({ type: "error", message: "stream interrupted" });
        return;
      }
      if (chunk.done) break;
      buf += dec.decode(chunk.value, { stream: true });
      const frames = buf.split("\n\n");
      buf = frames.pop() || "";
      for (const frame of frames) {
        const line = frame.split("\n").find((l) => l.startsWith("data: "));
        if (!line) continue;
        try {
          onEvent(JSON.parse(line.slice(6)));
        } catch (e) {
          /* skip malformed frame */
        }
      }
    }
  }

  // ── REST: GET /api/* helper ─────────────────────────────────────────
  async function apiGet(path) {
    const res = await fetch(BACKEND + path, { headers: authHeaders() });
    if (res.status === 401) {
      handleUnauthorized();
      throw new Error("unauthorized");
    }
    if (!res.ok) throw new Error("HTTP " + res.status + " for " + path);
    return res.json();
  }

  // ── ID + label helpers ──────────────────────────────────────────────
  const BILL_TYPE_LABEL = {
    hr: "H.R.", s: "S.", hjres: "H.J.Res.", sjres: "S.J.Res.",
    hconres: "H.Con.Res.", sconres: "S.Con.Res.",
  };

  function prettyBillId(id) {
    if (!id) return "";
    const parts = String(id).split("-");
    if (parts.length < 3) return String(id);
    const type = parts[1], num = parts[2];
    return (BILL_TYPE_LABEL[type] || type.toUpperCase()) + " " + num;
  }

  function congressOf(id) {
    const n = parseInt(String(id).split("-")[0], 10);
    return Number.isFinite(n) ? n : null;
  }

  function deriveSecNum(citation) {
    if (!citation) return "";
    const m = String(citation).match(/Sec\.\s*([0-9A-Za-z()]+)/);
    return m ? "SEC. " + m[1] + "." : "";
  }

  function deriveMarker(citation) {
    if (!citation) return "";
    const m = String(citation).match(/Sec\.\s*([0-9A-Za-z()]+)/);
    return m ? "Sec. " + m[1] : "";
  }

  // Last parenthetical group of a citation — the subsection's own marker.
  // "Sec. 3(a)(1)" → "(1)";  "Sec. 3(a)" → "(a)";  "Sec. 3" → "§ 3".
  function lastMarker(citation) {
    if (!citation) return "";
    const groups = String(citation).match(/\([0-9A-Za-z]+\)/g);
    if (groups && groups.length) return groups[groups.length - 1];
    const m = String(citation).match(/Sec\.\s*([0-9A-Za-z]+)/);
    return m ? "§ " + m[1] : "";
  }

  function escapeHtml(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function formatStatute(targetId) {
    if (!targetId) return "";
    const m = String(targetId).match(/usc\/(\w+)\/([\w.\-()]+)/);
    if (m) return m[1] + " U.S.C. " + m[2];
    return String(targetId).replace(/^statute:/, "");
  }

  // ── Bill list: derive ranked "sources" from the agent's tool calls ──
  // Every /chat turn calls tools; their results name the bills the
  // answer was sourced from. We dedupe by bill_id, preserving the
  // order the agent surfaced them in.
  function billsFromToolResults(toolResults) {
    const order = [];
    const fields = new Map();
    function add(billId, f) {
      if (!billId) return;
      if (!fields.has(billId)) { order.push(billId); fields.set(billId, {}); }
      const cur = fields.get(billId);
      for (const k in f) if (cur[k] == null && f[k] != null) cur[k] = f[k];
    }
    for (const tr of toolResults || []) {
      const r = tr.result || {};
      if (Array.isArray(r.hits)) {                       // search_corpus
        for (const h of r.hits) add(h.bill_id, {
          short: h.short_title || h.title, title: h.title, sponsor: h.sponsor,
          congress: h.congress, tier: h.tier, summary: h.summary,
          relevance: h.relevance_score, matches: h.matched_keywords,
          introduced: h.introduced_date,
        });
      }
      if (Array.isArray(r.matches)) {                    // find_bills_defining
        for (const m of r.matches) add(m.bill_id, {
          short: m.bill_short_title || m.bill_title, title: m.bill_title,
          congress: m.congress, matches: m.surface_form ? [m.surface_form] : null,
        });
      }
      if (Array.isArray(r.definitions)) {                // find_definitions_of
        for (const d of r.definitions) add(d.bill_id, {
          short: d.bill_short_title, congress: d.congress,
        });
      }
      if (Array.isArray(r.bills)) {                      // find_bills_amending
        for (const b of r.bills) add(b.bill_id, {
          short: b.bill_short_title || b.bill_title, title: b.bill_title,
          congress: b.congress,
        });
      }
      if (tr.name === "get_bill" && r.bill_id) {         // single-bill metadata
        add(r.bill_id, {
          short: r.short_title || r.title, title: r.title, sponsor: r.sponsor,
          congress: r.congress, tier: r.tier, introduced: r.introduced_date,
          cosponsors: Array.isArray(r.cosponsors) ? r.cosponsors.length : null,
        });
      }
      if (r.bill_id) add(r.bill_id, {});                 // any other single-bill tool
    }
    const bills = order.map((id) => {
      const f = fields.get(id);
      return {
        id,
        bill_id: prettyBillId(id),
        short: f.short || f.title || prettyBillId(id),
        congress: f.congress || congressOf(id),
        sponsor: f.sponsor || null,
        cosponsors: f.cosponsors || 0,
        introduced: f.introduced || "",
        tier: f.tier || null,
        relevance: f.relevance != null ? f.relevance : null,
        matches: Array.isArray(f.matches) ? f.matches.slice(0, 3) : [],
        summary: f.summary || "",
      };
    });
    // search_corpus returns a raw FTS rank score (unbounded, e.g. ~18),
    // not a 0–1 fraction. Normalise against the strongest hit so the
    // relevance meter reads as a relative 0–100, not a raw "577".
    const maxRel = bills.reduce((m, b) => (b.relevance > m ? b.relevance : m), 0);
    if (maxRel > 0) {
      for (const b of bills) {
        if (b.relevance != null) b.relevance = b.relevance / maxRel;
      }
    }
    return bills;
  }

  // ── Section tree → center Text panel shape ──────────────────────────
  // Escape verbatim text, keep XML line breaks — never reflow the law.
  function verbatimHtml(text) {
    return escapeHtml(text).replace(/\n/g, "<br/>");
  }

  // A node's OWN text — its chapeau (for an internal node) or its whole
  // body (for a leaf). The backend `/sections` aggregator now computes
  // this server-side (text_full minus each child's rendered segment), so
  // a node's own text is simply its `text` field.
  function ownText(node) {
    return String((node && node.text) || "").trim();
  }

  // Format any tree node into renderable verbatim blocks: the node's own
  // text (leafHtml — chapeau, or full text if it has no children) plus a
  // flattened depth-tagged list of every descendant. Shared by the Text
  // panel and the Definition cards so both render statute text the same.
  function formatNode(node) {
    const blocks = [];
    function walk(n, depth, prefix) {
      const own = ownText(n);
      const kids = n.children || [];
      const marker = (prefix || "") + lastMarker(n.canonical_citation);
      // A node with no own text and no heading is a pure grouping marker
      // (e.g. "(3)" that just wraps "(A)/(B)"). Don't render an empty
      // line for it — fold its marker into the first child: "(3)(A)".
      if (!own && !n.heading && kids.length) {
        kids.forEach((c, i) => walk(c, depth, i === 0 ? marker : ""));
        return;
      }
      blocks.push({
        id: n.section_id,
        depth: depth,
        marker: marker,
        heading: n.heading || "",
        html: verbatimHtml(own),
      });
      for (const c of kids) walk(c, depth + 1, "");
    }
    for (const c of node.children || []) walk(c, 0, "");
    return { leafHtml: verbatimHtml(ownText(node)), blocks: blocks };
  }

  function findNode(tree, id) {
    const stack = ((tree && tree.sections) || []).slice();
    while (stack.length) {
      const n = stack.pop();
      if (n.section_id === id) return n;
      for (const c of n.children || []) stack.push(c);
    }
    return null;
  }

  function sectionsTreeToText(tree) {
    return ((tree && tree.sections) || []).map((s) => {
      const f = formatNode(s);
      return {
        id: s.section_id,
        num: deriveMarker(s.canonical_citation),
        title: s.heading || "(untitled section)",
        blocks: f.blocks,
        leafHtml: f.leafHtml,
      };
    });
  }

  // ── Section tree → Structure-mode outline ───────────────────────────
  function sectionsTreeToStructure(tree, stats) {
    const out = [];
    function walk(node, level) {
      out.push({
        id: node.section_id,
        marker: deriveMarker(node.canonical_citation) || "§",
        title: node.heading || "",
        level: level,
        anchor: node.section_id,
        pages: "",
      });
      for (const c of node.children || []) walk(c, level + 1);
    }
    for (const s of (tree && tree.sections) || []) walk(s, 1);
    return { sections: out, stats: stats };
  }

  // ── defined_terms result → Definition-mode cards ────────────────────
  // The definition's verbatim text is rendered from its node in the
  // section tree (same formatter as the Text panel) so a structured
  // definition shows as indented subsections, not one run-on block.
  function mapDefinitions(res, tree) {
    const terms = (res && res.terms) || [];
    return terms.map((t, i) => {
      const node = tree ? findNode(tree, t.defining_section_id) : null;
      return {
        id: t.defined_term_id || "def-" + i,
        term: t.surface_form || "(term)",
        kind: t.definition_type === "by_reference" ? "byref" : "direct",
        anchor: t.defining_section_id,
        // Prefer the structured tree formatting; fall back to the
        // verbatim definition_text the API already provides if the node
        // is missing or carries no text.
        body: (() => {
          const fmt = node ? formatNode(node) : null;
          const hasText = fmt && (fmt.leafHtml ||
            (fmt.blocks || []).some((b) => b.html));
          return hasText
            ? fmt
            : { leafHtml: verbatimHtml(t.definition_text || ""), blocks: [] };
        })(),
        refs_to: t.by_reference_target_citation || null,
        cite: t.defining_section_citation || "",
        verified: true, // definitions are mechanically extracted from the bill XML
      };
    });
  }

  // ── amendments result → Amendment-mode cards ────────────────────────
  const OP_MAP = {
    strike: "strike", insert: "insert", strike_and_insert: "replace",
    replace: "replace", add_at_end: "add-end", redesignate: "replace",
    repeal: "strike", other: "insert",
  };
  function mapAmendments(res) {
    const ams = (res && res.amendments) || [];
    return ams.map((a, i) => {
      const rows = [];
      if (a.before_text) rows.push({ kind: "del", text: a.before_text });
      if (a.after_text) rows.push({ kind: "add", text: a.after_text });
      if (!rows.length && a.operation_text)
        rows.push({ kind: "add", text: a.operation_text });
      return {
        id: a.amendment_id || "am-" + i,
        op: OP_MAP[a.operation_type] || "insert",
        anchor: a.source_section_id,
        target: a.target_canonical_citation || "",
        target_label: a.operation_text || a.target_canonical_citation || "amendment",
        rows: rows,
        cite: a.source_section_citation || "",
        // v1 corpus: target_text_unverified is true (OLRC text not yet
        // ingested). Only show "verified" when the backend says so.
        verified: a.target_text_unverified === false,
      };
    });
  }

  // ── citation graphs (per top-level section) → Citation-mode groups ──
  async function fetchCitationGroups(tree) {
    const top = (tree && tree.sections) || [];
    const groups = [];
    for (const s of top) {
      let g;
      try {
        g = await apiGet(
          "/api/citation_graph?section_id=" +
            encodeURIComponent(s.section_id) + "&direction=out"
        );
      } catch (e) {
        continue;
      }
      const edges = (g && g.edges) || [];
      if (!edges.length) continue;
      groups.push({
        group: (deriveSecNum(s.canonical_citation) || s.heading || "Section")
          .replace(/\.$/, "") + " — " + (s.heading || ""),
        items: edges.map((e, i) => ({
          id: s.section_id + "-c" + i,
          ref: formatStatute(e.target_id),
          title: e.type ? e.type + " reference" : "citation",
          source: "U.S. Code",
          verified: true,
          anchor: s.section_id,
        })),
      });
    }
    return groups;
  }

  // ── Load a bill's full detail (Text + Structure + Definition + Amend) ─
  // /sections is load-bearing: if it fails or comes back error-shaped
  // (a transient backend failure), throw so the caller can retry rather
  // than cache a permanently-blank bill. defined_terms / amendments are
  // non-critical and degrade to empty on their own.
  async function loadBillDetail(billId) {
    const [treeR, defsR, amsR] = await Promise.allSettled([
      apiGet("/api/bill/" + encodeURIComponent(billId) + "/sections"),
      apiGet("/api/bill/" + encodeURIComponent(billId) + "/defined_terms"),
      apiGet("/api/bill/" + encodeURIComponent(billId) + "/amendments"),
    ]);
    if (treeR.status !== "fulfilled" || !treeR.value ||
        treeR.value.error || treeR.value.not_found) {
      throw new Error("section tree unavailable for " + billId);
    }
    const tree = treeR.value;
    const defs = defsR.status === "fulfilled" ? mapDefinitions(defsR.value, tree) : [];
    const ams = amsR.status === "fulfilled" ? mapAmendments(amsR.value) : [];
    const text = sectionsTreeToText(tree);
    const structure = sectionsTreeToStructure(tree, {
      sections: text.length,
      definitions: defs.length,
      amendments: ams.length,
      citations: 0,
    });
    return {
      _tree: tree,            // kept for lazy citation fetch
      text: text,
      structure: structure,
      definitions: defs,
      amendments: ams,
      citations: null,        // lazily filled when Citation mode opens
    };
  }

  // ── Expose ──────────────────────────────────────────────────────────
  window.PolilabsBackend = {
    BACKEND: BACKEND,
    streamChat: streamChat,
    apiGet: apiGet,
    prettyBillId: prettyBillId,
    billsFromToolResults: billsFromToolResults,
    loadBillDetail: loadBillDetail,
    fetchCitationGroups: fetchCitationGroups,
  };
})();
