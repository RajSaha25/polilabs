/* global React, Icon, TextPanel, DecompPanel */
// Polilabs — Bill viewer (Text + Decomp side by side, with shared
// header). Also exposes loading + empty states for the same area.

const { useState } = React;

// ── Loading state ─────────────────────────────────────────────────────
function BillViewerLoading() {
  const steps = [
    { id: "retrieve", label: "Retrieving 14 of 191 bills" },
    { id: "extract", label: "Extracting verbatim sections" },
    { id: "verify", label: "Verifying citations against U.S. Code" },
    { id: "rank", label: "Ranking by semantic relevance" },
  ];
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
        {steps.map((s, i) => (
          <React.Fragment key={s.id}>
            <span className={"step " + (i === 1 ? "now" : "")}>
              {i < 1 ? "✓ " : ""}{s.label}
            </span>
            {i < steps.length - 1 ? <span style={{ color: "var(--accent-line)" }}>›</span> : null}
          </React.Fragment>
        ))}
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
function BillViewerEmpty({ presets = [], onPreset }) {
  return (
    <div className="stage" style={{ gridTemplateRows: "1fr" }}>
      <div className="empty">
        <div className="empty-card">
          <div className="empty-mark">
            <Icon name="scales" size={26} strokeWidth={1.25} />
          </div>
          <div>
            <h3>The bill viewer is empty.</h3>
            <p>
              Polilabs only displays text it can verify against an authoritative source.
              Ask a research question to start, or pick a recent thread.
            </p>
          </div>
          <div className="empty-suggests">
            {presets.map((p, i) => (
              <button key={i} type="button" onClick={() => onPreset?.(p)}>
                <span>&ldquo;{p}&rdquo;</span>
                <span className="k">↵</span>
              </button>
            ))}
          </div>
          <div className="mono" style={{
            display: "flex", gap: 18, marginTop: 8,
            fontSize: 11, color: "var(--ink-4)",
            paddingTop: 16, borderTop: "1px solid var(--rule-faint)",
            width: "100%", justifyContent: "center"
          }}>
            <span>191 bills indexed</span>
            <span style={{ color: "var(--rule-strong)" }}>·</span>
            <span>118th–119th Congress</span>
            <span style={{ color: "var(--rule-strong)" }}>·</span>
            <span>updated 4h ago</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Loaded state header — bill identity + pager ───────────────────────
function BillViewerHeader({ bill, position, onPrev, onNext, total }) {
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
        <div className="bv-sub">
          Sponsored by <strong style={{ color: "var(--ink-2)", fontWeight: 500 }}>{bill.sponsor || "—"}</strong>
          {bill.cosponsors ? (
            <React.Fragment>{" · "}{bill.cosponsors} cosponsor{bill.cosponsors === 1 ? "" : "s"}</React.Fragment>
          ) : null}
          {bill.relevance != null ? (
            <React.Fragment>{" · "}relevance <span className="mono" style={{ color: "var(--ink-2)" }}>{(bill.relevance * 100).toFixed(0)}</span></React.Fragment>
          ) : null}
        </div>
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
}) {
  // When user clicks a Decomp card → highlight the matching anchor in the Text panel.
  // When user clicks an anchored term in the Text panel → highlight the matching Decomp card.
  // Both flows funnel through setActiveAnchor.

  return (
    <section className="stage">
      <BillViewerHeader bill={bill} position={position} total={total} onPrev={onPrev} onNext={onNext} />
      <div className="bv-split">
        <TextPanel
          bill={bill}
          activeAnchor={activeAnchor}
          onAnchorClick={setActiveAnchor}
        />
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
