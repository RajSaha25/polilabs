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

// ── Streaming text renderer ───────────────────────────────────────────
function AnswerStream({ paragraphs, streaming, charsRevealed, activeCite, onCiteClick }) {
  // We just render what's revealed, char by char. For simplicity, render
  // each run as a whole if we've passed its cumulative offset.
  let consumed = 0;
  return (
    <div className="answer-body serif" style={{ fontFamily: "var(--font-serif)", fontSize: 14.5, lineHeight: 1.7 }}>
      {paragraphs.map((p, pi) => {
        const elements = [];
        let pConsumed = 0;
        let pLength = 0;
        for (const r of p.runs) {
          const t = r.t || (r.cite ? `[${r.label}]` : "");
          pLength += t.length;
        }
        for (let ri = 0; ri < p.runs.length; ri++) {
          const r = p.runs[ri];
          const t = r.t || (r.cite ? `[${r.label}]` : "");
          const start = consumed;
          const end = consumed + t.length;
          if (streaming && start >= charsRevealed) break;
          let display = t;
          if (streaming && end > charsRevealed) display = t.slice(0, charsRevealed - start);
          if (r.cite) {
            elements.push(
              <button
                key={ri}
                type="button"
                className={"cite mono" + (activeCite === r.cite ? " active" : "")}
                onClick={() => onCiteClick?.(r)}
                title={"Open citation " + r.label}
              >
                {display}
              </button>
            );
          } else if (r.term) {
            elements.push(<em key={ri} style={{ fontWeight: 600, fontStyle: "italic", color: "var(--ink)" }}>{display}</em>);
          } else {
            elements.push(<span key={ri}>{display}</span>);
          }
          consumed = end;
        }
        const showCaret = streaming && (consumed >= charsRevealed) && (pi === paragraphs.length - 1 || consumed === charsRevealed);
        const lastP = pi === paragraphs.length - 1;
        return (
          <p key={pi}>
            {elements}
            {streaming && lastP && consumed >= charsRevealed && <span className="stream-caret" />}
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
  bills, question, answerParagraphs, selectedId, onSelect,
  streaming, charsRevealed, activeCite, onCiteClick,
  promptValue, setPromptValue, onSubmit, onPreset, presets,
  showRelevance, showMatches, sourcesMatched, error,
}) {
  const listRef = useRef(null);
  const answerRef = useRef(null);

  // When activeCite changes (user clicked a card in Decomp), scroll answer
  // so the matching pill comes into view.
  useEffect(() => {
    if (!activeCite || !answerRef.current) return;
    const el = answerRef.current.querySelector(".cite.active");
    if (el) el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeCite]);

  return (
    <aside className="rail">
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
          <div className="answer-meta">
            <span className="pill"><span className="dot" /> verbatim · no paraphrase</span>
            <span style={{ marginLeft: "auto" }}>{question.sources_matched} of {question.sources_total} sources</span>
          </div>
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
          <AnswerStream
            paragraphs={answerParagraphs}
            streaming={streaming}
            charsRevealed={charsRevealed}
            activeCite={activeCite}
            onCiteClick={onCiteClick}
          />
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
