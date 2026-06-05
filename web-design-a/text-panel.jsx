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
  const ref = useRef(null);
  useEffect(() => {
    const t = setTimeout(() => ref.current && ref.current.focus(), 0);
    return () => clearTimeout(t);
  }, []);
  const left = Math.max(12, Math.min(x, window.innerWidth - 320));
  return (
    <div className="note-composer" style={{ top: y + 8, left }} onMouseDown={(e) => e.stopPropagation()}>
      <textarea
        ref={ref}
        className="note-input"
        placeholder="Add a note to this passage…  (⌘↵ to save)"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); onSave(body, color); }
          if (e.key === "Escape") onCancel();
        }}
        rows={3}
      />
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
          <button type="button" className="note-btn primary" onClick={() => onSave(body, color)}>Save note</button>
        </div>
      </div>
    </div>
  );
}
window.NoteComposer = NoteComposer;

function TextPanel({ bill, activeAnchor, onAnchorClick, annotations = [], onAddAnnotation, agentFlags = [] }) {
  const scrollRef = useRef(null);
  // pendingSel = the "Add note" pill awaiting a click; composer = the
  // open form. Each is { anchor, quote, x, y } or null.
  const [pendingSel, setPendingSel] = useState(null);
  const [composer, setComposer] = useState(null);

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
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    const t = setTimeout(() => el.classList.remove("hl-target"), 1200);
    return () => clearTimeout(t);
  }, [activeAnchor]);

  // Capture clicks on .anchor spans so we can fire onAnchorClick — but
  // only when there's no active text selection (a drag-select shouldn't
  // also count as a sync-highlight click).
  const handleClick = (e) => {
    const a = e.target.closest("[data-anchor]");
    if (!a || !window.getSelection().isCollapsed) return;
    onAnchorClick?.(a.getAttribute("data-anchor"));
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

  const saveNote = (body, color) => {
    if (!composer) return;
    Promise.resolve(
      onAddAnnotation?.({ section_id: composer.anchor, quote: composer.quote, body, color }),
    ).finally(() => {
      setComposer(null);
      window.getSelection().removeAllRanges();
    });
  };

  // A bare mousedown anywhere in the panel dismisses the pill/composer.
  const dismiss = () => { setPendingSel(null); setComposer(null); };

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
    </div>
  );
}

window.TextPanel = TextPanel;
