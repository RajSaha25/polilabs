/* global React, Icon */
// Polilabs — Left Rail
// A conversation rail: a History list of past questions, the agent's
// answer for the active question with its ranked source bills folded in,
// and the prompt input pinned at the bottom.

const { useState, useRef, useEffect } = React;

// ── Clickable bill citations ──────────────────────────────────────────
// The agent names bills by number in its answer ("S. 3312", "H.R. 8516").
// Each ranked bill's number form is matched and turned into a clickable
// citation that opens the bill in the viewer. Matching only ever targets
// a bill already in the list, so a wrong link is near-impossible; a
// missed mention just stays plain text.
function buildBillMatchers(bills) {
  const out = [];
  (bills || []).forEach((bill) => {
    // bill.bill_id is the human form, e.g. "H.R. 6881" / "S. 5436".
    const raw = String(bill.bill_id || "").trim();
    const numM = raw.match(/(\d+)\s*$/);
    if (!numM) return;
    const letters = raw.slice(0, numM.index).replace(/[^A-Za-z]/g, "");
    if (!letters) return;
    // Letters interleaved with an optional dot + optional space, so
    // "H.R. 6881" also matches "HR 6881" / "H.R.6881" in the prose.
    const letterPat = letters.split("").map((c) => c + "\\.?\\s?").join("");
    out.push({
      regex: new RegExp("\\b" + letterPat + numM[1] + "\\b", "g"),
      billId: bill.id,
    });
  });
  return out;
}
function linkifyText(text, matchers, onSelectBill) {
  if (!text || !matchers || !matchers.length) return text;
  const hits = [];
  matchers.forEach((mt) => {
    for (const found of String(text).matchAll(mt.regex)) {
      if (found.index != null) {
        hits.push({ start: found.index, end: found.index + found[0].length, billId: mt.billId });
      }
    }
  });
  if (!hits.length) return text;
  hits.sort((a, b) => a.start - b.start);
  const out = [];
  let cursor = 0, k = 0;
  hits.forEach((h) => {
    if (h.start < cursor) return;
    if (h.start > cursor) out.push(text.slice(cursor, h.start));
    out.push(
      <button key={"bl" + (k++)} type="button" className="bill-ref"
        onClick={() => onSelectBill && onSelectBill(h.billId)} title="Open this bill">
        {text.slice(h.start, h.end)}
      </button>
    );
    cursor = h.end;
  });
  if (cursor < text.length) out.push(text.slice(cursor));
  return out;
}

// ── Markdown answer renderer ──────────────────────────────────────────
// Inline emphasis is rendered as italic — including Markdown bold. Bold
// is reserved for section headings so they stand out as the structure;
// liberal inline **bold** would compete with that.
function InlineRuns({ runs, matchers, onSelectBill }) {
  return (runs || []).map((r, i) => {
    if (r.code) return <code key={i} className="md-code">{r.t}</code>;
    const content = linkifyText(r.t, matchers, onSelectBill);
    if (r.b || r.i) return <em key={i}>{content}</em>;
    return <React.Fragment key={i}>{content}</React.Fragment>;
  });
}

// The agent's chain of thought — its tool steps (what it searched/read,
// in plain English) and the reasoning it narrated. Shown by default and
// streamed live so a policymaker can watch and audit how the answer was
// built; collapsible once they've seen it.
function AnswerPlan({ text, steps = [], streaming }) {
  const [manual, setManual] = useState(null);
  const open = manual === null ? true : manual;   // present by default
  const paras = (text || "").split(/\n+/).map((p) => p.trim()).filter(Boolean);
  const count = steps.length || paras.length;
  if (!count && !streaming) return null;
  return (
    <div className="answer-plan">
      <button type="button" className="plan-toggle" onClick={() => setManual(!open)}>
        <span className="plan-caret">{open ? "▾" : "▸"}</span>
        <span>Chain of thought</span>
        <span className="plan-hint">{open ? "hide" : `${count} step${count === 1 ? "" : "s"}`}</span>
      </button>
      {open ? (
        <div className="plan-body">
          {steps.length ? (
            <ul className="cot-steps">
              {steps.map((s, i) => (
                <li key={i} className="cot-step"><span className="cot-dot" />{s.label}</li>
              ))}
              {streaming ? (
                <li className="cot-step cot-live"><span className="spinner-sm" /> working…</li>
              ) : null}
            </ul>
          ) : streaming && !paras.length ? (
            <p className="cot-thinking">thinking…</p>
          ) : null}
          {paras.map((p, i) => <p key={i} className="cot-thought">{p}</p>)}
        </div>
      ) : null}
    </div>
  );
}

