/* global React, Icon */
// Polilabs — Center Text panel. Renders the bill section-by-section
// in a literary, statutory style. Exposes anchor IDs so the Decomp
// panel can sync-highlight matching ranges, and lets a researcher
// select statute text to attach a private highlight + note.

const { useEffect, useRef, useState } = React;

const NOTE_COLORS = ["yellow", "green", "blue", "pink"];

function renderHtml(html) {
  return { __html: html };
}

// Renders a node's verbatim statute text — the node's own text plus its
// depth-indented subsections. Shared by the Text panel and Definition
// cards so both format statute text identically. `annotated` (optional)
// is a Map anchor -> { notes: [user annotations], agent: bool }; a block
// carrying a user note gets a coloured wash + quote flag, and one the
// agent pointed at gets a dashed accent + sparkle flag (transient, this
// answer only).
function StatuteBody({ leafHtml, blocks, annotated }) {
  return (
    <React.Fragment>
      {leafHtml ? (
        <div className="subsec">
          <span className="marker" />
          <div className="body">
            <p dangerouslySetInnerHTML={renderHtml(leafHtml)} />
          </div>
        </div>
      ) : null}
      {(blocks || []).map((b) => {
        const entry = annotated && annotated.get ? annotated.get(b.id) : null;
        const notes = entry ? entry.notes : null;
        const hasNote = notes && notes.length;
        const agent = !!(entry && entry.agent);
        const color = hasNote ? notes[notes.length - 1].color : null;
        return (
        <div
          key={b.id}
          className={"subsec"
            + (hasNote ? " has-note hl-" + (color || "yellow") : "")
            + (agent ? " agent-flag" : "")}
          data-anchor={b.id}
          style={{ marginLeft: b.depth * 22 }}
        >
          {agent ? (
            <span className="agent-flag-mark" title="The agent referenced this section" aria-hidden="true">
              <Icon name="sparkle" size={11} />
            </span>
          ) : null}
          {hasNote ? (
            <span className="note-flag" title={notes.length + " note" + (notes.length === 1 ? "" : "s")} aria-hidden="true">
              <Icon name="quote" size={11} />
            </span>
          ) : null}
          <span className="marker">{b.marker}</span>
          <div className="body">
            {b.heading ? (
              <p style={{ fontWeight: 600, color: "var(--ink)", marginBottom: b.html ? 4 : 0 }}>
                {b.heading}
              </p>
            ) : null}
            {b.html ? <p dangerouslySetInnerHTML={renderHtml(b.html)} /> : null}
          </div>
        </div>
        );
      })}
    </React.Fragment>
  );
}
window.StatuteBody = StatuteBody;

// ── selection → note composer ─────────────────────────────────────────
// A two-step affordance: selecting statute text raises a "Add note" pill;
// clicking it opens an inline composer. Two steps so an ordinary
// copy-selection doesn't immediately hijack the screen with a form.
function NoteComposer({ x, y, onSave, onCancel }) {
  const [body, setBody] = useState("");
  const [color, setColor] = useState("yellow");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const ref = useRef(null);
  useEffect(() => {
    const t = setTimeout(() => ref.current && ref.current.focus(), 0);
    return () => clearTimeout(t);
  }, []);
  const left = Math.max(12, Math.min(x, window.innerWidth - 320));

  // Save on Enter. On success the parent unmounts this composer; on
  // failure we surface the error and KEEP the text so nothing is lost.
  const submit = () => {
    if (saving) return;
    setSaving(true);
    setError("");
    Promise.resolve(onSave(body, color)).catch((e) => {
      setError((e && e.message) ? e.message : "Couldn't save the note. Please retry.");
      setSaving(false);
    });
  };

  return (
    <div className="note-composer" style={{ top: y + 8, left }} onMouseDown={(e) => e.stopPropagation()}>
      <textarea
        ref={ref}
        className="note-input"
        placeholder="Add a note…  (Enter to save · ⇧Enter for a new line)"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
          else if (e.key === "Escape") onCancel();
        }}
        rows={3}
      />
      {error ? <div className="note-error">{error}</div> : null}
      <div className="note-composer-foot">
        <div className="note-swatches">
          {NOTE_COLORS.map((c) => (
            <button
              key={c}
              type="button"
              className={"swatch hl-" + c + (color === c ? " on" : "")}
              aria-label={"Highlight " + c}
              onClick={() => setColor(c)}
            />
          ))}
        </div>
        <div className="note-actions">
          <button type="button" className="note-btn ghost" onClick={onCancel}>Cancel</button>
          <button type="button" className="note-btn primary" onClick={submit} disabled={saving}>
            {saving ? "saving…" : "Save note"}
          </button>
        </div>
      </div>
    </div>
  );
}
window.NoteComposer = NoteComposer;

