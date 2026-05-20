/* global React, Icon */
// Polilabs — Left Rail
// Top: ranked bill list. Middle: agent answer. Bottom: prompt input.

const { useState, useRef, useEffect } = React;

// ── Relevance bar (8 segments) ─────────────────────────────────────────
function Relevance({ value }) {
  const filled = Math.round(value * 8);
  return (
    <span className="relevance" title={`relevance ${(value * 100).toFixed(0)}%`}>
      <span className="bar">
        {Array.from({ length: 8 }).map((_, i) => (
          <span key={i} className={"seg" + (i < filled ? " on" : "")} />
        ))}
      </span>
      <span>{(value * 100).toFixed(0)}</span>
    </span>
  );
}

// ── A single bill in the ranked list ───────────────────────────────────
function BillItem({ bill, rank, selected, onClick, showRelevance, showMatches }) {
  const tierClass = "chip tier-" + bill.tier;
  return (
    <button
      type="button"
      className="bill-item"
      aria-selected={selected}
      onClick={onClick}
    >
      <div className="b-head">
        <span className="b-rank mono">#{String(rank).padStart(2, "0")}</span>
        <span className="b-id mono">{bill.bill_id}</span>
        <span style={{ flex: 1 }} />
        {bill.tier ? <span className={tierClass}>Tier {bill.tier}</span> : null}
      </div>
      <div className="b-title">{bill.short}</div>
      <div className="b-sponsor">{bill.sponsor || "Sponsor n/a"} · {bill.congress}th</div>
      {(showMatches && bill.matches?.length) ? (
        <div className="b-meta">
          {bill.matches.slice(0, 3).map((m) => (
            <span className="chip match" key={m}>{m}</span>
          ))}
        </div>
      ) : null}
      {showRelevance && bill.relevance != null ? (
        <div className="b-meta" style={{ marginTop: 8, justifyContent: "space-between" }}>
          <Relevance value={bill.relevance} />
        </div>
      ) : null}
    </button>
  );
}

// ── Markdown answer renderer ──────────────────────────────────────────
function InlineRuns({ runs }) {
  return (runs || []).map((r, i) => {
    if (r.code) return <code key={i} className="md-code">{r.t}</code>;
    if (r.b && r.i) return <strong key={i}><em>{r.t}</em></strong>;
    if (r.b) return <strong key={i}>{r.t}</strong>;
    if (r.i) return <em key={i}>{r.t}</em>;
    return <React.Fragment key={i}>{r.t}</React.Fragment>;
  });
}

// Collapsible "agent approach" — the planning/reasoning the agent
// narrated before producing the answer, kept clearly separate from it.
function AnswerPlan({ text }) {
  const [open, setOpen] = useState(false);
  if (!text) return null;
  const paras = text.split(/\n+/).map((p) => p.trim()).filter(Boolean);
  return (
    <div className="answer-plan">
      <button type="button" className="plan-toggle" onClick={() => setOpen((o) => !o)}>
        <span className="plan-caret">{open ? "▾" : "▸"}</span>
        <span>Agent approach</span>
        <span className="plan-hint">{open ? "hide" : `${paras.length} step${paras.length === 1 ? "" : "s"}`}</span>
      </button>
      {open ? (
        <div className="plan-body">
          {paras.map((p, i) => <p key={i}>{p}</p>)}
        </div>
      ) : null}
    </div>
  );
}