function AnswerStream({ blocks, streaming, bills, onSelectBill }) {
  let leadUsed = false;
  const headNums = {};   // sequential number per heading level
  const matchers = buildBillMatchers(bills);
  // Thin wrapper so every run gets the bill-citation matchers.
  const Runs = ({ runs }) => (
    <InlineRuns runs={runs} matchers={matchers} onSelectBill={onSelectBill} />
  );
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
                  <tr>{b.header.map((c, ci) => <th key={ci}><Runs runs={c} /></th>)}</tr>
                </thead>
                <tbody>
                  {b.rows.map((r, ri) => (
                    <tr key={ri}>{r.map((c, ci) => <td key={ci}><Runs runs={c} /></td>)}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (b.type === "h") {
          headNums[b.level] = (headNums[b.level] || 0) + 1;
          return (
            <div key={bi} className={"md-h md-h" + b.level}>
              <span className="md-h-num">{headNums[b.level]}.</span>{" "}
              <Runs runs={b.runs} />{caret}
            </div>
          );
        }
        if (b.type === "ul" || b.type === "ol") {
          const Tag = b.type === "ul" ? "ul" : "ol";
          return (
            <Tag key={bi} className="md-list">
              {b.items.map((it, ii) => (
                <li key={ii}>
                  <Runs runs={it} />
                  {streaming && last && ii === b.items.length - 1 ? <span className="stream-caret" /> : null}
                </li>
              ))}
            </Tag>
          );
        }
        return (
          <p key={bi} className={isLead ? "answer-lead" : undefined}>
            <Runs runs={b.runs} />{caret}
          </p>
        );
      })}
    </div>
  );
}

// ── Ranked source bills — folded into the answer ──────────────────────
// The bills the agent drew on, listed right under its answer. Clicking a
// row opens that bill in the viewer; the row matching the open bill is
// marked. This replaces the old standalone "Sources" panel.
function SourceRow({ bill, rank, selected, onClick }) {
  // bill.short is often just the bill number again when the tool result
  // carried no short_title — don't print the identifier twice.
  const title = bill.short && bill.short !== bill.bill_id ? bill.short : "";
  return (
    <button type="button" className="source-row" aria-selected={selected} onClick={onClick}>
      <span className="sr-rank mono">#{String(rank).padStart(2, "0")}</span>
      <span className="sr-id mono">{bill.bill_id}</span>
      <span className="sr-title">{title}</span>
      <span className="sr-cong mono">{bill.congress ? bill.congress + "th" : ""}</span>
    </button>
  );
}

function SourceList({ bills, selectedId, onSelect }) {
  if (!bills || !bills.length) return null;
  return (
    <div className="source-list">
      <div className="source-list-head">
        <span>Sources</span>
        <span className="count mono">{bills.length} ranked</span>
      </div>
      {bills.map((b, i) => (
        <SourceRow
          key={b.id}
          bill={b}
          rank={i + 1}
          selected={b.id === selectedId}
          onClick={() => onSelect(b.id)}
        />
      ))}
    </div>
  );
}

