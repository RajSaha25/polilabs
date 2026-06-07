/* global React, ReactDOM, PolilabsBackend, PolilabsAuth, AuthScreen, Landing,
   Icon, LeftRail, BillViewer, BillViewerLoading, BillViewerEmpty,
   TweaksPanel, useTweaks, TweakSection, TweakRadio, TweakToggle, TweakColor */

// Polilabs — App. Wires the Claude-Design three-zone prototype to the
// real FastAPI backend (server.py) via window.PolilabsBackend.
//
//   prompt  → POST /chat (SSE)  → streaming answer + ranked bill list
//   select  → GET /api/bill/... → verbatim Text + Structure/Defs/Amends
//
// No invented text: every panel is filled from a backend response.

const { useState, useEffect, useRef, useMemo } = React;
const B = window.PolilabsBackend;

// ── markdown answer → block model ─────────────────────────────────────
// The agent streams Markdown. We parse it into a small block model
// (headings, paragraphs, lists, rule) with inline runs (bold/italic/code)
// so the left rail can render it as formatted text instead of raw "###".
function parseInline(text) {
  const runs = [];
  const re = /(\*\*\*([^*]+?)\*\*\*|\*\*([^*]+?)\*\*|\*([^*\n]+?)\*|`([^`]+?)`)/g;
  let last = 0;
  for (const m of String(text).matchAll(re)) {
    if (m.index > last) runs.push({ t: text.slice(last, m.index) });
    if (m[2] != null) runs.push({ t: m[2], b: true, i: true });
    else if (m[3] != null) runs.push({ t: m[3], b: true });
    else if (m[4] != null) runs.push({ t: m[4], i: true });
    else if (m[5] != null) runs.push({ t: m[5], code: true });
    last = m.index + m[0].length;
  }
  if (last < text.length) runs.push({ t: text.slice(last) });
  return runs.length ? runs : [{ t: text }];
}

function splitTableRow(line) {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}
function isTableSeparator(line) {
  return line.includes("|") && /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(line);
}

function parseMarkdown(text) {
  const lines = String(text || "").replace(/\r/g, "").split("\n");
  const blocks = [];
  let para = [];
  let list = null;
  const flushPara = () => {
    if (para.length) { blocks.push({ type: "p", runs: parseInline(para.join(" ")) }); para = []; }
  };
  const flushList = () => { if (list) { blocks.push(list); list = null; } };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    let m;
    if (!line) { flushPara(); flushList(); continue; }
    if (line.includes("|") && i + 1 < lines.length && isTableSeparator(lines[i + 1])) {
      flushPara(); flushList();
      const header = splitTableRow(line).map(parseInline);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].trim() && lines[i].includes("|")) {
        rows.push(splitTableRow(lines[i]).map(parseInline));
        i++;
      }
      i--;
      blocks.push({ type: "table", header, rows });
    } else if (/^(-{3,}|\*{3,}|_{3,})$/.test(line)) {
      flushPara(); flushList(); blocks.push({ type: "hr" });
    } else if ((m = line.match(/^(#{1,6})\s+(.*)$/))) {
      flushPara(); flushList();
      // Strip any number the agent prefixed ("1. ", "2) ") — AnswerStream
      // applies its own sequential numbering, so keeping it would double up.
      const htext = m[2].trim().replace(/^\d+[.):]\s+/, "");
      blocks.push({ type: "h", level: m[1].length, runs: parseInline(htext) });
    } else if ((m = line.match(/^[-*+]\s+(.*)$/))) {
      flushPara();
      if (!list || list.type !== "ul") { flushList(); list = { type: "ul", items: [] }; }
      list.items.push(parseInline(m[1].trim()));
    } else if ((m = line.match(/^\d+[.)]\s+(.*)$/))) {
      flushPara();
      if (!list || list.type !== "ol") { flushList(); list = { type: "ol", items: [] }; }
      list.items.push(parseInline(m[1].trim()));
    } else {
      flushList();
      para.push(line);
    }
  }
  flushPara(); flushList();
  return blocks;
}

// A short, instant title for a chat, derived from its first message. Used
// as the dock-tab label right away (and as a fallback if the server-side
// summarized title is unavailable). Clean whitespace, drop trailing
// punctuation, capitalize, truncate to a few words.
function deriveTitle(msg) {
  let s = String(msg || "").replace(/\s+/g, " ").trim();
  if (!s) return "New chat";
  s = s.replace(/[?.!,;:]+$/, "");
  s = s.charAt(0).toUpperCase() + s.slice(1);
  const words = s.split(" ");
  if (words.length > 6) return words.slice(0, 6).join(" ") + "…";
  return s.length > 46 ? s.slice(0, 44).replace(/\s+\S*$/, "") + "…" : s;
}

// ── accent / theme / density sync (from the original prototype) ───────
function hexToRgb(hex) {
  const h = hex.replace("#", "");
  const v = h.length === 3 ? h.split("").map((c) => c + c).join("") : h;
  return { r: parseInt(v.slice(0, 2), 16), g: parseInt(v.slice(2, 4), 16), b: parseInt(v.slice(4, 6), 16) };
}
function rgbToHex({ r, g, b }) {
  return "#" + [r, g, b].map((n) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, "0")).join("");
}
function shade(hex, percent) {
  const { r, g, b } = hexToRgb(hex);
  const f = percent / 100;
  return rgbToHex({ r: r + (f < 0 ? r * f : (255 - r) * f), g: g + (f < 0 ? g * f : (255 - g) * f), b: b + (f < 0 ? b * f : (255 - b) * f) });
}
function tint(hex, amount) {
  const { r, g, b } = hexToRgb(hex);
  return rgbToHex({ r: r + (255 - r) * amount, g: g + (255 - g) * amount, b: b + (255 - b) * amount });
}
function useTweakSync(tweaks) {
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", tweaks.theme || "light");
    document.documentElement.setAttribute("data-density", tweaks.density || "default");
    if (tweaks.accent) {
      const root = document.documentElement.style;
      root.setProperty("--accent", tweaks.accent);
      root.setProperty("--accent-2", shade(tweaks.accent, -10));
      root.setProperty("--accent-soft", tint(tweaks.accent, 0.92));
      root.setProperty("--accent-line", tint(tweaks.accent, 0.7));
      root.setProperty("--accent-ink", shade(tweaks.accent, -32));
    }
  }, [tweaks.theme, tweaks.density, tweaks.accent]);
}

const TWEAK_DEFAULTS = {
  accent: "#1e3fa8", theme: "light", density: "default",
  showRelevance: true, showMatches: true,
};

const PRESETS = [
  "How does each bill define ‘foundation model’?",
  "Which bills amend the Federal Trade Commission Act?",
  "What’s NOT in this corpus?",
];

// Turn a raw tool call into a plain-English chain-of-thought step so a
// policymaker can see (and audit) exactly what the agent did.
function toolStepLabel(name, args) {
  const a = args || {};
  switch (name) {
    case "search_corpus": return `Searched the corpus for “${a.query}”`;
    case "get_bill": return `Opened bill ${a.bill_id}`;
    case "get_section": return `Read section ${a.section_id}`;
    case "get_citation_graph": return `Traced citations around ${a.section_id}`;
    case "get_defined_terms": return `Pulled defined terms in ${a.bill_id}`;
    case "get_amendments": return `Pulled amendments in ${a.bill_id}`;
    case "get_amendments_targeting": return `Found amendments targeting ${a.target || a.citation_string || "a statute"}`;
    case "resolve_citation": return `Resolved the citation “${a.citation_string}”`;
    case "find_definitions_of": return `Searched definitions of “${a.term}”`;
    case "find_bills_defining": return `Found bills defining “${a.term}”`;
    case "find_bills_amending": return `Found bills amending ${a.citation_string || "a statute"}`;
    case "corpus_coverage": return "Checked what the corpus does and doesn't cover";
    default: return name;
  }
}

// ── Past-chats sidebar ────────────────────────────────────────────────
// A file-explorer-style list of this session's chats (each turn is a
// "chat"). Click one to reopen its answer + bills. Newest on top.
function ChatsSidebar({ turns, activeId, onSelect, onNew, onClose }) {
  return (
    <aside className="chats-sidebar">
      <div className="chats-head">
        <span className="chats-title">Chats</span>
        <div className="chats-head-actions">
          <button type="button" className="chats-new" onClick={onNew} title="New chat">
            <Icon name="search" size={13} />
          </button>
          <button type="button" className="chats-collapse" onClick={onClose} title="Hide chats">
            <Icon name="chevron-left" size={14} />
          </button>
        </div>
      </div>
      <div className="chats-list scroll">
        {(turns || []).length === 0 ? (
          <p className="chats-empty">Your questions show up here. Ask something to start a chat.</p>
        ) : (
          turns.slice().reverse().map((t) => (
            <button
              key={t.id}
              type="button"
              className={"chat-item" + (t.id === activeId ? " active" : "")}
              onClick={() => onSelect(t.id)}
              title={t.question}
            >
              <Icon name="doc" size={13} className="chat-item-icon" />
              <span className="chat-item-q">{t.question || "(untitled)"}</span>
            </button>
          ))
        )}
      </div>
    </aside>
  );
}

// ── App ───────────────────────────────────────────────────────────────
// The workspace shell. Routing between the workspace and the public
// landing page is handled by Root() — App always renders the workspace
// and exposes onShowLanding for the wordmark.
function App({ onSignOut, onShowLanding }) {
  const [tweaks, setTweak] = useTweaks(TWEAK_DEFAULTS);
  useTweakSync(tweaks);

  // Conversation — an archive of turns. A new prompt appends one; the
  // recent-queries list brings an earlier turn's answer + bills back.
  // Each turn: { id, question, answerText, planText, bills, billIdx, error }.
  const [turns, setTurns] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [streaming, setStreaming] = useState(false);

  // Viewer state + caches — shared across turns.
  const [billDetail, setBillDetail] = useState({});    // keyed by bill id
  const [mode, setMode] = useState("structure");
  const [activeAnchor, setActiveAnchor] = useState(null);
  const [prompt, setPrompt] = useState("");

  // Per-user in-bill annotations, keyed by bill id. Loaded from the
  // gated /api/annotations surface when a bill is opened; mutated
  // through the handlers below (optimistic on the result row).
  const [annotations, setAnnotations] = useState({});

  // Grounded bill summaries, keyed by bill id: { loading, text, error }.
  // The top result of a turn auto-summarizes; other bills summarize lazily
  // the first time they're selected. Cached here (and server-side) so
  // re-selecting a bill is instant + free.
  const [summaries, setSummaries] = useState({});

  // "Connect your agent" modal (bring-your-own-agent connector tokens).
  const [showConnector, setShowConnector] = useState(false);

  // "All notes" modal — every annotation across all bills, from
  // PolilabsAnnotations.listAll(). `pendingNav` queues a jump from that
  // list: open the bill, then scroll to the note once its text loads.
  const [showAllNotes, setShowAllNotes] = useState(false);
  const [allNotes, setAllNotes] = useState({ loading: false, items: [], error: null });
  const [pendingNav, setPendingNav] = useState(null);

  // Past-chats sidebar (IDE file-explorer style). Each turn is a "chat".
  const [chatsOpen, setChatsOpen] = useState(true);
  const CHATS_W = 220;

  // Inline bill chats (double-click the text). Keyed by bill id, each
  // bill holds an array of independent agent threads so several agents
  // can be worked at once:
  //   { [billId]: { threads: [{ id, messages:[{role,content,flags}], loading }] } }
  // Threads persist when their window is closed (minimized to the dock),
  // so reopening restores the conversation. The sections an agent reads
  // become flags highlighted in the bill text.
  const [billChat, setBillChat] = useState({});

  const turn = turns.find((t) => t.id === activeId) || null;
  const patchTurn = (id, partial) =>
    setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, ...partial } : t)));

  // Sync-highlight is a transient pulse, not a sticky selection: a click
  // scrolls + flashes the matching span/card, then clears so nothing
  // stays highlighted afterwards.
  const anchorTimer = useRef(null);
  const flashAnchor = (anchor) => {
    if (anchorTimer.current) clearTimeout(anchorTimer.current);
    setActiveAnchor(anchor);
    if (anchor) anchorTimer.current = setTimeout(() => setActiveAnchor(null), 1500);
  };

  // resizable layout — rail width (px) + Text/Decomp split fraction
  const [railW, setRailW] = useState(460);
  const [textFrac, setTextFrac] = useState(0.58);
  const onRailResize = (e) => {
    e.preventDefault();
    const move = (ev) => setRailW(Math.max(320, Math.min(640, ev.clientX - (chatsOpen ? CHATS_W : 0))));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const bills = turn ? turn.bills : [];
  const billIdx = turn ? turn.billIdx : 0;
  const selectedBill = bills[billIdx] || null;
  const selectedId = selectedBill ? selectedBill.id : null;
  const detail = selectedBill ? billDetail[selectedBill.id] : null;

  // Select a bill within the active turn.
  const setBillIdx = (next) => {
    if (!turn) return;
    const wanted = typeof next === "function" ? next(turn.billIdx) : next;
    patchTurn(turn.id, {
      billIdx: Math.max(0, Math.min(turn.bills.length - 1, wanted)),
    });
  };

  // ── all-notes view: fetch every annotation, jump to one ────────────
  const openAllNotes = () => {
    setShowAllNotes(true);
    setAllNotes({ loading: true, items: [], error: null });
    window.PolilabsAnnotations.listAll()
      .then((items) => setAllNotes({ loading: false, items: items || [], error: null }))
      .catch((e) => setAllNotes({ loading: false, items: [], error: String((e && e.message) || e) }));
  };

  // Open the bill a note lives on — reuse it if it's already in the active
  // turn, else spin up a lightweight turn for it — then queue a scroll to
  // the note's section once the verbatim text has loaded.
  const openNote = (note) => {
    setShowAllNotes(false);
    const billId = note.bill_id;
    const idxInTurn = turn ? turn.bills.findIndex((b) => b.id === billId) : -1;
    if (idxInTurn >= 0) {
      setBillIdx(idxInTurn);
    } else {
      const pretty = B && B.prettyBillId ? B.prettyBillId(billId) : billId;
      const id = "t-note-" + Date.now() + "-" + Math.random().toString(36).slice(2, 7);
      setTurns((ts) => [...ts, {
        id, question: pretty, answerText: "", planText: "",
        bills: [{ id: billId, bill_id: pretty, short: pretty }], billIdx: 0, error: null,
      }]);
      setActiveId(id);
    }
    setPendingNav({ billId, sectionId: note.section_id || null });
  };

  // When a queued note-jump's bill has loaded its text, scroll to the
  // note's section (a null section is a bill-level note → just open it).
  useEffect(() => {
    if (!pendingNav || selectedId !== pendingNav.billId) return;
    const d = billDetail[selectedId];
    if (!d || !(d.text && d.text.length)) return;   // wait for verbatim text
    flashAnchor(pendingNav.sectionId);
    setPendingNav(null);
  }, [pendingNav, selectedId, billDetail]);

  // ── streaming answer blocks ────────────────────────────────────────
  const answerText = turn ? turn.answerText : "";
  const answerBlocks = useMemo(() => {
    if (answerText) return parseMarkdown(answerText);
    if (streaming) return [{ type: "p", runs: [{ t: "Searching the corpus…" }] }];
    return [];
  }, [answerText, streaming]);

  // ── submit a question → POST /chat (SSE) ───────────────────────────
  const onSubmit = () => {
    const q = prompt.trim();
    if (!q || streaming) return;
    setPrompt("");
    setActiveAnchor(null);

    // A fresh turn — it becomes the active one; earlier turns stay in
    // the archive and are reachable from the recent-queries list.
    const id = "t-" + Date.now() + "-" + Math.random().toString(36).slice(2, 7);
    setTurns((ts) => [...ts, {
      id, question: q, answerText: "", planText: "",
      bills: [], billIdx: 0, error: null,
    }]);
    setActiveId(id);
    setStreaming(true);

    const collected = [];
    // Sections the agent actually pulled this turn (get_section /
    // get_citation_graph). These become transient "agent flags" — the
    // agent pointing the researcher at verbatim spans it relied on. Not
    // persisted; they live on the turn and clear when the turn changes.
    const flagged = new Set();

    // Carry the conversation so far — every prior question with its
    // answer — so a follow-up ("how does that bill relate to…") keeps
    // context. Assistant turns are plain answer text (no tool_use
    // blocks), so they replay to the API cleanly.
    const history = [];
    for (const t of turns) {
      if (t.question && t.answerText) {
        history.push({ role: "user", content: t.question });
        history.push({ role: "assistant", content: t.answerText });
      }
    }

    const segments = [""];
    let sawTool = false;
    // Chain of thought: the agent's tool steps, labelled in plain English,
    // streamed live so a policymaker can watch (and audit) how it worked.
    const steps = [];

    B.streamChat(q, history, (ev) => {
      if (ev.type === "text") {
        if (sawTool) { segments.push(""); sawTool = false; }
        segments[segments.length - 1] += ev.delta || "";
        patchTurn(id, {
          answerText: segments[segments.length - 1],
          planText: segments.slice(0, -1).join("\n\n").trim(),
        });
      } else if (ev.type === "tool_call") {
        // A section_id argument means the agent read (or walked the
        // citations of) that exact span — flag it for the researcher.
        const sid = ev.args && ev.args.section_id;
        if (sid) flagged.add(sid);
        steps.push({ name: ev.name, label: toolStepLabel(ev.name, ev.args || {}) });
        patchTurn(id, { toolSteps: [...steps] });
        sawTool = true;
      } else if (ev.type === "tool_result") {
        collected.push(ev);
        const sid = ev.args && ev.args.section_id;
        if (sid) flagged.add(sid);
        sawTool = true;
      } else if (ev.type === "error") {
        patchTurn(id, { error: ev.message || "unknown backend error" });
      } else if (ev.type === "done") {
        setStreaming(false);
        patchTurn(id, { bills: B.billsFromToolResults(collected), billIdx: 0, agentFlags: [...flagged] });
      }
    }).catch((e) => {
      patchTurn(id, { error: String(e) });
      setStreaming(false);
    });
  };

  const onPreset = (text) => setPrompt(text);

  // ── load a bill's full detail on selection ─────────────────────────
  // A failed load is never cached — a transient backend error must not
  // leave the bill blank for the whole session. Retry a few times, then
  // fall back to an empty detail so the viewer stops spinning.
  useEffect(() => {
    if (!selectedId || billDetail[selectedId]) return;
    let cancelled = false;
    let tries = 0;
    let timer = null;
    const attempt = () => {
      B.loadBillDetail(selectedId).then((d) => {
        if (!cancelled) setBillDetail((prev) => ({ ...prev, [selectedId]: d }));
      }).catch(() => {
        if (cancelled) return;
        tries += 1;
        if (tries < 3) { timer = setTimeout(attempt, 600 * tries); return; }
        setBillDetail((prev) => ({ ...prev, [selectedId]: { text: [], structure: { sections: [], stats: { sections: 0, definitions: 0, amendments: 0, citations: 0 } }, definitions: [], amendments: [], citations: [], _tree: { sections: [] } } }));
      });
    };
    attempt();
    return () => { cancelled = true; if (timer) clearTimeout(timer); };
  }, [selectedId]);

  // ── lazy-load Citation mode (per-section graphs) ───────────────────
  useEffect(() => {
    if (mode !== "citation" || !selectedId || !detail || detail.citations !== null) return;
    let cancelled = false;
    B.fetchCitationGroups(detail._tree).then((groups) => {
      if (cancelled) return;
      setBillDetail((prev) => ({
        ...prev,
        [selectedId]: { ...prev[selectedId], citations: groups },
      }));
    }).catch(() => {
      if (!cancelled) setBillDetail((prev) => ({
        ...prev,
        [selectedId]: { ...prev[selectedId], citations: [] },
      }));
    });
    return () => { cancelled = true; };
  }, [mode, selectedId, detail]);

  // reset highlight when the selected bill changes
  useEffect(() => { setActiveAnchor(null); }, [selectedId]);

  // ── load this user's annotations for the open bill ─────────────────
  useEffect(() => {
    if (!selectedId || annotations[selectedId]) return;
    let cancelled = false;
    window.PolilabsAnnotations.list(selectedId)
      .then((rows) => { if (!cancelled) setAnnotations((p) => ({ ...p, [selectedId]: rows })); })
      .catch(() => { if (!cancelled) setAnnotations((p) => ({ ...p, [selectedId]: [] })); });
    return () => { cancelled = true; };
  }, [selectedId]);

  const billAnnotations = selectedId ? (annotations[selectedId] || []) : [];

  // Create / edit / delete an annotation on the open bill. Each resolves
  // the server row into local state so ids and timestamps stay truthful.
  const addAnnotation = (a) => {
    if (!selectedId) return Promise.resolve();
    return window.PolilabsAnnotations.create({ ...a, bill_id: selectedId })
      .then((row) => setAnnotations((p) => ({
        ...p, [selectedId]: [...(p[selectedId] || []), row],
      })));
  };
  const editAnnotation = (id, patch) =>
    window.PolilabsAnnotations.update(id, patch).then((row) =>
      setAnnotations((p) => ({
        ...p, [selectedId]: (p[selectedId] || []).map((x) => (x.id === id ? row : x)),
      })));
  const removeAnnotation = (id) =>
    window.PolilabsAnnotations.remove(id).then(() =>
      setAnnotations((p) => ({
        ...p, [selectedId]: (p[selectedId] || []).filter((x) => x.id !== id),
      })));

  // ── grounded bill summary for the selected bill (cached) ────────────
  // The top result is auto-selected, so it auto-summarizes; selecting any
  // other source triggers its summary on first view ("top result auto,
  // rest on click"). A prior error is retried when the bill is revisited.
  useEffect(() => {
    if (!selectedId) return;
    const cur = summaries[selectedId];
    if (cur && (cur.loading || cur.text)) return;   // cached / in-flight
    let cancelled = false;
    setSummaries((p) => ({ ...p, [selectedId]: { loading: true, text: "", error: null } }));
    B.summarizeBill(selectedId)
      .then((r) => { if (!cancelled) setSummaries((p) => ({
        ...p, [selectedId]: { loading: false, text: (r && r.summary) || "", error: (r && r.error) || null } })); })
      .catch((e) => { if (!cancelled) setSummaries((p) => ({
        ...p, [selectedId]: { loading: false, text: "", error: String(e) } })); });
    return () => { cancelled = true; };
  }, [selectedId]);

  // ── Inline bill chats (double-click the text) ──────────────────────
  // Each bill holds N independent agent threads, run OUTSIDE the main
  // thread (they never touch `turns` or the bills list). Every assistant
  // turn records the section ids that agent read; those become highlight
  // flags. Threads persist per bill, so a minimized chat reopens intact.

  // Patch the most recent assistant message of ONE thread.
  const patchThread = (chat, billId, threadId, partial, loading) => {
    const cur = chat[billId];
    if (!cur) return chat;
    const threads = cur.threads.map((t) => {
      if (t.id !== threadId) return t;
      const msgs = t.messages.slice();
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === "assistant") { msgs[i] = { ...msgs[i], ...partial }; break; }
      }
      return { ...t, messages: msgs, loading: loading === undefined ? t.loading : loading };
    });
    return { ...chat, [billId]: { ...cur, threads } };
  };

  // Create an empty thread on the open bill; returns its id so the caller
  // can open a window for it.
  const newThread = () => {
    if (!selectedId) return null;
    const billId = selectedId;
    const tid = "c-" + Date.now() + "-" + Math.random().toString(36).slice(2, 6);
    setBillChat((p) => {
      const cur = p[billId] || { threads: [] };
      return { ...p, [billId]: { ...cur, threads: [...cur.threads, { id: tid, messages: [], loading: false, title: null }] } };
    });
    return tid;
  };

  // Set/replace a thread's display title (used for the dock tab).
  const setThreadTitle = (billId, threadId, title) => setBillChat((p) => {
    const cur = p[billId];
    if (!cur) return p;
    return { ...p, [billId]: { ...cur, threads: cur.threads.map((t) => (t.id === threadId ? { ...t, title } : t)) } };
  });

  const removeThread = (threadId) => {
    if (!selectedId) return;
    const billId = selectedId;
    setBillChat((p) => {
      const cur = p[billId];
      if (!cur) return p;
      return { ...p, [billId]: { ...cur, threads: cur.threads.filter((t) => t.id !== threadId) } };
    });
  };

  // Ask a question inside ONE thread of the open bill.
  const askInBill = (threadId, question) => {
    const q = (question || "").trim();
    if (!selectedId || !q || !threadId) return;
    const billId = selectedId;
    const billTitle = selectedBill ? (selectedBill.short || selectedBill.bill_id || billId) : billId;
    const thread = ((billChat[billId] && billChat[billId].threads) || []).find((t) => t.id === threadId);
    const prior = ((thread && thread.messages) || [])
      .filter((m) => m.content).map((m) => ({ role: m.role, content: m.content }));
    const isFirst = prior.length === 0;
    // First turn carries the bill scope; later turns rely on replayed history.
    const scoped = isFirst ?
      `[Answer questions about ONE bill: ${billId} ("${billTitle}"). Stay inside this bill. ` +
      `Ground answers in its section text via get_section or get_citation_graph. Do not dump a huge ` +
      `get_bill table of contents. Cite the sections you use. Be concise.]\n\n${q}` : q;
    setBillChat((p) => {
      const cur = p[billId] || { threads: [] };
      const threads = cur.threads.map((t) => t.id === threadId
        ? { ...t,
            title: t.title || (isFirst ? deriveTitle(q) : t.title),
            messages: [...t.messages, { role: "user", content: q }, { role: "assistant", content: "", flags: [] }],
            loading: true }
        : t);
      return { ...p, [billId]: { ...cur, threads } };
    });
    // Upgrade the instant title to a short LLM-summarized one (best effort;
    // silently keeps the instant title if the backend lacks the route).
    if (isFirst) {
      B.titleForChat(q)
        .then((r) => { const tt = r && (r.title || "").trim(); if (tt) setThreadTitle(billId, threadId, tt); })
        .catch(() => {});
    }
    const flags = new Set();
    let answer = "";
    B.streamChat(scoped, prior, (ev) => {
      if (ev.type === "text") {
        answer += ev.delta || "";
        setBillChat((p) => patchThread(p, billId, threadId, { content: answer }));
      } else if (ev.type === "tool_call" || ev.type === "tool_result") {
        const sid = ev.args && ev.args.section_id;
        if (sid) { flags.add(sid); setBillChat((p) => patchThread(p, billId, threadId, { flags: [...flags] })); }
      } else if (ev.type === "error") {
        setBillChat((p) => patchThread(p, billId, threadId, { content: answer || ("⚠️ " + (ev.message || "error")), flags: [...flags] }, false));
      } else if (ev.type === "done") {
        setBillChat((p) => patchThread(p, billId, threadId, { content: answer, flags: [...flags] }, false));
      }
    }).catch((e) => setBillChat((p) => patchThread(p, billId, threadId, { content: answer || ("⚠️ " + String(e)), flags: [...flags] }, false)));
  };

  const chatThreads = selectedId ? ((billChat[selectedId] && billChat[selectedId].threads) || []) : [];

  // Agent flags shown on the open bill = those the main answer touched +
  // every section any inline agent has read. De-duplicated.
  const turnFlags = turn ? (turn.agentFlags || []) : [];
  const combinedAgentFlags = React.useMemo(() => {
    const chatFlags = chatThreads.flatMap((t) => t.messages.flatMap((m) => m.flags || []));
    return [...new Set([...turnFlags, ...chatFlags])];
  }, [turnFlags, billChat, selectedId]);

  // ── the merged bill object the viewer renders ──────────────────────
  const viewerBill = selectedBill && detail
    ? { ...selectedBill, ...detail, citations: detail.citations || [] }
    : null;

  const asked = turns.length > 0;

  // ── viewer stage ───────────────────────────────────────────────────
  let stage;
  if (!asked) {
    stage = <BillViewerEmpty presets={PRESETS} onPreset={onPreset} />;
  } else if (streaming && bills.length === 0) {
    stage = <BillViewerLoading />;
  } else if (bills.length === 0) {
    // Asked, but the agent answered without surfacing a bill (scope
    // question, false-premise probe, aggregate answer). `answered`
    // mode hides the preset buttons and rewrites the copy so the
    // empty viewer stops looking like a first-visit pitch.
    stage = <BillViewerEmpty answered={true} />;
  } else if (!viewerBill) {
    stage = <BillViewerLoading />;
  } else {
    stage = (
      <BillViewer
        bill={viewerBill}
        position={billIdx}
        total={bills.length}
        onPrev={() => setBillIdx((i) => Math.max(0, i - 1))}
        onNext={() => setBillIdx((i) => Math.min(bills.length - 1, i + 1))}
        activeAnchor={activeAnchor}
        setActiveAnchor={flashAnchor}
        annotations={billAnnotations}
        onAddAnnotation={addAnnotation}
        onEditAnnotation={editAnnotation}
        onRemoveAnnotation={removeAnnotation}
        agentFlags={combinedAgentFlags}
        chatThreads={chatThreads}
        onAsk={askInBill}
        onNewThread={newThread}
        onRemoveThread={removeThread}
      />
    );
  }

  const questionObj = {
    text: turn ? turn.question : "",
    sources_total: 191,
    sources_matched: bills.length,
  };

  return (
    <div className={"app" + (chatsOpen ? " has-chats" : "")}
         style={{ "--rail-w": railW + "px", "--chats-w": CHATS_W + "px" }}>
      <header className="app-header">
        <div className="brand">
          <button type="button" className="chats-toggle" title={chatsOpen ? "Hide chats" : "Show past chats"}
                  onClick={() => setChatsOpen((o) => !o)}>
            <Icon name="list-tree" size={16} />
          </button>
          <button type="button" className="brand-name" title="back to home"
                  onClick={onShowLanding}>polilabs</button>
        </div>
        <div className="header-tools">
          {streaming && <div className="stat mono">agent working…</div>}
          <button type="button" className="connect-agent-btn" onClick={openAllNotes}
                  title="See every note you've made, across all bills">
            <Icon name="quote" size={13} /> Notes
          </button>
          <button type="button" className="connect-agent-btn" onClick={() => setShowConnector(true)}
                  title="Use your own approved AI agent on the corpus">
            <Icon name="link" size={13} /> Connect agent
          </button>
          <div className="signout">
            <span className="signout-user">
              {(PolilabsAuth.getUser() || {}).email}
            </span>
            <button className="signout-btn" type="button" onClick={onSignOut}>
              Sign out
            </button>
          </div>
        </div>
      </header>

      {chatsOpen ? (
        <ChatsSidebar
          turns={turns}
          activeId={activeId}
          onSelect={setActiveId}
          onNew={() => setActiveId(null)}
          onClose={() => setChatsOpen(false)}
        />
      ) : null}

      <div className="rail-resizer" style={{ left: (chatsOpen ? CHATS_W : 0) + railW }} onPointerDown={onRailResize}
           title="Drag to resize the rail" />

      <LeftRail
        bills={bills}
        turns={turns}
        activeTurnId={activeId}
        onSelectTurn={setActiveId}
        question={questionObj}
        sourcesMatched={bills.length}
        answerBlocks={answerBlocks}
        planText={turn ? turn.planText : ""}
        toolSteps={turn ? (turn.toolSteps || []) : []}
        selectedId={selectedId}
        summary={selectedId ? summaries[selectedId] : null}
        onSelect={(id) => {
          const i = bills.findIndex((b) => b.id === id);
          if (i >= 0) setBillIdx(i);
        }}
        streaming={streaming}
        promptValue={prompt}
        setPromptValue={setPrompt}
        onSubmit={onSubmit}
        onPreset={onPreset}
        presets={PRESETS.slice(0, 2)}
        showRelevance={tweaks.showRelevance}
        showMatches={tweaks.showMatches}
        error={turn ? turn.error : null}
      />

      {stage}



      {showConnector ? <ConnectorPanel onClose={() => setShowConnector(false)} /> : null}

      {showAllNotes ? (
        <AllNotesPanel data={allNotes} onClose={() => setShowAllNotes(false)} onSelect={openNote} />
      ) : null}

      <TweaksPanel title="Tweaks">
        <TweakSection label="Theme">
          <TweakRadio label="Mode" value={tweaks.theme} options={[
            { value: "light", label: "Light" },
            { value: "dark", label: "Dark" },
          ]} onChange={(v) => setTweak("theme", v)} />
          <TweakRadio label="Density" value={tweaks.density} options={[
            { value: "compact", label: "Compact" },
            { value: "default", label: "Default" },
            { value: "comfortable", label: "Comfy" },
          ]} onChange={(v) => setTweak("density", v)} />
          <TweakColor label="Accent" value={tweaks.accent}
            options={["#1e3fa8", "#0b3b2e", "#7c2d12", "#111827"]}
            onChange={(v) => setTweak("accent", v)} />
        </TweakSection>

        <TweakSection label="Sources list">
          <TweakToggle label="Show relevance scores" value={tweaks.showRelevance} onChange={(v) => setTweak("showRelevance", v)} />
          <TweakToggle label="Show matched keywords" value={tweaks.showMatches} onChange={(v) => setTweak("showMatches", v)} />
        </TweakSection>
      </TweaksPanel>
    </div>
  );
}

// ── Root — public landing + auth gate ─────────────────────────────────
// Three views: 'landing' (public; the marketing page), 'auth' (sign in
// or create account), 'workspace' (the gated research tool).
//
// First visit lands on the public page. "Open the workspace" routes to
// the auth screen for unauthenticated visitors and directly to the app
// for signed-in users. Signing out returns to the landing page, not the
// auth screen — so a returning visitor can read about the product
// without being challenged for credentials first.
function Root() {
  const [user, setUser] = useState(() =>
    PolilabsAuth.isAuthenticated() ? PolilabsAuth.getUser() : null,
  );
  const [view, setView] = useState(() =>
    // A signed-in returning user still gets to see the landing first —
    // this is the screen Andrew wants to see when he opens the app.
    "landing",
  );

  if (view === "auth") {
    return (
      <AuthScreen
        onAuthed={(u) => { setUser(u); setView("workspace"); }}
        onBack={() => setView("landing")}
      />
    );
  }
  if (view === "workspace" && user) {
    return (
      <App
        onSignOut={() => {
          PolilabsAuth.logout();
          setUser(null);
          setView("landing");
        }}
        onShowLanding={() => setView("landing")}
      />
    );
  }
  // landing (default; also the fallback when 'workspace' is requested
  // without a signed-in user).
  return (
    <Landing
      user={user}
      onOpenWorkspace={() => setView(user ? "workspace" : "auth")}
      onSignIn={() => setView("auth")}
      onSignOut={() => {
        PolilabsAuth.logout();
        setUser(null);
      }}
    />
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<Root />);
