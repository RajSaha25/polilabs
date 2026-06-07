/* global React, Icon */
// Polilabs — "All notes" modal. Every highlight + note the signed-in
// researcher has, across all bills, grouped by bill. Clicking a note
// jumps to that bill and scrolls to where the note lives — app.jsx wires
// that navigation through onSelect. Data comes from
// PolilabsAnnotations.listAll() (GET /api/annotations with no bill_id).

const { useMemo } = React;

// Match the in-text highlight palette so a note's dot reads as the same
// colour the user picked in the bill.
const NOTE_DOT = {
  yellow: "rgba(250, 204, 21, 0.6)",
  green: "rgba(52, 211, 153, 0.6)",
  pink: "rgba(244, 114, 182, 0.6)",
  blue: "rgba(96, 165, 250, 0.6)",
};

function AllNotesPanel({ data, onClose, onSelect }) {
  const pretty = (id) =>
    (window.PolilabsBackend && window.PolilabsBackend.prettyBillId
      ? window.PolilabsBackend.prettyBillId(id)
      : id) || id;

  // Group annotations by bill, preserving the backend's most-recent-first
  // order. A Map keeps first-seen insertion order, so the bill holding the
  // newest note floats to the top.
  const groups = useMemo(() => {
    const m = new Map();
    (data.items || []).forEach((a) => {
      if (!m.has(a.bill_id)) m.set(a.bill_id, []);
      m.get(a.bill_id).push(a);
    });
    return [...m.entries()];
  }, [data.items]);

  const total = (data.items || []).length;

  return (
    <div className="modal-scrim" onMouseDown={onClose}>
      <div className="modal notes-modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <h2>Your notes</h2>
            <p className="modal-sub">
              Every highlight and note you&rsquo;ve made, across all bills. Click one to jump to it.
            </p>
          </div>
          <button className="modal-x" type="button" aria-label="Close" onClick={onClose}>
            <Icon name="x" size={16} />
          </button>
        </div>

        <div className="modal-body notes-body">
          {data.loading ? (
            <div className="notes-empty"><span className="spinner" /> Loading your notes…</div>
          ) : data.error ? (
            <div className="notes-empty notes-error">Couldn&rsquo;t load your notes: {data.error}</div>
          ) : total === 0 ? (
            <div className="notes-empty">
              No notes yet. Open a bill, select any passage to highlight it, and add a
              note — everything you mark collects here.
            </div>
          ) : (
            <React.Fragment>
              <div className="notes-summary mono">{total} note{total === 1 ? "" : "s"} across {groups.length} bill{groups.length === 1 ? "" : "s"}</div>
              {groups.map(([billId, notes]) => (
                <div key={billId} className="notes-group">
                  <div className="notes-group-head">
                    <span className="notes-bill mono">{pretty(billId)}</span>
                    <span className="notes-count">{notes.length}</span>
                  </div>
                  {notes.map((n) => (
                    <button
                      key={n.id}
                      type="button"
                      className="note-item"
                      onClick={() => onSelect(n)}
                      title="Jump to this passage"
                    >
                      <span className="note-dot" style={{ background: NOTE_DOT[n.color] || NOTE_DOT.yellow }} />
                      <span className="note-text">
                        {n.quote ? <span className="note-quote">&ldquo;{n.quote}&rdquo;</span> : null}
                        {n.body ? <span className="note-body">{n.body}</span> : null}
                        {!n.quote && !n.body ? <span className="note-quote note-muted">(highlight)</span> : null}
                      </span>
                      <Icon name="arrow-right" size={13} className="note-go i" />
                    </button>
                  ))}
                </div>
              ))}
            </React.Fragment>
          )}
        </div>
      </div>
    </div>
  );
}

window.AllNotesPanel = AllNotesPanel;
