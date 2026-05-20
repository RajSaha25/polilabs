/* global React, Icon */
// Polilabs — Right Decomp panel. Same bill in one of four lenses:
//   Structure (default), Definition, Amendment, Citation.

const { useState, useEffect, useRef } = React;

const MODES = [
  { id: "structure",  label: "Structure",  icon: "list-tree" },
  { id: "definition", label: "Definition", icon: "quote" },
  { id: "amendment", label: "Amendment", icon: "diff" },
  { id: "citation",   label: "Citation",   icon: "link" },
];

// ── Mode tabs ─────────────────────────────────────────────────────────
function ModeTabs({ mode, onChange, counts }) {
  return (
    <div className="mode-tabs" role="tablist">
      {MODES.map((m) => (
        <button
          key={m.id}
          role="tab"
          className="mode-tab"
          aria-selected={mode === m.id}
          onClick={() => onChange(m.id)}
        >
          {m.label}
          <span className="count mono">{counts[m.id]}</span>
        </button>
      ))}
    </div>
  );
}

// ── Definition mode ──────────────────────────────────────────────────
function DefinitionMode({ bill, activeAnchor, onSelect }) {
  return (
    <div className="decomp-body">
      <div className="dc-section-head">
        <span className="num">DEFINED</span>
        <span className="title">Defined terms</span>
        <span className="count">{bill.definitions.length} terms</span>
      </div>

      {bill.definitions.map((d) => {
        const active = activeAnchor === d.anchor;
        return (
          <div
            key={d.id}
            className="def-card"
            data-active={active ? "true" : "false"}
            data-anchor={d.anchor}
            onClick={() => onSelect(d.anchor)}
          >
            <div className="term-row">
              <span className="term-name">{d.term}</span>
              <span className={"term-kind " + (d.kind === "byref" ? "byref" : "")}>
                {d.kind === "byref" ? "by reference" : "direct"}
              </span>
            </div>
            <div className="def-body">
              <span className="quoted">&ldquo;{d.quoted}&rdquo;</span>
            </div>
            <div className="def-footer">
              <span className="cite-ref">
                <Icon name="anchor" size={11} />
                {d.cite}
                {d.refs_to ? <span style={{ color: "var(--ink-4)", marginLeft: 6 }}>→ {d.refs_to}</span> : null}
              </span>
              {d.verified ? (
                <span className="verified-pill">
                  <Icon name="check" size={11} />
                  verified
                </span>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Amendment mode ───────────────────────────────────────────────────
function AmendmentMode({ bill, activeAnchor, onSelect }) {
  return (
    <div className="decomp-body">
      <div className="dc-section-head">
        <span className="num">EDITS</span>
        <span className="title">Statutory amendments</span>
        <span className="count">{bill.amendments.length} edits</span>
      </div>

      {bill.amendments.map((a) => {
        const active = activeAnchor === a.anchor;
        return (
          <div
            key={a.id}
            className="amend-card"
            data-active={active ? "true" : "false"}
            data-anchor={a.anchor}
            onClick={() => onSelect(a.anchor)}
          >
            <div className="am-head">
              <span className={"am-op " + a.op}>
                {a.op === "strike" ? "strike" :
                 a.op === "insert" ? "insert" :
                 a.op === "replace" ? "replace" : "append"}
              </span>
              <span className="am-target">
                {a.target_label}
              </span>
              <span className="mono" style={{ color: "var(--ink-4)" }}>{a.target}</span>
            </div>
            <div className="am-body">
              {a.rows.map((r, i) => (
                <div key={i} className={"diff-row " + r.kind}>
                  <span className="marker">{r.kind === "del" ? "−" : "+"}</span>
                  <span className="text">{r.text}</span>
                </div>
              ))}
            </div>
            <div className="am-foot">
              <span className="cite-ref">
                <Icon name="anchor" size={11} /> {a.cite}
              </span>
              {a.verified ? (
                <span style={{ color: "var(--verified)", display: "inline-flex", alignItems: "center", gap: 4 }}>
                  <Icon name="check" size={11} /> verified against U.S. Code
                </span>
              ) : (
                <span style={{ color: "var(--ink-4)", display: "inline-flex", alignItems: "center", gap: 4 }}>
                  <Icon name="info" size={11} /> target text not yet verified
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ── Citation mode ────────────────────────────────────────────────────
function CitationMode({ bill, activeAnchor, onSelect }) {
  return (
    <div className="decomp-body">
      <div className="dc-section-head">
        <span className="num">ALL</span>
        <span className="title">Statutes cited by this bill</span>
        <span className="count">
          {bill.citations.reduce((n, g) => n + g.items.length, 0)} citations
        </span>
      </div>

      {bill.citations.map((g) => (
        <div className="cite-group" key={g.group}>
          <div style={{
            fontFamily: "var(--font-mono)", fontSize: 11,
            color: "var(--ink-3)", letterSpacing: "0.06em",
            textTransform: "uppercase", padding: "4px 12px",
            marginBottom: 4
          }}>
            {g.group}
          </div>
          <div className="cite-list">
            {g.items.map((c) => {
              const active = activeAnchor === c.anchor;
              return (
                <div
                  key={c.id}
                  className="cite-row"
                  data-active={active ? "true" : "false"}
                  onClick={() => onSelect(c.anchor)}
                >
                  <span className="ref">{c.ref}</span>
                  <span className="title">{c.title}</span>
                  <span className={"source " + (c.verified ? "verified" : "")}>
                    {c.verified ? <Icon name="check" size={10} /> : <Icon name="info" size={10} />}
                    {c.source}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Structure mode (default) ─────────────────────────────────────────
function StructureMode({ bill, activeAnchor, onSelect }) {
  const { sections, stats } = bill.structure;
  return (
    <div className="decomp-body">
      <div className="dc-section-head" style={{ marginBottom: 12 }}>
        <span className="num">OUTLINE</span>
        <span className="title">Section hierarchy</span>
        <span className="count">{sections.filter((s) => s.level === 1).length} sections</span>
      </div>

      <div className="struct-tree">
        {sections.map((s) => (
          <div
            key={s.id}
            className="struct-node"
            style={{ paddingLeft: 10 + (s.level - 1) * 18 }}
            data-active={activeAnchor === s.anchor ? "true" : "false"}
            data-anchor={s.anchor}
            onClick={() => onSelect(s.anchor)}
          >
            <span className="marker">{s.marker}</span>
            {s.title ? <span className="title">{s.title}</span> : null}
          </div>
        ))}
      </div>

      <div className="struct-summary">
        <div className="s-stat">
          <span className="v">{stats.sections}</span>
          <span className="l">sections</span>
        </div>
        <div className="s-stat">
          <span className="v">{stats.definitions}</span>
          <span className="l">definitions</span>
        </div>
        <div className="s-stat">
          <span className="v">{stats.amendments}</span>
          <span className="l">amendments</span>
        </div>
        <div className="s-stat">
          <span className="v">{stats.citations}</span>
          <span className="l">citations</span>
        </div>
      </div>
    </div>
  );
}

// ── Decomp panel container ───────────────────────────────────────────
function DecompPanel({ bill, mode, setMode, activeAnchor, onSelect }) {
  const scrollRef = useRef(null);

  const counts = {
    structure:  bill.structure?.sections?.length ?? 0,
    definition: bill.definitions?.length ?? 0,
    amendment: bill.amendments?.length ?? 0,
    citation:   bill.citations?.reduce((n, g) => n + g.items.length, 0) ?? 0,
  };

  // When activeAnchor changes (a click came from the Text panel),
  // scroll the matching card into view and pulse it.
  useEffect(() => {
    if (!activeAnchor || !scrollRef.current) return;
    const el = scrollRef.current.querySelector(`[data-anchor="${activeAnchor}"]`);
    if (!el) return;
    el.classList.add("card-target");
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    const t = setTimeout(() => el.classList.remove("card-target"), 1100);
    return () => clearTimeout(t);
  }, [activeAnchor, mode]);

  return (
    <div className="panel-col decomp-col">
      <div className="panel-bar">
        <span className="panel-label">
          <span className="dot" />
          Decomp · {MODES.find((m) => m.id === mode)?.label.toLowerCase()}
        </span>
        <ModeTabs mode={mode} onChange={setMode} counts={counts} />
      </div>

      <div className="scroll" ref={scrollRef} style={{ minHeight: 0, flex: 1 }}>
        {mode === "structure"  && <StructureMode  bill={bill} activeAnchor={activeAnchor} onSelect={onSelect} />}
        {mode === "definition" && <DefinitionMode bill={bill} activeAnchor={activeAnchor} onSelect={onSelect} />}
        {mode === "amendment" && <AmendmentMode bill={bill} activeAnchor={activeAnchor} onSelect={onSelect} />}
        {mode === "citation"   && <CitationMode   bill={bill} activeAnchor={activeAnchor} onSelect={onSelect} />}
      </div>
    </div>
  );
}

window.DecompPanel = DecompPanel;