// ── note popover — view / edit / delete an existing note in place ──────
// Notes are permanent: clicking a highlighted passage's flag reopens it.
function NotePopRow({ note, onEdit, onRemove, onClose }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(note.body || "");
  return (
    <div className={"note-pop-row hl-" + (note.color || "yellow")}>
      {note.quote ? (
        <div className="note-pop-quote">&ldquo;{note.quote.length > 160 ? note.quote.slice(0, 160) + "…" : note.quote}&rdquo;</div>
      ) : null}
      {editing ? (
        <textarea
          className="note-input"
          value={draft}
          autoFocus
          rows={2}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); Promise.resolve(onEdit(note.id, { body: draft })).then(() => setEditing(false)); }
            else if (e.key === "Escape") { setEditing(false); setDraft(note.body || ""); }
          }}
        />
      ) : (
        <div className="note-pop-body" onClick={() => setEditing(true)} title="Click to edit">
          {note.body ? note.body : <span className="note-empty">No text yet — click to add.</span>}
        </div>
      )}
      <div className="note-pop-foot">
        <button type="button" className="note-pop-del" onClick={() => { Promise.resolve(onRemove(note.id)).then(onClose); }}>
          <Icon name="x" size={11} /> delete
        </button>
      </div>
    </div>
  );
}

function NotePopover({ x, y, notes, onEdit, onRemove, onClose }) {
  const left = Math.max(12, Math.min(x, window.innerWidth - 320));
  return (
    <div className="note-popover" style={{ top: y + 6, left }} onMouseDown={(e) => e.stopPropagation()}>
      <div className="note-pop-head">
        <span>Your note{notes.length > 1 ? "s" : ""}</span>
        <button type="button" className="modal-x" onClick={onClose} aria-label="Close"><Icon name="x" size={13} /></button>
      </div>
      {notes.map((n) => <NotePopRow key={n.id} note={n} onEdit={onEdit} onRemove={onRemove} onClose={onClose} />)}
    </div>
  );
}
window.NotePopover = NotePopover;

