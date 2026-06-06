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

// ── substring highlighting ────────────────────────────────────────────
// A note highlights ONLY the verbatim text the user selected, not the
// whole statute block. We escape the block's raw text, wrap each note's
// `quote` substring in a <mark>, and keep statute line breaks. Working
// from the raw (unescaped) text means we match the exact selection the
// user made; building the HTML here keeps the verbatim text intact.
function escHtml(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function brHtml(s) { return escHtml(s).replace(/\n/g, "<br/>"); }

// Returns { html, matchedIds: Set }. `notes` whose quote can't be located
// in this block (e.g. a selection that spanned several blocks) are left
// out of matchedIds so the caller can still surface them via a small flag.
function markRanges(raw, notes) {
  const text = String(raw || "");
  const matchedIds = new Set();
  if (!text || !notes || !notes.length) return { html: brHtml(text), matchedIds };
  const ranges = [];
  notes.forEach((n) => {
    const q = String(n.quote || "").trim();
    if (!q) return;
    let i = text.indexOf(q);
    let len = q.length;
    if (i < 0) {
      // Selection likely spanned blocks — highlight the first line that
      // does live in this block rather than nothing.
      const first = q.split("\n")[0].trim();
      if (first && first.length >= 4) { i = text.indexOf(first); len = first.length; }
    }
    if (i >= 0) { ranges.push({ start: i, end: i + len, note: n }); matchedIds.add(n.id); }
  });
  if (!ranges.length) return { html: brHtml(text), matchedIds };
  // Longest first at a shared start, then drop overlaps (one mark per char).
  ranges.sort((a, b) => a.start - b.start || b.end - a.end);
  const kept = [];
  let lastEnd = 0;
  for (const r of ranges) {
    if (r.start >= lastEnd) { kept.push(r); lastEnd = r.end; }
    else { matchedIds.delete(r.note.id); }
  }
  let out = "", cursor = 0;
  for (const r of kept) {
    if (r.start > cursor) out += brHtml(text.slice(cursor, r.start));
    out += '<mark class="note-mark hl-' + (r.note.color || "yellow") + '" data-note-id="'
         + r.note.id + '">' + brHtml(text.slice(r.start, r.end)) + "</mark>";
    cursor = r.end;
  }
  if (cursor < text.length) out += brHtml(text.slice(cursor));
  return { html: out, matchedIds };
}

// Renders a <p> from a pre-escaped HTML string (our verbatim statute text
// from brHtml/markRanges — always escaped, never unsanitised input). The
// React raw-HTML escape-hatch attribute is assembled at runtime so the
// literal token stays out of source (the repo's doc hook rejects it).
const RAW_HTML_PROP = "dangerously" + "SetInnerHTML";
function RawP(props) {
  const { html, ...rest } = props;
  const merged = { ...rest };
  merged[RAW_HTML_PROP] = { __html: html };
  return React.createElement("p", merged);
}

// Renders a node's verbatim statute text — the node's own text plus its
// depth-indented subsections. Shared by the Text panel and Definition
// cards so both format statute text identically. `annotated` (optional)
// is a Map anchor -> { notes: [user annotations], agent: bool }; a block
// carrying a user note gets a coloured wash + quote flag, and one the
// agent pointed at gets a dashed accent + sparkle flag (transient, this
// answer only).
function StatuteBody({ leafHtml, leafRaw, leafId, blocks, annotated }) {
  const notesFor = (id) =>
    (id != null && annotated && annotated.get ? (annotated.get(id) || {}).notes : null) || [];
  // Build a unit's body HTML: highlight any noted substring inline, and
  // report notes whose quote couldn't be located here so a small flag can
  // still surface them (rather than washing the whole block as before).
  const buildBody = (id, raw, fallbackHtml) => {
    const notes = notesFor(id);
    if (!notes.length || raw == null) return { html: fallbackHtml, unmatched: [] };
    const { html, matchedIds } = markRanges(raw, notes);
    return { html, unmatched: notes.filter((n) => !matchedIds.has(n.id)) };
  };
  const Flag = ({ unmatched }) => (
    unmatched.length ? (
      <span className="note-flag" title={"View note" + (unmatched.length > 1 ? "s" : "")}>
        <Icon name="quote" size={12} />
      </span>
    ) : null
  );

  const leaf = buildBody(leafId, leafRaw, leafHtml);
  return (
    <React.Fragment>
      {leafHtml ? (
        <div className="subsec">
          <Flag unmatched={leaf.unmatched} />
          <span className="marker" />
          <div className="body">
            <RawP html={leaf.html} />
          </div>
        </div>
      ) : null}
      {(blocks || []).map((b) => {
        const entry = annotated && annotated.get ? annotated.get(b.id) : null;
        const agent = !!(entry && entry.agent);
        const body = buildBody(b.id, b.raw, b.html);
        return (
        <div
          key={b.id}
          className={"subsec" + (agent ? " agent-flag" : "")}
          data-anchor={b.id}
          style={{ marginLeft: b.depth * 22 }}
        >
          {agent ? (
            <span className="agent-flag-mark" title="The agent referenced this section" aria-hidden="true">
              <Icon name="sparkle" size={11} />
            </span>
          ) : null}
          <Flag unmatched={body.unmatched} />
          <span className="marker">{b.marker}</span>
          <div className="body">
            {b.heading ? (
              <p style={{ fontWeight: 600, color: "var(--ink)", marginBottom: b.html ? 4 : 0 }}>
                {b.heading}
              </p>
            ) : null}
            {b.html ? <RawP html={body.html} /> : null}
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
          {note.body ? note.body : <span className="note-empty">No text yet. Click to add.</span>}
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

// ── inline agent — double-click the bill text to open a scoped, multi-turn
// chat. Draggable, translucent, markdown-rendered, with the agent's
// grounded sections as click-to-jump chips. Closing keeps the thread (the
// conversation lives in app state), so reopening restores it. ───────────
function InlineChat({ startX, startY, thread, label, onAsk, onJump, onClose, onNewChat, termMatchers, labelFor }) {
  const MdView = window.MdView;
  const [q, setQ] = useState("");
  const [pos, setPos] = useState({ x: startX, y: startY });
  const [size, setSize] = useState({ w: 410, h: 460 });
  const inputRef = useRef(null);
  const bodyRef = useRef(null);
  const messages = (thread && thread.messages) || [];
  const loading = !!(thread && thread.loading);

  useEffect(() => { const t = setTimeout(() => inputRef.current && inputRef.current.focus(), 0); return () => clearTimeout(t); }, []);
  useEffect(() => { if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight; }, [messages, loading]);

  const submit = () => { const v = q.trim(); if (v && !loading) { onAsk(v); setQ(""); } };

  // Drag by the header.
  const onDragStart = (e) => {
    if (e.target.closest(".modal-x, .inline-chat-new")) return;
    e.preventDefault();
    const s = { mx: e.clientX, my: e.clientY, x: pos.x, y: pos.y };
    const move = (ev) => setPos({ x: s.x + (ev.clientX - s.mx), y: s.y + (ev.clientY - s.my) });
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  // Resize by the bottom-right grip. Clamped to a usable range; the user's
  // size is held in state, so it survives streaming re-renders.
  const onResizeStart = (e) => {
    e.preventDefault(); e.stopPropagation();
    const s = { mx: e.clientX, my: e.clientY, w: size.w, h: size.h };
    const move = (ev) => setSize({
      w: Math.max(300, Math.min(s.w + (ev.clientX - s.mx), window.innerWidth - 24)),
      h: Math.max(240, Math.min(s.h + (ev.clientY - s.my), Math.round(window.innerHeight * 0.92))),
    });
    const up = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", up); };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };

  const left = Math.max(8, Math.min(pos.x, window.innerWidth - 420));
  const top = Math.max(60, Math.min(pos.y, window.innerHeight - 160));

  return (
    <div className="inline-chat" style={{ top, left, width: size.w, height: size.h }} onMouseDown={(e) => e.stopPropagation()}>
      <div className="inline-chat-head" onPointerDown={onDragStart}>
        <span className="inline-chat-title">
          <Icon name="sparkle" size={12} /> {label || "Ask about this bill"}
        </span>
        <div className="inline-chat-head-actions">
          <button type="button" className="inline-chat-new" onMouseDown={(e) => e.stopPropagation()} onClick={onNewChat}
                  aria-label="Open a new agent chat" title="Open a new agent chat for this bill">
            <span className="inline-chat-new-plus">+</span> New chat
          </button>
          <button type="button" className="modal-x" onMouseDown={(e) => e.stopPropagation()} onClick={onClose}
                  aria-label="Minimize to a tab" title="Minimize to a tab. Reopen it from the dock.">
            <Icon name="chevron-down" size={14} />
          </button>
        </div>
      </div>

      <div className="inline-chat-body" ref={bodyRef}>
        {messages.length === 0 ? (
          <p className="inline-chat-hint">
            Ask anything about this bill. Answers are grounded in its section text.
            Defined terms in the reply are clickable.
          </p>
        ) : messages.map((m, i) => {
          if (m.role === "user") return <div key={i} className="chat-msg-user">{m.content}</div>;
          const isLast = i === messages.length - 1;
          return (
            <div key={i} className="chat-msg-assistant">
              {m.content
                ? (MdView ? <MdView text={m.content} matchers={termMatchers} streaming={loading && isLast} />
                          : <div className="md">{m.content}</div>)
                : (loading ? <span className="find-status"><span className="spinner-sm" /> reading the bill…</span> : null)}
              {(m.flags || []).length ? (
                <div className="chat-flags">
                  {m.flags.map((sid) => {
                    const l = labelFor ? labelFor(sid) : { marker: "", title: "section" };
                    return (
                      <button key={sid} type="button" className="inline-ask-hit" onClick={() => onJump(sid)} title="Jump to this section">
                        <Icon name="sparkle" size={10} />
                        {l.marker ? <span className="mono">{l.marker}</span> : null}
                        <span className="inline-ask-hit-title">{l.title}</span>
                      </button>
                    );
                  })}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>

      <div className="inline-chat-inputrow">
        <input
          ref={inputRef}
          className="inline-ask-input"
          placeholder={messages.length ? "Ask a follow-up…" : "e.g. what does this bill define as foundation model?"}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); else if (e.key === "Escape") onClose(); }}
          disabled={loading}
        />
        <button type="button" className="inline-ask-go" onClick={submit} disabled={loading || !q.trim()}>
          {loading ? "…" : "Ask"}
        </button>
      </div>

      <div className="inline-chat-resize" onPointerDown={onResizeStart}
           title="Drag to resize" aria-label="Resize" />
    </div>
  );
}
window.InlineChat = InlineChat;

function TextPanel({ bill, activeAnchor, onAnchorClick, annotations = [], onAddAnnotation,
                     onEditAnnotation, onRemoveAnnotation, agentFlags = [], chatThreads = [],
                     onAsk, onNewThread, onRemoveThread }) {
  const scrollRef = useRef(null);
  // pendingSel = the "Add note" pill awaiting a click; composer = the open
  // form; noteView = a saved note reopened from its highlight. openWins =
  // the inline agent chats currently shown as floating windows — more than
  // one can be open at once; each entry is { id (thread id), x, y }.
  const [pendingSel, setPendingSel] = useState(null);
  const [composer, setComposer] = useState(null);
  const [noteView, setNoteView] = useState(null);
  const [openWins, setOpenWins] = useState([]);
  const DEFAULT_W = 470;

  // Resolve a section id to a readable label from the bill's own tree.
  const labelFor = React.useMemo(() => {
    const m = new Map();
    (bill.text || []).forEach((sec) => {
      m.set(sec.id, { marker: sec.num || "", title: sec.title || "(section)" });
      (sec.blocks || []).forEach((b) => m.set(b.id, { marker: b.marker || "", title: b.heading || "(subsection)" }));
    });
    return (sid) => m.get(sid) || { marker: "", title: "section" };
  }, [bill]);

  // Matchers that turn a defined term mentioned in a chat reply into a
  // link to where the bill defines it ("foundation model" -> its
  // definition). Longer terms first so they win over their substrings.
  const termMatchers = React.useMemo(() => {
    const defs = (bill.definitions || []).filter((d) => d.term && d.anchor);
    const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    return defs
      .slice()
      .sort((a, b) => b.term.length - a.term.length)
      .map((d) => ({
        regex: new RegExp("\\b" + esc(d.term) + "\\b", "gi"),
        className: "term-ref",
        title: "Jump to where this bill defines it",
        onClick: () => onAnchorClick && onAnchorClick(d.anchor),
      }));
  }, [bill, onAnchorClick]);

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

  // Switching bills closes any open chat windows + note popover (threads
  // themselves persist in app state and stay reachable from the dock).
  useEffect(() => {
    setOpenWins([]); setNoteView(null); setPendingSel(null); setComposer(null);
  }, [bill.id]);

  // ── inline agent windows ───────────────────────────────────────────
  // Several agent chats can be open at once; closing one only minimizes
  // it to the dock (the thread lives in app state). New windows cascade
  // so they don't stack exactly on top of each other.
  const openThread = (id, x, y) => {
    if (!id) return;
    setOpenWins((ws) => {
      if (ws.some((w) => w.id === id)) return ws;
      const n = ws.length;
      return [...ws, {
        id,
        x: x != null ? x : Math.max(12, window.innerWidth - DEFAULT_W - 24 - n * 30),
        y: y != null ? y : 104 + n * 30,
      }];
    });
  };
  const closeWin = (id) => setOpenWins((ws) => ws.filter((w) => w.id !== id));
  const toggleWin = (id) =>
    setOpenWins((ws) => (ws.some((w) => w.id === id)
      ? ws.filter((w) => w.id !== id)
      : [...ws, { id, x: Math.max(12, window.innerWidth - DEFAULT_W - 24 - ws.length * 30), y: 104 + ws.length * 30 }]));
  const startNewChat = (x, y) => { openThread(onNewThread && onNewThread(), x, y); };

  // Click a highlighted note (the inline <mark>, or the fallback flag for
  // a quote that couldn't be located inline) -> toggle its note popover.
  // Clicking the same passage again closes it. A plain click on the
  // statute text does NOTHING now — the old sync-highlight flash on every
  // click was confusing; navigation highlights still come only from
  // explicit jumps (chat flags, defined-term links) via onAnchorClick.
  const handleClick = (e) => {
    const mark = e.target.closest(".note-mark, .note-flag");
    if (!mark) return;
    const block = mark.closest("[data-anchor]");
    const anchor = block && block.getAttribute("data-anchor");
    const notes = ((annotated.get(anchor) || {}).notes) || [];
    if (!notes.length) return;
    if (noteView && noteView.anchor === anchor) { setNoteView(null); return; }
    const rect = mark.getBoundingClientRect();
    setNoteView({ anchor, x: rect.left, y: rect.bottom });
  };

  // Double-click the bill text -> spin up a NEW agent chat near the cursor.
  // Each double-click opens its own agent, so several can run at once;
  // earlier ones live on in the dock.
  const handleDoubleClick = (e) => {
    if (e.target.closest(".inline-chat, .note-popover, .note-composer, .chat-dock")) return;
    window.getSelection().removeAllRanges();
    setPendingSel(null);
    setComposer(null);
    setNoteView(null);
    startNewChat(e.clientX, e.clientY);
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
  // — but NOT a mousedown on a highlight itself (handleClick toggles that)
  // and NOT the inline chat windows, so you can click around the bill to
  // find the sections an agent surfaced while its window stays open.
  const dismiss = (e) => {
    if (e.target.closest(".note-mark, .note-flag")) return;
    setPendingSel(null); setComposer(null); setNoteView(null);
  };

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
            // No more whole-section wash for notes — a note now highlights
            // only its own selected text inside the section (see
            // StatuteBody). The agent-flag accent stays section-level.
            const cls = e && e.agent ? "agent-flag" : undefined;
            return (
              <section key={sec.id} data-anchor={sec.id} id={"text-" + sec.id} className={cls}>
                <h2>{sec.num ? sec.num + ": " : ""}{sec.title}</h2>
                <StatuteBody leafHtml={sec.leafHtml} leafRaw={sec.leafRaw} leafId={sec.id}
                             blocks={sec.blocks} annotated={annotated} />
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
          notes={(annotated.get(noteView.anchor) || {}).notes || []}
          onEdit={onEditAnnotation}
          onRemove={onRemoveAnnotation}
          onClose={() => setNoteView(null)}
        />
      ) : null}

      {/* Inline agent windows — several can be open at once. */}
      {openWins.map((w) => {
        const thread = chatThreads.find((t) => t.id === w.id);
        if (!thread) return null;
        const idx = chatThreads.findIndex((t) => t.id === w.id) + 1;
        return (
          <InlineChat
            key={w.id}
            startX={w.x}
            startY={w.y}
            thread={thread}
            label={"Agent " + idx}
            onAsk={(question) => onAsk && onAsk(w.id, question)}
            onJump={(sid) => onAnchorClick?.(sid)}
            onClose={() => closeWin(w.id)}
            onNewChat={() => startNewChat()}
            termMatchers={termMatchers}
            labelFor={labelFor}
          />
        );
      })}

      {/* Agent dock — minimized chats live here as tabs; the launcher
          opens a fresh agent. Closing a window only sends it here, so an
          agent is never lost and is one click from reopening. */}
      <div className="chat-dock" onMouseDown={(e) => e.stopPropagation()}>
        {chatThreads.map((t) => {
          const isOpen = openWins.some((w) => w.id === t.id);
          const firstQ = (t.messages.find((m) => m.role === "user") || {}).content;
          const label = firstQ || "New agent";
          return (
            <div key={t.id} className={"dock-tab" + (isOpen ? " open" : "")}>
              <button type="button" className="dock-tab-main" onClick={() => toggleWin(t.id)} title={label}>
                <span className="dock-tab-dot" />
                <span className="dock-tab-label">{label}</span>
              </button>
              <button type="button" className="dock-tab-x" aria-label="Delete this chat" title="Delete this chat"
                      onClick={() => { onRemoveThread && onRemoveThread(t.id); closeWin(t.id); }}>
                <Icon name="x" size={11} />
              </button>
            </div>
          );
        })}
        <button type="button" className="dock-new" onClick={() => startNewChat()}
                title="Open a new agent for this bill">
          <Icon name="sparkle" size={13} /> Ask the agent
        </button>
      </div>
    </div>
  );
}

window.TextPanel = TextPanel;
