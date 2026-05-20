/* global React, Icon */
// Polilabs — Center Text panel. Renders the bill section-by-section
// in a literary, statutory style. Exposes anchor IDs so the Decomp
// panel can sync-highlight matching ranges.

const { useEffect, useRef } = React;

function renderHtml(html) {
  return { __html: html };
}

function TextPanel({ bill, activeAnchor, onAnchorClick, onScrollEnd }) {
  const scrollRef = useRef(null);

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
          <div style={{ marginBottom: 28, paddingBottom: 18, borderBottom: "1px solid var(--rule-faint)" }}>
            <div style={{
              fontFamily: "var(--font-mono)", fontSize: 11,
              color: "var(--ink-4)", letterSpacing: "0.06em", textTransform: "uppercase",
              marginBottom: 8
            }}>
              {bill.congress}th Congress · 2d Session · {bill.bill_id}
            </div>
            <div style={{
              fontFamily: "var(--font-serif)", fontSize: 14, lineHeight: 1.7,
              color: "var(--ink-2)", textAlign: "center",
              maxWidth: 580, margin: "0 auto",
              fontVariant: "small-caps"
            }}>
              A bill
            </div>
            <p style={{
              fontFamily: "var(--font-serif)", fontSize: 15, lineHeight: 1.7,
              color: "var(--ink)", textAlign: "center",
              maxWidth: 580, margin: "8px auto 0",
              fontStyle: "italic"
            }}>
              {bill.summary}
            </p>
            <div style={{
              textAlign: "center", marginTop: 16,
              fontFamily: "var(--font-mono)", fontSize: 11,
              color: "var(--ink-4)", letterSpacing: "0.06em"
            }}>
              Be it enacted by the Senate and House of Representatives of the<br />
              United States of America in Congress assembled,
            </div>
          </div>

          {bill.text.map((sec) => (
            <section key={sec.id} data-anchor={sec.id} id={"text-" + sec.id}>
              <div className="section-num">{sec.num}</div>
              <h2>{sec.title}</h2>
              {sec.intro ? <p style={{ marginBottom: 12 }}>{sec.intro}</p> : null}
              {sec.paras.map((p) => (
                <div key={p.id} className="subsec" data-anchor={p.id}>
                  <span className="marker">{p.marker}</span>
                  <div className="body">
                    <p dangerouslySetInnerHTML={renderHtml(p.html)} />
                    {p.children?.map((c, ci) => (
                      <div className="subsec" key={ci} style={{ marginTop: 4 }}>
                        <span className="marker">{c.marker}</span>
                        <div className="body">
                          <p dangerouslySetInnerHTML={renderHtml(c.html)} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
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