function AnswerStream({ blocks, streaming }) {
  let leadUsed = false;
  return (
    <div className="answer-body md">
      {(blocks || []).map((b, bi) => {
        const last = bi === blocks.length - 1;
        const caret = streaming && last ? <span className="stream-caret" /> : null;
        const isLead = b.type === "p" && !leadUsed;
        if (b.type === "p") leadUsed = true;
        if (b.type === "hr") return <hr key={bi} className="md-hr" />;
        if (b.type === "table") {
          return (
            <div key={bi} className="md-table-wrap">
              <table className="md-table">
                <thead>
                  <tr>{b.header.map((c, ci) => <th key={ci}><InlineRuns runs={c} /></th>)}</tr>
                </thead>
                <tbody>
                  {b.rows.map((r, ri) => (
                    <tr key={ri}>{r.map((c, ci) => <td key={ci}><InlineRuns runs={c} /></td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (b.type === "h") {
          return (
            <div key={bi} className={"md-h md-h" + b.level}>
              <InlineRuns runs={b.runs} />{caret}
            </div>
          );
        }
        if (b.type === "ul" || b.type === "ol") {
          const Tag = b.type === "ul" ? "ul" : "ol";
          return (
            <Tag key={bi} className="md-list">
              {b.items.map((it, ii) => (
                <li key={ii}>
                  <InlineRuns runs={it} />
                  {streaming && last && ii === b.items.length - 1 ? <span className="stream-caret" /> : null}
                </li>
              ))}
            </Tag>
          );
        }
        return (
          <p key={bi} className={isLead ? "answer-lead" : undefined}>
            <InlineRuns runs={b.runs} />{caret}
          </p>
        );
      })}
    </div>
  );
}

// ── Prompt input ──────────────────────────────────────────────────────
function PromptInput({ value, onChange, onSubmit, onPreset, presets, disabled }) {
  const ref = useRef(null);
  return (
    <div className="prompt">
      <div className="prompt-shell">
        <textarea
          ref={ref}
          value={value}
          placeholder="Ask anything across 191 federal AI-governance bills…"
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              onSubmit();
            }
          }}
          disabled={disabled}
          rows={2}
        />
        <div className="row">
          <span className="scope mono">
            <Icon name="scope" size={11} /> 118th–119th · all chambers
          </span>
          <button
            type="button"
            className="prompt-send accent"
            onClick={onSubmit}
            disabled={disabled || !value.trim()}
            style={{ opacity: !value.trim() ? 0.4 : 1 }}
          >
            Ask <span className="k">⌘↵</span>
          </button>
        </div>
      </div>
      {!value.trim() && presets?.length ? (
        <div className="preset-row">
          {presets.map((p, i) => (
            <button key={i} type="button" className="preset" onClick={() => onPreset(p)}>
              <span className="arrow">↳</span>
              <span>{p}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

// ── Left rail container ───────────────────────────────────────────────
function LeftRail({
  bills, question, answerBlocks, planText, selectedId, onSelect,
  streaming, promptValue, setPromptValue, onSubmit, onPreset, presets,
  showRelevance, showMatches, sourcesMatched, error,
}) {
  const listRef = useRef(null);
  const answerRef = useRef(null);
  const railRef = useRef(null);

  // Drag-resizable Sources / Answer split (vertical, within the rail).
  const [sourcesH, setSourcesH] = useState(320);
  const onSourcesResize = (e) => {
    e.preventDefault();
    const move = (ev) => {
      const r = railRef.current && railRef.current.getBoundingClientRect();
      if (!r) return;
      setSourcesH(Math.max(140, Math.min(r.height - 300, ev.clientY - r.top)));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  return (
    <aside className="rail" ref={railRef} style={{ "--sources-h": sourcesH + "px" }}>
      {/* — Sources — */}
      <section className="rail-section" style={{ minHeight: 0 }}>
        <header className="rail-head">
          <span>Sources <span style={{ color: "var(--ink-3)", marginLeft: 6 }}>· ranked</span></span>
          <span className="count mono">
            {sourcesMatched} <span style={{ color: "var(--ink-4)" }}>/ 191</span>
          </span>
        </header>
        <div className="bill-list scroll" ref={listRef}>
          {bills.map((b, i) => (
            <BillItem
              key={b.id}
              bill={b}
              rank={i + 1}
              selected={b.id === selectedId}
              onClick={() => onSelect(b.id)}
              showRelevance={showRelevance}
              showMatches={showMatches}
            />
          ))}
        </div>
      </section>

      <div className="rail-vresizer" onPointerDown={onSourcesResize}
           title="Drag to resize" />

      {/* — Agent answer — */}
      <section className="rail-section" style={{ minHeight: 0 }}>
        <header className="rail-head">
          <span>Answer</span>
          <span className="count mono">
            <span style={{ color: streaming ? "var(--ink-4)" : "var(--verified)" }}>●</span>
            {streaming ? " streaming" : " from backend"}
          </span>
        </header>
        <div className="answer-wrap scroll" ref={answerRef}>
          {error ? (
            <div style={{
              fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.5,
              color: "#b42318", background: "#fef3f2",
              border: "1px solid #fda29b", borderRadius: 6,
              padding: "8px 10px", marginBottom: 12,
            }}>
              backend error — {error}
            </div>
          ) : null}
          {/* Quoted question */}
          {question.text ? (
            <div style={{
              fontFamily: "var(--font-serif)",
              fontSize: 15, lineHeight: 1.5, marginBottom: 12,
              color: "var(--ink)", borderLeft: "2px solid var(--rule-strong)",
              paddingLeft: 10
            }}>
              {question.text}
            </div>
          ) : null}
          <AnswerPlan text={planText} />
          <AnswerStream blocks={answerBlocks} streaming={streaming} />
        </div>
      </section>

      {/* — Prompt — */}
      <PromptInput
        value={promptValue}
        onChange={setPromptValue}
        onSubmit={onSubmit}
        onPreset={onPreset}
        presets={presets}
        disabled={streaming}
      />
    </aside>
  );
}

window.LeftRail = LeftRail;
