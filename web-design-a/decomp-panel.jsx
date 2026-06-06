/* global React, Icon, StatuteBody */
// Polilabs — Right Decomp panel. Same bill in one of four lenses:
//   Structure (default), Definition, Amendment, Citation.

const { useState, useEffect, useRef, useMemo } = React;

const MODES = [
  { id: "structure",  label: "Structure",  icon: "list-tree" },
  { id: "definition", label: "Definition", icon: "quote" },
  { id: "amendment", label: "Amendment", icon: "diff" },
  { id: "citation",   label: "Citation",   icon: "link" },
  { id: "notes",      label: "Notes",      icon: "doc" },
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
              {d.body ? <StatuteBody leafHtml={d.body.leafHtml} blocks={d.body.blocks} /> : null}
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
// The outline is a collapsible tree: a section with nested children
// starts collapsed, so a deep bill is not dumped flat. Click the
// chevron to expand a branch; click the row to scroll the Text panel.
function StructureMode({ bill, activeAnchor, onSelect }) {
  const { sections, stats } = bill.structure;

  // A section has children when the next section sits one level deeper.
  const hasChildren = (i) =>
    i + 1 < sections.length && sections[i + 1].level > sections[i].level;

  // Every parent section starts collapsed.
  const [collapsed, setCollapsed] = useState(() => {
    const init = new Set();
    sections.forEach((s, i) => { if (hasChildren(i)) init.add(s.id); });
    return init;
  });
  const toggle = (id) => setCollapsed((prev) => {
    const next = new Set(prev);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });

  // Walk the flat, level-indexed list; skip nodes inside a collapsed
  // branch (any deeper node after a collapsed one, until the level
  // returns to that node's depth or shallower).
  const visible = [];
  let hideBelow = Infinity;
  sections.forEach((s, i) => {
    if (s.level > hideBelow) return;
    hideBelow = Infinity;
    visible.push({ s, parent: hasChildren(i) });
    if (collapsed.has(s.id)) hideBelow = s.level;
  });

  return (
    <div className="decomp-body">
      <div className="dc-section-head" style={{ marginBottom: 12 }}>
        <span className="num">OUTLINE</span>
        <span className="title">Section hierarchy</span>
        <span className="count">{sections.filter((s) => s.level === 1).length} sections</span>
      </div>

      <div className="struct-tree">
        {visible.map(({ s, parent }) => {
          const isCollapsed = collapsed.has(s.id);
          return (
            <div
              key={s.id}
              className="struct-node"
              style={{ paddingLeft: 10 + (s.level - 1) * 18 }}
              data-active={activeAnchor === s.anchor ? "true" : "false"}
              data-anchor={s.anchor}
              onClick={() => onSelect(s.anchor)}
            >
              {parent ? (
                <button
                  type="button"
                  className="struct-toggle"
                  aria-expanded={!isCollapsed}
                  aria-label={isCollapsed ? "Expand section" : "Collapse section"}
                  onClick={(e) => { e.stopPropagation(); toggle(s.id); }}
                >
                  {isCollapsed ? "▸" : "▾"}
                </button>
              ) : (
                <span className="struct-toggle struct-toggle-empty" aria-hidden="true" />
              )}
              <span className="marker">{s.marker}</span>
              {s.title ? <span className="title">{s.title}</span> : null}
            </div>
          );
        })}
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

// ── Notes mode ───────────────────────────────────────────────────────
// The researcher's own highlights + notes on this bill. Mechanical, like
// the rest of the Decomp panel: it lists what the user (or the agent)
// flagged verbatim — it never paraphrases the law. Click a card to jump
// to the passage; edit or delete in place.
function NoteCard({ note, onSelect, onEdit, onRemove }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(note.body || "");
  const isAgent = note.source === "agent";
  return (
    <div
      className={"note-card hl-" + (note.color || "yellow") + (isAgent ? " agent" : "")}
      data-anchor={note.section_id || undefined}
    >
      {note.quote ? (
        <div className="note-quote" onClick={() => note.section_id && onSelect(note.section_id)}>
          <Icon name="quote" size={11} />
          <span>{note.quote.length > 220 ? note.quote.slice(0, 220) + "…" : note.quote}</span>
        </div>
      ) : null}

      {editing ? (
        <div className="note-edit">
          <textarea
            className="note-input"
            value={draft}
            autoFocus
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Escape") { setEditing(false); setDraft(note.body || ""); } }}
            rows={3}
          />
          <div className="note-actions">
            <button type="button" className="note-btn ghost" onClick={() => { setEditing(false); setDraft(note.body || ""); }}>Cancel</button>
            <button type="button" className="note-btn primary"
              onClick={() => { Promise.resolve(onEdit(note.id, { body: draft })).finally(() => setEditing(false)); }}>
              Save
            </button>
          </div>
        </div>
      ) : (
        <div className="note-text" onClick={() => !isAgent && setEditing(true)}>
          {note.body
            ? note.body
            : <span className="note-empty">{isAgent ? "Flagged by the agent — review this passage." : "No note — click to add text."}</span>}
        </div>
      )}

      <div className="note-foot">
        <span className="note-src">{isAgent ? "agent flag" : "your note"}</span>
        <button type="button" className="note-del" aria-label="Delete note" onClick={() => onRemove(note.id)}>
          <Icon name="x" size={11} />
        </button>
      </div>
    </div>
  );
}

function NotesMode({ notes, agentFlags = [], onSelect, onEdit, onRemove, labelFor }) {
  return (
    <div className="decomp-body">
      {agentFlags.length ? (
        <div className="agent-flag-group">
          <div className="dc-section-head">
            <span className="num">AGENT</span>
            <span className="title">Flagged this answer</span>
            <span className="count">{agentFlags.length}</span>
          </div>
          {agentFlags.map((sid) => {
            const l = labelFor ? labelFor(sid) : { marker: "", title: sid };
            return (
              <button key={sid} type="button" className="agent-flag-row" onClick={() => onSelect(sid)}>
                <Icon name="sparkle" size={11} />
                {l.marker ? <span className="mono agent-flag-marker">{l.marker}</span> : null}
                <span className="agent-flag-title">{l.title}</span>
              </button>
            );
          })}
        </div>
      ) : null}

      <div className="dc-section-head">
        <span className="num">NOTES</span>
        <span className="title">Highlights &amp; notes</span>
        <span className="count">{notes.length} note{notes.length === 1 ? "" : "s"}</span>
      </div>

      {notes.length === 0 ? (
        <div className="notes-empty">
          <Icon name="doc" size={22} strokeWidth={1.25} />
          <p>No notes on this bill yet.</p>
          <p className="hint">Select any passage in the Text panel to highlight it and attach a note.</p>
        </div>
      ) : (
        notes.map((n) => (
          <NoteCard key={n.id} note={n} onSelect={onSelect} onEdit={onEdit} onRemove={onRemove} />
        ))
      )}
    </div>
  );
}

// ── Find in this bill (agent-driven decomposition) ───────────────────
// The researcher states an intent; the agent locates the relevant
// VERBATIM sections (it reads them) and they get flagged in the Text
// panel. This is the dynamic counterpart to the fixed Structure outline:
// "show me the enforcement provisions", "where does this touch privacy".
function FindBar({ findState, onFind, onClearFind, onSelect, labelFor }) {
  const [q, setQ] = useState("");
  const loading = !!(findState && findState.loading);
  const submit = () => { const v = q.trim(); if (v && !loading) onFind(v); };
  const located = (findState && findState.flags) || [];
  return (
    <div className="find-bar">
      <div className="find-input-row">
        <Icon name="search" size={14} className="find-icon" />
        <input
          className="find-input"
          placeholder="Find provisions in this bill…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
          disabled={loading}
        />
        <button type="button" className="find-go" onClick={submit} disabled={loading || !q.trim()}>
          {loading ? "…" : "Find"}
        </button>
      </div>

      {!findState ? (
        <p className="find-hint">
          Tell the agent what you&rsquo;re looking for — it locates the relevant
          verbatim sections and highlights them. It never rewrites the law.
        </p>
      ) : loading ? (
        <div className="find-status"><span className="spinner-sm" /> locating sections for &ldquo;{findState.intent}&rdquo;…</div>
      ) : findState.error ? (
        <div className="find-error">{findState.error}</div>
      ) : (
        <div className="find-result">
          <div className="find-result-head">
            <span>{located.length} section{located.length === 1 ? "" : "s"} located for &ldquo;{findState.intent}&rdquo;</span>
            <button type="button" className="find-clear" onClick={onClearFind} aria-label="Clear search">
              <Icon name="x" size={12} />
            </button>
          </div>
          {located.map((sid) => {
            const l = labelFor ? labelFor(sid) : { marker: "", title: sid };
            return (
              <button key={sid} type="button" className="find-hit" onClick={() => onSelect(sid)}>
                {l.marker ? <span className="find-hit-marker mono">{l.marker}</span> : null}
                <span className="find-hit-title">{l.title}</span>
              </button>
            );
          })}
          {findState.answer ? <p className="find-answer">{findState.answer}</p> : null}
        </div>
      )}
    </div>
  );
}

// ── Decomp panel container ───────────────────────────────────────────
function DecompPanel({ bill, mode, setMode, activeAnchor, onSelect,
                       annotations = [], onEditAnnotation, onRemoveAnnotation,
                       agentFlags = [], findState, onFind, onClearFind }) {
  const scrollRef = useRef(null);

  const counts = {
    structure:  bill.structure?.sections?.length ?? 0,
    definition: bill.definitions?.length ?? 0,
    amendment: bill.amendments?.length ?? 0,
    citation:   bill.citations?.reduce((n, g) => n + g.items.length, 0) ?? 0,
    notes:      annotations.length,
  };

  // Resolve a section id to a readable label (marker + title) from the
  // bill's own text tree, so flag/find rows aren't opaque ids.
  const labelFor = useMemo(() => {
    const m = new Map();
    (bill.text || []).forEach((sec) => {
      m.set(sec.id, { marker: sec.num || "", title: sec.title || "(section)" });
      (sec.blocks || []).forEach((b) => m.set(b.id, { marker: b.marker || "", title: b.heading || "(subsection)" }));
    });
    return (sid) => m.get(sid) || { marker: "", title: sid };
  }, [bill]);

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

      {onFind ? (
        <FindBar findState={findState} onFind={onFind} onClearFind={onClearFind} onSelect={onSelect} labelFor={labelFor} />
      ) : null}

      <div className="scroll" ref={scrollRef} style={{ minHeight: 0, flex: 1 }}>
        {mode === "structure"  && <StructureMode  key={bill.id} bill={bill} activeAnchor={activeAnchor} onSelect={onSelect} />}
        {mode === "definition" && <DefinitionMode bill={bill} activeAnchor={activeAnchor} onSelect={onSelect} />}
        {mode === "amendment" && <AmendmentMode bill={bill} activeAnchor={activeAnchor} onSelect={onSelect} />}
        {mode === "citation"   && <CitationMode   bill={bill} activeAnchor={activeAnchor} onSelect={onSelect} />}
        {mode === "notes"      && <NotesMode notes={annotations} agentFlags={agentFlags} onSelect={onSelect} onEdit={onEditAnnotation} onRemove={onRemoveAnnotation} labelFor={labelFor} />}
      </div>
    </div>
  );
}

window.DecompPanel = DecompPanel;