// ── inline agent — double-click the bill text to ask, scoped to THIS
// bill. A translucent box that streams the answer and lets you jump to
// the sections the agent grounded it in. ───────────────────────────────
function InlineAsk({ x, y, findState, onAsk, onJump, onClose, labelFor }) {
  const [q, setQ] = useState("");
  const ref = useRef(null);
  useEffect(() => { const t = setTimeout(() => ref.current && ref.current.focus(), 0); return () => clearTimeout(t); }, []);
  const loading = !!(findState && findState.loading);
  const submit = () => { const v = q.trim(); if (v && !loading) onAsk(v); };
  const left = Math.max(12, Math.min(x, window.innerWidth - 400));
  const top = Math.max(70, Math.min(y, window.innerHeight - 280));
  const flags = (findState && findState.flags) || [];
  return (
    <div className="inline-ask" style={{ top, left }} onMouseDown={(e) => e.stopPropagation()}>
      <div className="inline-ask-head">
        <span className="inline-ask-title"><Icon name="sparkle" size={12} /> Ask about this bill</span>
        <button type="button" className="modal-x" onClick={onClose} aria-label="Close"><Icon name="x" size={13} /></button>
      </div>
      <div className="inline-ask-inputrow">
        <input
          ref={ref}
          className="inline-ask-input"
          placeholder="e.g. what does this bill spend on AI?"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); else if (e.key === "Escape") onClose(); }}
          disabled={loading}
        />
        <button type="button" className="inline-ask-go" onClick={submit} disabled={loading || !q.trim()}>
          {loading ? "…" : "Ask"}
        </button>
      </div>
      {findState ? (
        <div className="inline-ask-body">
          {findState.error ? <div className="find-error">{findState.error}</div> : null}
          {findState.answer ? (
            <div className="inline-ask-answer">{findState.answer}{loading ? <span className="ask-caret">▍</span> : null}</div>
          ) : loading ? (
            <div className="find-status"><span className="spinner-sm" /> reading the bill…</div>
          ) : null}
          {flags.length ? (
            <div className="inline-ask-hits">
              {flags.map((sid) => {
                const l = labelFor ? labelFor(sid) : { marker: "", title: "section" };
                return (
                  <button key={sid} type="button" className="inline-ask-hit" onClick={() => onJump(sid)}>
                    <Icon name="sparkle" size={10} />
                    {l.marker ? <span className="mono">{l.marker}</span> : null}
                    <span className="inline-ask-hit-title">{l.title}</span>
                  </button>
                );
              })}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
window.InlineAsk = InlineAsk;

function TextPanel({ bill, activeAnchor, onAnchorClick, annotations = [], onAddAnnotation,
                     onEditAnnotation, onRemoveAnnotation, agentFlags = [], findState, onAsk, onClearAsk }) {
  const scrollRef = useRef(null);
  // pendingSel = the "Add note" pill awaiting a click; composer = the
  // open form. noteView = an existing note reopened from its flag.
  // askBox = the inline double-click agent chat. Each is positioned.
  const [pendingSel, setPendingSel] = useState(null);
  const [composer, setComposer] = useState(null);
  const [noteView, setNoteView] = useState(null);
  const [askBox, setAskBox] = useState(null);

  // Resolve a section id to a readable label from the bill's own tree.
  const labelFor = React.useMemo(() => {
    const m = new Map();
    (bill.text || []).forEach((sec) => {
      m.set(sec.id, { marker: sec.num || "", title: sec.title || "(section)" });
      (sec.blocks || []).forEach((b) => m.set(b.id, { marker: b.marker || "", title: b.heading || "(subsection)" }));
    });
    return (sid) => m.get(sid) || { marker: "", title: "section" };
  }, [bill]);

  // Index by anchored section id so a block finds its own marks:
  //   { notes: [user annotations], agent: bool (agent pointed here) }.
  const annotated = React.useMemo(() => {
    const m = new Map();
    const ensure = (k) => { if (!m.has(k)) m.set(k, { notes: [], agent: false }); return m.get(k); };
    (annotations || []).forEach((a) => ensure(a.section_id || "__bill__").notes.push(a));
    (agentFlags || []).forEach((sid) => { if (sid) ensure(sid).agent = true; });
    return m;
  }, [annotations, agentFlags]);

  // The agent-flagged anchors present in THIS bill, in document order, for
  // the "step through" control. Only ids that actually resolve to a block.
  const flagAnchors = React.useMemo(() => {
    if (!agentFlags || !agentFlags.length) return [];
    const ids = [];
    (bill.text || []).forEach((sec) => {
      const walk = (b) => { if (agentFlags.includes(b.id)) ids.push(b.id); };
      if (agentFlags.includes(sec.id)) ids.push(sec.id);
      (sec.blocks || []).forEach(walk);
    });
    return ids;
  }, [bill, agentFlags]);
  const [flagCursor, setFlagCursor] = useState(0);
  const stepFlags = () => {
    if (!flagAnchors.length) return;
    const i = flagCursor % flagAnchors.length;
    onAnchorClick?.(flagAnchors[i]);
    setFlagCursor(i + 1);
  };

  // Scroll active anchor into view when it changes
  useEffect(() => {
    if (!activeAnchor || !scrollRef.current) return;
    const el = scrollRef.current.querySelector(`[data-anchor="${activeAnchor}"]`);
    if (!el) return;
    // pulse-highlight
    el.classList.add("hl-target");
    // block: "start" lands the section's first line just below the
    // panel header, where reading naturally begins. block: "center"
    // (the previous value) parked the section mid-viewport, which
    // made clicks from the structure tree feel like they were
    // dropping the user "into the middle" of a section rather than
    // at its start.
    el.scrollIntoView({ block: "start", behavior: "smooth" });
    const t = setTimeout(() => el.classList.remove("hl-target"), 1200);
    return () => clearTimeout(t);
  }, [activeAnchor]);

  // Capture clicks on .anchor spans so we can fire onAnchorClick — but
  // only when there's no active text selection (a drag-select shouldn't
  // also count as a sync-highlight click).
  const handleClick = (e) => {
    // Click a note flag -> reopen that note (view / edit / delete).
    const flag = e.target.closest(".note-flag");
    if (flag) {
      const block = flag.closest("[data-anchor]");
      const anchor = block && block.getAttribute("data-anchor");
      const notes = ((annotated.get(anchor) || {}).notes) || [];
      if (notes.length) {
        const rect = flag.getBoundingClientRect();
        setNoteView({ anchor, notes, x: rect.right, y: rect.bottom });
        return;
      }
    }
    const a = e.target.closest("[data-anchor]");
    if (!a || !window.getSelection().isCollapsed) return;
    onAnchorClick?.(a.getAttribute("data-anchor"));
  };

  // Double-click the bill text -> open the inline agent, scoped to this
  // bill, near the cursor. Clears the word the browser auto-selected.
  const handleDoubleClick = (e) => {
    if (e.target.closest(".inline-ask, .note-popover, .note-composer")) return;
    const block = e.target.closest("[data-anchor]");
    const anchor = block ? block.getAttribute("data-anchor") : null;
    window.getSelection().removeAllRanges();
    setPendingSel(null);
    setComposer(null);
    setNoteView(null);
    onClearAsk?.();
    setAskBox({ anchor, x: e.clientX, y: e.clientY });
  };

  // On mouse-up, if statute text was selected inside this panel, raise
  // the "Add note" pill anchored to the nearest [data-anchor] block.
  const handleMouseUp = () => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) { setPendingSel(null); return; }
    const quote = sel.toString().trim();
    if (!quote) { setPendingSel(null); return; }
    let node = sel.anchorNode;
    let el = node && node.nodeType === 3 ? node.parentElement : node;
    if (!el || !scrollRef.current || !scrollRef.current.contains(el)) { setPendingSel(null); return; }
    const anchorEl = el.closest("[data-anchor]");
    const anchor = anchorEl ? anchorEl.getAttribute("data-anchor") : null;
    const rect = sel.getRangeAt(0).getBoundingClientRect();
    setComposer(null);
    setPendingSel({ anchor, quote: quote.slice(0, 2000), x: rect.left, y: rect.bottom });
  };

  const openComposer = () => {
    if (pendingSel) { setComposer(pendingSel); setPendingSel(null); }
  };

  // Returns the save promise. Close the composer + clear the selection
  // ONLY on success; on failure the promise rejects and NoteComposer keeps
  // the text + shows the error (no silent disappearance).
  const saveNote = (body, color) => {
    if (!composer) return Promise.resolve();
    return Promise.resolve(
      onAddAnnotation?.({ section_id: composer.anchor, quote: composer.quote, body, color }),
    ).then(() => {
      setComposer(null);
      window.getSelection().removeAllRanges();
    });
  };

  // A bare mousedown in the panel dismisses the pill/composer/note popover
  // — but NOT the inline ask box, so you can click around the bill to find
  // the sections it surfaced while the box stays open.
  const dismiss = () => { setPendingSel(null); setComposer(null); setNoteView(null); };

  return (
    <div className="panel-col text-col">
      <div className="panel-bar">
        <span className="panel-label">
          <span className="dot" />
          Text · verbatim
        </span>
        {flagAnchors.length ? (
          <button type="button" className="agent-flag-chip" onClick={stepFlags}
                  title="Step through the sections the agent referenced">
            <Icon name="sparkle" size={12} />
            agent flagged {flagAnchors.length}
          </button>
        ) : (
          <span className="mono" style={{
            fontSize: 11, color: "var(--ink-4)", letterSpacing: 0.04,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            minWidth: 0
          }}>
            {bill.introduced}
          </span>
        )}
      </div>

      <div
        className="scroll"
        ref={scrollRef}
        style={{ minHeight: 0, flex: 1 }}
        onClick={handleClick}
        onMouseUp={handleMouseUp}
        onMouseDown={dismiss}
        onDoubleClick={handleDoubleClick}
      >
        <article className="text-body">
          {/* Long title / preamble */}
          <div style={{ marginBottom: 40, paddingBottom: 28, borderBottom: "1px solid var(--rule-faint)" }}>
            <div style={{
              fontFamily: "var(--font-mono)", fontSize: 14,
              color: "var(--ink-3)", letterSpacing: "0.07em", textTransform: "uppercase",
              textAlign: "center", marginBottom: 18, fontWeight: 500
            }}>
              {bill.congress}th Congress · 2d Session · {bill.bill_id}
            </div>
            <div style={{
              fontFamily: "var(--font-serif)", fontSize: 36, lineHeight: 1.15,
              color: "var(--ink)", textAlign: "center",
              margin: "0 auto", fontWeight: 600,
              letterSpacing: "0.12em", textTransform: "uppercase"
            }}>
              A Bill
            </div>
            <p style={{
              fontFamily: "var(--font-serif)", fontSize: 19, lineHeight: 1.6,
              color: "var(--ink)", textAlign: "center",
              maxWidth: 600, margin: "16px auto 0",
              fontStyle: "italic"
            }}>
              {bill.summary}
            </p>
            <div style={{
              textAlign: "center", marginTop: 24,
              fontFamily: "var(--font-serif)", fontSize: 17, lineHeight: 1.6,
              color: "var(--ink-2)", fontStyle: "italic"
            }}>
              Be it enacted by the Senate and House of Representatives of the<br />
              United States of America in Congress assembled,
            </div>
          </div>

          {bill.text.map((sec) => {
            const e = annotated.get(sec.id);
            const sn = e ? e.notes : null;
            const cls = [
              sn && sn.length ? "has-note hl-" + sn[sn.length - 1].color : "",
              e && e.agent ? "agent-flag" : "",
            ].filter(Boolean).join(" ") || undefined;
            return (
              <section key={sec.id} data-anchor={sec.id} id={"text-" + sec.id} className={cls}>
                <h2>{sec.num ? sec.num + ": " : ""}{sec.title}</h2>
                <StatuteBody leafHtml={sec.leafHtml} blocks={sec.blocks} annotated={annotated} />
              </section>
            );
          })}

          <div style={{
            marginTop: 40, paddingTop: 18,
            borderTop: "1px solid var(--rule-faint)",
            fontFamily: "var(--font-mono)", fontSize: 11,
            color: "var(--ink-4)", letterSpacing: "0.04em",
            textAlign: "center"
          }}>
            END OF BILL · verbatim text from the polilabs corpus
          </div>
        </article>
      </div>

      {pendingSel ? (
        <button
          type="button"
          className="note-pill"
          style={{ top: pendingSel.y + 8, left: Math.max(12, Math.min(pendingSel.x, window.innerWidth - 130)) }}
          onMouseDown={(e) => { e.preventDefault(); e.stopPropagation(); }}
          onClick={openComposer}
        >
          <Icon name="quote" size={12} /> Add note
        </button>
      ) : null}

      {composer ? (
        <NoteComposer x={composer.x} y={composer.y} onSave={saveNote} onCancel={() => setComposer(null)} />
      ) : null}

      {noteView ? (
        <NotePopover
          x={noteView.x}
          y={noteView.y}
          notes={(annotated.get(noteView.anchor) || {}).notes || noteView.notes}
          onEdit={onEditAnnotation}
          onRemove={onRemoveAnnotation}
          onClose={() => setNoteView(null)}
        />
      ) : null}

      {askBox ? (
        <InlineAsk
          x={askBox.x}
          y={askBox.y}
          findState={findState}
          onAsk={onAsk}
          onJump={(sid) => onAnchorClick?.(sid)}
          onClose={() => { setAskBox(null); onClearAsk?.(); }}
          labelFor={labelFor}
        />
      ) : null}
    </div>
  );
}

window.TextPanel = TextPanel;
