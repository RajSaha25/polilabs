/* global React, Icon, TextPanel, DecompPanel */
// Polilabs — Bill viewer (Text + Decomp side by side, with shared
// header). Also exposes loading + empty states for the same area.

const { useState, useRef } = React;

// ── Loading state ─────────────────────────────────────────────────────
function BillViewerLoading() {
  return (
    <div className="stage">
      <div className="bv-header">
        <div>
          <div className="bv-id">
            <div className="skeleton" style={{ width: 90, height: 11 }} />
            <span className="sep">·</span>
            <div className="skeleton" style={{ width: 60, height: 11 }} />
          </div>
          <h1 className="bv-title">
            <span className="skeleton" style={{ display: "inline-block", width: 380, height: 28, borderRadius: 4 }} />
          </h1>
          <div className="bv-sub">
            <span className="skeleton" style={{ display: "inline-block", width: 220, height: 12, borderRadius: 4 }} />
          </div>
        </div>
        <div className="bv-pager">
          <span className="skeleton" style={{ width: 60, height: 22, borderRadius: 4 }} />
        </div>
      </div>

      <div className="loading-banner">
        <span className="spinner" />
        <span className="step now">Loading verbatim text and decomposition…</span>
      </div>

      <div className="bv-split">
        <div className="panel-col text-col">
          <div className="panel-bar">
            <span className="panel-label"><span className="dot" /> Text · verbatim</span>
          </div>
          <div className="scroll" style={{ flex: 1 }}>
            <div className="text-body">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} style={{ marginBottom: 22 }}>
                  <div className="skeleton" style={{ height: 11, width: 70, marginBottom: 8 }} />
                  <div className="skeleton" style={{ height: 22, width: "60%", marginBottom: 14 }} />
                  <div className="skeleton" style={{ height: 13, width: "100%", marginBottom: 6 }} />
                  <div className="skeleton" style={{ height: 13, width: "97%", marginBottom: 6 }} />
                  <div className="skeleton" style={{ height: 13, width: "94%", marginBottom: 6 }} />
                  <div className="skeleton" style={{ height: 13, width: "78%" }} />
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="panel-col decomp-col">
          <div className="panel-bar">
            <span className="panel-label"><span className="dot" /> Decomp · structure</span>
            <div className="skeleton" style={{ width: 180, height: 24, borderRadius: 6 }} />
          </div>
          <div className="scroll" style={{ flex: 1 }}>
            <div className="decomp-body">
              {Array.from({ length: 8 }).map((_, i) => (
                <div key={i} style={{
                  display: "grid",
                  gridTemplateColumns: "60px 1fr 40px",
                  gap: 12,
                  padding: "10px 12px",
                  marginLeft: i % 3 === 1 ? 24 : i % 3 === 2 ? 48 : 0,
                }}>
                  <div className="skeleton" style={{ height: 11 }} />
                  <div className="skeleton" style={{ height: 13, width: `${60 + ((i * 13) % 30)}%` }} />
                  <div className="skeleton" style={{ height: 11 }} />
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────────
//
// Two modes:
//   - first visit (default): full pitch + preset prompts. The user
//     hasn't asked anything yet, so we onboard them with examples.
//   - `answered` mode: the user already asked, but the agent's answer
//     didn't surface a specific bill (scope question, false-premise
//     probe, aggregate-only answer, etc.). Showing the same "ask a
//     research question to start" pitch + the same three preset
//     buttons looks awkward — the user obviously already did that.
//     We drop the presets and rewrite the copy to point at where the
//     answer actually landed (the left rail).
function BillViewerEmpty({ presets = [], onPreset, answered = false }) {
  return (
    <div className="stage" style={{ gridTemplateRows: "1fr" }}>
      <div className="empty">
        <div className="empty-card">
          <div className="empty-mark">
            <Icon name="scales" size={26} strokeWidth={1.25} />
          </div>
          <div>
            <h3>
              {answered
                ? "No specific bill to display."
                : "The bill viewer is empty."}
            </h3>
            <p>
              {answered
                ? "The agent answered in the left panel — this question didn't surface a single bill. Try a more specific query, or pick a bill from a previous answer."
                : "Polilabs only displays text it can verify against an authoritative source. Ask a research question to start, or pick a recent thread."}
            </p>
          </div>
          {!answered && presets.length > 0 && (
            <div className="empty-suggests">
              {presets.map((p, i) => (
                <button key={i} type="button" onClick={() => onPreset?.(p)}>
                  <span>&ldquo;{p}&rdquo;</span>
                  <span className="k">↵</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Loaded state header — bill identity + pager ───────────────────────
function BillViewerHeader({ bill, position, onPrev, onNext, total }) {
  // Sponsor / cosponsors / relevance are only known for some bills,
  // depending on which tool surfaced them. Show only what's present —
  // an empty "Sponsored by —" line is noise, so it's dropped entirely.
  const subParts = [];
  if (bill.sponsor) {
    subParts.push(
      <span key="sp">Sponsored by <strong style={{ color: "var(--ink-2)", fontWeight: 500 }}>{bill.sponsor}</strong></span>
    );
  }
  if (bill.cosponsors) {
    subParts.push(<span key="co">{bill.cosponsors} cosponsor{bill.cosponsors === 1 ? "" : "s"}</span>);
  }
  // Relevance score dropped — it was a per-query relative number (the
  // top hit always normalised to 100), not a real cross-corpus metric.
  return (
    <div className="bv-header">
      <div>
        <div className="bv-id mono">
          <span>{bill.bill_id}</span>
          <span className="sep">·</span>
          <span>{bill.congress}th Congress</span>
          {bill.introduced ? (
            <React.Fragment>
              <span className="sep">·</span>
              <span>Introduced {bill.introduced}</span>
            </React.Fragment>
          ) : null}
          {bill.tier ? (
            <span className={"chip tier-" + bill.tier} style={{ marginLeft: 6 }}>Tier {bill.tier}</span>
          ) : null}
        </div>
        <h1 className="bv-title">{bill.short}</h1>
        {subParts.length ? (
          <div className="bv-sub">
            {subParts.map((p, i) => (
              <React.Fragment key={i}>{i > 0 ? " · " : ""}{p}</React.Fragment>
            ))}
          </div>
        ) : null}
      </div>
      <div className="bv-pager">
        <button className="pg-btn" onClick={onPrev} disabled={position <= 0} aria-label="Previous bill">
          <Icon name="chevron-left" size={14} />
        </button>
        <span className="pg-pos mono">
          {String(position + 1).padStart(2, "0")} <span style={{ color: "var(--ink-4)" }}>/ {String(total).padStart(2, "0")}</span>
        </span>
        <button className="pg-btn" onClick={onNext} disabled={position >= total - 1} aria-label="Next bill">
          <Icon name="chevron-right" size={14} />
        </button>
      </div>
    </div>
  );
}

// ── Loaded bill viewer ────────────────────────────────────────────────
function BillViewer({
  bill, position, total, onPrev, onNext,
  mode, setMode, activeAnchor, setActiveAnchor,
  textFrac, setTextFrac,
}) {
  // Sync highlighting: clicking a Decomp card highlights the matching
  // anchor in the Text panel and vice versa; both funnel through
  // setActiveAnchor. The Text|Decomp divider is drag-resizable.
  const splitRef = useRef(null);

  const onResize = (e) => {
    e.preventDefault();
    const move = (ev) => {
      const el = splitRef.current;
      if (!el) return;
      const r = el.getBoundingClientRect();
      let f = (ev.clientX - r.left) / r.width;
      f = Math.max(0.32, Math.min(0.68, f));
      setTextFrac(f);
    };
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

  return (
    <section className="stage">
      <BillViewerHeader bill={bill} position={position} total={total} onPrev={onPrev} onNext={onNext} />
      <div
        className="bv-split"
        ref={splitRef}
        style={{ gridTemplateColumns: `${textFrac}fr 8px ${1 - textFrac}fr` }}
      >
        <TextPanel
          bill={bill}
          activeAnchor={activeAnchor}
          onAnchorClick={setActiveAnchor}
        />
        <div className="col-resizer" onPointerDown={onResize} title="Drag to resize panels" />
        <DecompPanel
          bill={bill}
          mode={mode}
          setMode={setMode}
          activeAnchor={activeAnchor}
          onSelect={setActiveAnchor}
        />
      </div>
    </section>
  );
}

window.BillViewer = BillViewer;
window.BillViewerLoading = BillViewerLoading;
window.BillViewerEmpty = BillViewerEmpty;
