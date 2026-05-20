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
  "http://localhost:8000";

(function () {
  const BACKEND = window.POLILABS_BACKEND;

  // ── SSE: stream a chat turn from POST /chat ─────────────────────────
  async function streamChat(message, history, onEvent, signal) {
    let res;
    try {
      res = await fetch(BACKEND + "/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, history: history || [] }),
        signal,
      });
    } catch (e) {
      onEvent({ type: "error", message: "request failed: " + e });
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
    const res = await fetch(BACKEND + path);
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
    return order.map((id) => {
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
  }

  // ── Section tree → center Text panel shape ──────────────────────────
  // Escape verbatim text, keep XML line breaks — never reflow the law.
  function verbatimHtml(text) {
    return escapeHtml(text).replace(/\n/g, "<br/>");
  }

  // The backend `text` field is recursive (text_full): a parent's text
  // already contains every descendant's text. To render readably without
  // duplication we walk the tree and emit verbatim text ONLY at leaves;
  // internal nodes contribute their heading/marker as structure.
  function sectionsTreeToText(tree) {
    const secs = (tree && tree.sections) || [];
    return secs.map((s) => {
      const blocks = [];
      function walk(node, depth) {
        const kids = node.children || [];
        const isLeaf = kids.length === 0;
        blocks.push({
          id: node.section_id,
          depth: depth,
          marker: lastMarker(node.canonical_citation),
          heading: node.heading || "",
          html: isLeaf ? verbatimHtml(node.text) : "",
        });
        for (const c of kids) walk(c, depth + 1);
      }
      for (const c of s.children || []) walk(c, 0);
      const topIsLeaf = !(s.children && s.children.length);
      return {
        id: s.section_id,
        num: deriveSecNum(s.canonical_citation),
        title: s.heading || "(untitled section)",
        blocks: blocks,
        // a section with no children carries its own verbatim text
        leafHtml: topIsLeaf ? verbatimHtml(s.text) : "",
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
        title: node.heading || "(untitled)",
        level: Math.min(level, 3),
        anchor: node.section_id,
        pages: "",
      });
      for (const c of node.children || []) walk(c, level + 1);
    }
    for (const s of (tree && tree.sections) || []) walk(s, 1);
    return { sections: out, stats: stats };
  }

  // ── defined_terms result → Definition-mode cards ────────────────────
  function mapDefinitions(res) {
    const terms = (res && res.terms) || [];
    return terms.map((t, i) => ({
      id: t.defined_term_id || "def-" + i,
      term: t.surface_form || "(term)",
      kind: t.definition_type === "by_reference" ? "byref" : "direct",
      anchor: t.defining_section_id,
      quoted: t.definition_text || "",
      refs_to: t.by_reference_target_citation || null,
      cite: t.defining_section_citation || "",
      verified: true, // definitions are mechanically extracted from the bill XML
    }));
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
  async function loadBillDetail(billId) {
    const [treeR, defsR, amsR] = await Promise.allSettled([
      apiGet("/api/bill/" + encodeURIComponent(billId) + "/sections"),
      apiGet("/api/bill/" + encodeURIComponent(billId) + "/defined_terms"),
      apiGet("/api/bill/" + encodeURIComponent(billId) + "/amendments"),
    ]);
    const tree = treeR.status === "fulfilled" ? treeR.value : { sections: [] };
    const defs = defsR.status === "fulfilled" ? mapDefinitions(defsR.value) : [];
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
