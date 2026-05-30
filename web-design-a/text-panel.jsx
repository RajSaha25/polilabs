/* global React, Icon */
// Polilabs — Center Text panel. Renders the bill section-by-section
// in a literary, statutory style. Exposes anchor IDs so the Decomp
// panel can sync-highlight matching ranges.

const { useEffect, useRef } = React;

function renderHtml(html) {
  return { __html: html };
}

// Renders a node's verbatim statute text — the node's own text plus its
// depth-indented subsections. Shared by the Text panel and Definition
// cards so both format statute text identically.
function StatuteBody({ leafHtml, blocks }) {
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
      {(blocks || []).map((b) => (
        <div
          key={b.id}
          className="subsec"
          data-anchor={b.id}
          style={{ marginLeft: b.depth * 22 }}
        >
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
      ))}
    </React.Fragment>
  );
}
window.StatuteBody = StatuteBody;

function TextPanel({ bill, activeAnchor, onAnchorClick, onScrollEnd }) {
  const scrollRef = useRef(null);

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

  // Capture clicks on .anchor spans so we can fire onAnchorClick
  const handleClick = (e) => {
    const a = e.target.closest("[data-anchor]");
    if (!a) return;
    const anchor = a.getAttribute("data-anchor");
    onAnchorClick?.(anchor);
  };

  return (
    <div className="panel-col text-col">
      <div className="panel-bar">
        <span className="panel-label">
          <span className="dot" />
          Text · verbatim
        </span>
        <span className="mono" style={{
          fontSize: 11, color: "var(--ink-4)", letterSpacing: 0.04,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          minWidth: 0
        }}>
          {bill.introduced}
        </span>
      </div>

      <div className="scroll" ref={scrollRef} style={{ minHeight: 0, flex: 1 }} onClick={handleClick}>
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

          {bill.text.map((sec) => (
            <section key={sec.id} data-anchor={sec.id} id={"text-" + sec.id}>
              <h2>{sec.num ? sec.num + ": " : ""}{sec.title}</h2>
              <StatuteBody leafHtml={sec.leafHtml} blocks={sec.blocks} />
            </section>
          ))}

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
    </div>
  );
}

window.TextPanel = TextPanel;
