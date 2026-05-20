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
  let last = 0, m;
  while ((m = re.exec(text))) {
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
      blocks.push({ type: "h", level: m[1].length, runs: parseInline(m[2].trim()) });
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

  // conversation
  const [history, setHistory] = useState([]);          // [{role:'user', content}]
  const [question, setQuestion] = useState("");        // last submitted prompt
  const [answerText, setAnswerText] = useState("");
  const [planText, setPlanText] = useState("");   // agent narration before the answer
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState(null);
  const [asked, setAsked] = useState(false);           // has a query ever run?

  // sources + viewer
  const [bills, setBills] = useState([]);
  const [billIdx, setBillIdx] = useState(0);
  const [billDetail, setBillDetail] = useState({});    // keyed by bill id
  const [mode, setMode] = useState("structure");
  const [activeAnchor, setActiveAnchor] = useState(null);

  // Sync-highlight is a transient pulse, not a sticky selection: a click
  // scrolls + flashes the matching span/card, then clears so nothing
  // stays highlighted afterwards.
  const anchorTimer = useRef(null);
  const flashAnchor = (anchor) => {
    if (anchorTimer.current) clearTimeout(anchorTimer.current);
    setActiveAnchor(anchor);
    if (anchor) anchorTimer.current = setTimeout(() => setActiveAnchor(null), 1500);
  };

  // prompt input
  const [prompt, setPrompt] = useState("");

  // resizable layout — rail width (px) + Text/Decomp split fraction
  const [railW, setRailW] = useState(360);
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

  const selectedBill = bills[billIdx] || null;
  const detail = selectedBill ? billDetail[selectedBill.id] : null;

  // ── streaming answer blocks ────────────────────────────────────────
  const answerBlocks = useMemo(() => {
    if (answerText) return parseMarkdown(answerText);
    if (streaming) return [{ type: "p", runs: [{ t: "Searching the corpus…" }] }];
    return [];
  }, [answerText, streaming]);

  // ── submit a question → POST /chat (SSE) ───────────────────────────
  const onSubmit = () => {
    const q = prompt.trim();
    if (!q || streaming) return;
    setQuestion(q);
    setPrompt("");
    setAnswerText("");
    setPlanText("");
    setError(null);
    setStreaming(true);
    setAsked(true);
    setBills([]);
    setBillIdx(0);
    setActiveAnchor(null);

    const collected = [];
    const priorHistory = history;

    // The agent narrates its plan, calls tools, then writes the answer.
    // Split the streamed text on tool boundaries: the final text segment
    // is the answer; everything before it is planning/reasoning.
    const segments = [""];
    let sawTool = false;

    B.streamChat(q, priorHistory, (ev) => {
      if (ev.type === "text") {
        if (sawTool) { segments.push(""); sawTool = false; }
        segments[segments.length - 1] += ev.delta || "";
        setAnswerText(segments[segments.length - 1]);
        setPlanText(segments.slice(0, -1).join("\n\n").trim());
      } else if (ev.type === "tool_call") {
        sawTool = true;
      } else if (ev.type === "tool_result") {
        collected.push(ev);
        sawTool = true;
      } else if (ev.type === "error") {
        setError(ev.message || "unknown backend error");
      } else if (ev.type === "done") {
        setStreaming(false);
        const ranked = B.billsFromToolResults(collected);
        setBills(ranked);
        setBillIdx(0);
        setHistory([...priorHistory, { role: "user", content: q }]);
      }
    }).catch((e) => {
      setError(String(e));
      setStreaming(false);
    });
  };

  const onPreset = (text) => setPrompt(text);

  // ── load a bill's full detail on selection ─────────────────────────
  useEffect(() => {
    const bill = bills[billIdx];
    if (!bill || billDetail[bill.id]) return;
    let cancelled = false;
    B.loadBillDetail(bill.id).then((d) => {
      if (!cancelled) setBillDetail((prev) => ({ ...prev, [bill.id]: d }));
    }).catch(() => {
      if (!cancelled) setBillDetail((prev) => ({ ...prev, [bill.id]: { text: [], structure: { sections: [], stats: { sections: 0, definitions: 0, amendments: 0, citations: 0 } }, definitions: [], amendments: [], citations: [], _tree: { sections: [] } } }));
    });
    return () => { cancelled = true; };
  }, [bills, billIdx]);

  // ── lazy-load Citation mode (per-section graphs) ───────────────────
  useEffect(() => {
    if (mode !== "citation" || !selectedBill || !detail || detail.citations !== null) return;
    let cancelled = false;
    B.fetchCitationGroups(detail._tree).then((groups) => {
      if (cancelled) return;
      setBillDetail((prev) => ({
        ...prev,
        [selectedBill.id]: { ...prev[selectedBill.id], citations: groups },
      }));
    }).catch(() => {
      if (!cancelled) setBillDetail((prev) => ({
        ...prev,
        [selectedBill.id]: { ...prev[selectedBill.id], citations: [] },
      }));
    });
    return () => { cancelled = true; };
  }, [mode, billIdx, detail]);

  // reset highlight when switching bills
  useEffect(() => { setActiveAnchor(null); }, [billIdx]);

  // ── the merged bill object the viewer renders ──────────────────────
  const viewerBill = selectedBill && detail
    ? { ...selectedBill, ...detail, citations: detail.citations || [] }
    : null;

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
    text: question,
    sources_total: 191,
    sources_matched: bills.length,
  };

  return (
    <div className="app" style={{ "--rail-w": railW + "px" }}>
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark">P</div>
          <div className="brand-name">polilabs</div>
        </div>
        <div className="header-tools">
          <div className="stat mono"><b>191</b> bills · 118th–119th Congress</div>
          <div className="stat mono">{streaming ? "agent working…" : "ready"}</div>
        </div>
      </header>

      <div className="rail-resizer" style={{ left: railW }} onPointerDown={onRailResize}
           title="Drag to resize the rail" />

      <LeftRail
        bills={bills}
        question={questionObj}
        sourcesMatched={bills.length}
        answerBlocks={answerBlocks}
        planText={planText}
        selectedId={selectedBill ? selectedBill.id : null}
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
        error={error}
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
