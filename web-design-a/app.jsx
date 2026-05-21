/* global React, ReactDOM, PolilabsBackend, Icon,
   LeftRail, BillViewer, BillViewerLoading, BillViewerEmpty,
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

// ── App ───────────────────────────────────────────────────────────────
function App() {
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
  const [railW, setRailW] = useState(440);
  const [textFrac, setTextFrac] = useState(0.5);
  const onRailResize = (e) => {
    e.preventDefault();
    const move = (ev) => setRailW(Math.max(300, Math.min(640, ev.clientX)));
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

    // Send an EMPTY history: the backend's _to_anthropic_history keeps
    // only user turns and drops every assistant turn, so passing prior
    // turns would hand Claude a run of unanswered user questions and it
    // would answer all of them. Each question is answered on its own.
    const segments = [""];
    let sawTool = false;

    B.streamChat(q, [], (ev) => {
      if (ev.type === "text") {
        if (sawTool) { segments.push(""); sawTool = false; }
        segments[segments.length - 1] += ev.delta || "";
        patchTurn(id, {
          answerText: segments[segments.length - 1],
          planText: segments.slice(0, -1).join("\n\n").trim(),
        });
      } else if (ev.type === "tool_call") {
        sawTool = true;
      } else if (ev.type === "tool_result") {
        collected.push(ev);
        sawTool = true;
      } else if (ev.type === "error") {
        patchTurn(id, { error: ev.message || "unknown backend error" });
      } else if (ev.type === "done") {
        setStreaming(false);
        patchTurn(id, { bills: B.billsFromToolResults(collected), billIdx: 0 });
      }
    }).catch((e) => {
      patchTurn(id, { error: String(e) });
      setStreaming(false);
    });
  };

  const onPreset = (text) => setPrompt(text);

  // ── load a bill's detail on selection (two stages) ─────────────────
  // Stage 1: /sections (~15ms) → the verbatim Text panel renders at once.
  // Stage 2: defined_terms + amendments (~10s graph queries) load in the
  // background and patch in; the Decomp tabs show a loading state until.
  useEffect(() => {
    if (!selectedId || billDetail[selectedId]) return;
    let cancelled = false;
    B.loadBillText(selectedId).then((base) => {
      if (cancelled) return;
      setBillDetail((prev) => ({ ...prev, [selectedId]: base }));
      return B.loadBillExtras(selectedId, base._tree);
    }).then((extras) => {
      if (cancelled || !extras) return;
      setBillDetail((prev) => {
        const cur = prev[selectedId];
        if (!cur) return prev;
        return {
          ...prev,
          [selectedId]: {
            ...cur,
            definitions: extras.definitions,
            amendments: extras.amendments,
            structure: {
              ...cur.structure,
              stats: {
                ...cur.structure.stats,
                definitions: extras.definitions.length,
                amendments: extras.amendments.length,
              },
            },
          },
        };
      });
    }).catch(() => {
      if (cancelled) return;
      setBillDetail((prev) => {
        const cur = prev[selectedId];
        // text loaded but extras failed → show empty, not perpetual spinner
        if (cur) return { ...prev, [selectedId]: { ...cur, definitions: [], amendments: [] } };
        return { ...prev, [selectedId]: { text: [], structure: { sections: [], stats: { sections: 0, definitions: 0, amendments: 0, citations: 0 } }, definitions: [], amendments: [], citations: [], _tree: { sections: [] } } };
      });
    });
    return () => { cancelled = true; };
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
    stage = <BillViewerEmpty presets={PRESETS} onPreset={onPreset} />;
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
        mode={mode} setMode={setMode}
        activeAnchor={activeAnchor}
        setActiveAnchor={flashAnchor}
        textFrac={textFrac}
        setTextFrac={setTextFrac}
      />
    );
  }

  const questionObj = {
    text: turn ? turn.question : "",
    sources_total: 191,
    sources_matched: bills.length,
  };

  return (
    <div className="app" style={{ "--rail-w": railW + "px" }}>
      <header className="app-header">
        <div className="brand">
          <div className="brand-name">polilabs</div>
        </div>
        <div className="header-tools">
          <div className="stat mono"><b>191</b> bills · 118th–119th Congress</div>
          {streaming && <div className="stat mono">agent working…</div>}
        </div>
      </header>

      <div className="rail-resizer" style={{ left: railW }} onPointerDown={onRailResize}
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
        selectedId={selectedId}
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

      <footer className="app-footer">
        <span><span className="dot" /> backend connected</span>
        <span><a href="Polilabs Design System.html" style={{ color: "var(--accent)", textDecoration: "none" }}>↗ design system</a></span>
      </footer>

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

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