// ── Prompt input ──────────────────────────────────────────────────────
// Enter submits; Shift+Enter inserts a newline. No send button — the
// keystroke is the only affordance, so the input stays uncluttered.
function PromptInput({ value, onChange, onSubmit, onPreset, presets, disabled }) {
  const ref = useRef(null);
  const [showPresets, setShowPresets] = useState(false);
  return (
    <div className="prompt">
      <div className="prompt-shell">
        <textarea
          ref={ref}
          value={value}
          placeholder="Ask anything across the polilabs legislative corpus…"
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (!disabled && value.trim()) onSubmit();
            }
          }}
          disabled={disabled}
          rows={2}
        />
        <div className="row">
          <span className="prompt-hint mono">
            {disabled ? "working…" : "↵ to send · ⇧↵ newline"}
          </span>
        </div>
      </div>
      {/* Suggested-questions toggle stays visible regardless of whether
          the prompt input has text. The previous `!value.trim() &&`
          gate caused the whole block to disappear the moment the user
          started typing, which read as a jumpy UI bug: an affordance
          shouldn't vanish when you engage with a sibling element. The
          collapsible itself is the on/off control — collapsed by
          default so it doesn't dominate the rail. */}
      {presets?.length ? (
        <div className="preset-block">
          <button
            type="button"
            className="preset-toggle"
            onClick={() => setShowPresets((o) => !o)}
          >
            <span className="plan-caret">{showPresets ? "▾" : "▸"}</span>
            <span>Suggested questions</span>
          </button>
          {showPresets ? (
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
      ) : null}
    </div>
  );
}

// ── Grounded bill summary card ────────────────────────────────────────
// A short, plain-language summary of the SELECTED bill, generated by a
// cheap model and grounded in the bill's table of contents + metadata.
// It is LLM-generated, so it is clearly labelled and visually distinct
// from the verbatim statute text (the anti-hallucination thesis): the
// summary helps you triage, the bill text is the source of truth.
function BillSummary({ summary, bill }) {
  if (!summary) return null;
  const { loading, text, error } = summary;
  if (!loading && !text && !error) return null;
  return (
    <div className="bill-summary">
      <div className="bill-summary-head">
        <Icon name="sparkle" size={12} className="bill-summary-spark" />
        <span className="bill-summary-title">
          Summary{bill && bill.bill_id ? " · " + bill.bill_id : ""}
        </span>
        <span className="bill-summary-tag"
              title="Model-generated from the bill's table of contents & metadata — not verbatim statute text.">
          AI · grounded
        </span>
      </div>
      {loading ? (
        <div className="bill-summary-loading"><span className="spinner-sm" /> summarizing…</div>
      ) : error ? (
        <div className="bill-summary-error">Couldn’t summarize — {error}</div>
      ) : (
        <p className="bill-summary-text">{text}</p>
      )}
    </div>
  );
}

// ── Left rail container ───────────────────────────────────────────────
function LeftRail({
  bills, turns, activeTurnId, onSelectTurn,
  question, answerBlocks, planText, toolSteps = [], selectedId, summary, onSelect,
  streaming, promptValue, setPromptValue, onSubmit, onPreset, presets,
  error,
}) {
  const answerRef = useRef(null);
  const historyRef = useRef(null);
  const hasHistory = (turns || []).length > 1;

  // History runs oldest → newest, so a new question lands at the bottom
  // (standard chat order). Keep that newest entry in view.
  useEffect(() => {
    const el = historyRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [(turns || []).length]);

  return (
    <aside className="rail">
      {/* — History — every past question stays reachable; asking a new
          one no longer discards the previous answer. — */}
      {hasHistory ? (
        <section className="rail-history">
          <header className="rail-head">
            <span>History</span>
            <span className="count mono">{turns.length}</span>
          </header>
          <div className="history-list scroll" ref={historyRef}>
            {turns.map((t) => (
              <button
                key={t.id}
                type="button"
                className={"history-q" + (t.id === activeTurnId ? " active" : "")}
                onClick={() => onSelectTurn(t.id)}
                title={t.question}
              >
                {t.question}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {/* — Agent answer + the ranked sources it used — */}
      <section className="rail-answer">
        <header className="rail-head">
          <span>Answer</span>
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
          <AnswerPlan text={planText} steps={toolSteps} streaming={streaming} />
          <AnswerStream blocks={answerBlocks} streaming={streaming}
            bills={bills} onSelectBill={onSelect} />
          <BillSummary summary={summary} bill={(bills || []).find((b) => b.id === selectedId)} />
          <SourceList bills={bills} selectedId={selectedId} onSelect={onSelect} />
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
