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

// ── answer text → the design's paragraph/run model ────────────────────
function textToParagraphs(text) {
  return String(text || "")
    .split(/\n+/)
    .map((p) => p.trim())
    .filter(Boolean)
    .map((p) => ({ kind: "p", runs: [{ t: p }] }));
}
function totalAnswerLength(paragraphs) {
  let n = 0;
  for (const p of paragraphs) for (const r of p.runs) n += (r.t || "").length;
  return n;
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
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState(null);
  const [asked, setAsked] = useState(false);           // has a query ever run?

  // sources + viewer
  const [bills, setBills] = useState([]);
  const [billIdx, setBillIdx] = useState(0);
  const [billDetail, setBillDetail] = useState({});    // keyed by bill id
  const [mode, setMode] = useState("structure");
  const [activeAnchor, setActiveAnchor] = useState(null);

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

  // ── streaming answer paragraphs ────────────────────────────────────
  const paragraphs = useMemo(() => {
    if (answerText) return textToParagraphs(answerText);
    if (streaming) return [{ kind: "p", runs: [{ t: "Searching the corpus…" }] }];
    return [];
  }, [answerText, streaming]);
  const charsRevealed = useMemo(() => totalAnswerLength(paragraphs), [paragraphs]);

  // ── submit a question → POST /chat (SSE) ───────────────────────────
  const onSubmit = () => {
    const q = prompt.trim();
    if (!q || streaming) return;
    setQuestion(q);
    setPrompt("");
    setAnswerText("");
    setError(null);
    setStreaming(true);
    setAsked(true);
    setBills([]);
    setBillIdx(0);
    setActiveAnchor(null);

    const collected = [];
    const priorHistory = history;
    let acc = "";

    B.streamChat(q, priorHistory, (ev) => {
      if (ev.type === "text") {
        acc += ev.delta || "";
        setAnswerText(acc);
      } else if (ev.type === "tool_result") {
        collected.push(ev);
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
        setActiveAnchor={setActiveAnchor}
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
        answerParagraphs={paragraphs}
        selectedId={selectedBill ? selectedBill.id : null}
        onSelect={(id) => {
          const i = bills.findIndex((b) => b.id === id);
          if (i >= 0) setBillIdx(i);
        }}
        streaming={streaming}
        charsRevealed={charsRevealed}
        activeCite={null}
        onCiteClick={() => {}}
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
