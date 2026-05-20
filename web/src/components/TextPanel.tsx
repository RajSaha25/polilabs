import { useEffect, useRef } from "react";
import { useAppStore } from "../store/useAppStore";
import type { RankedBill, SectionNode } from "../api/types";

/** One top-level section. Its `text` is text_full — already the
 *  complete verbatim text of the section and all its subsections — so
 *  we render it as a single block and do not recurse. The
 *  data-section-id anchors it for click-to-scroll from the outline. */
function TopSection({ node }: { node: SectionNode }) {
  return (
    <section
      data-section-id={node.section_id}
      className="mb-7 scroll-mt-4"
    >
      {node.heading && (
        <h3 className="mb-1 font-sans text-sm font-semibold tracking-tight text-ink">
          {node.heading}
        </h3>
      )}
      {node.canonical_citation && (
        <div className="mb-2 font-mono text-xs text-ink-faint">
          {node.canonical_citation}
        </div>
      )}
      {node.text && (
        <p className="whitespace-pre-wrap font-serif text-base leading-relaxed text-ink">
          {node.text}
        </p>
      )}
    </section>
  );
}

/** The center pane: the bill's verbatim text, set in serif so it reads
 *  as the source document rather than app content (web/DESIGN.md).
 *  Listens for scroll requests from the structure outline. */
export function TextPanel({ bill }: { bill: RankedBill }) {
  const entry = useAppStore((s) => s.billData[bill.bill_id]);
  const scrollRequest = useAppStore((s) => s.scrollRequest);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!scrollRequest || scrollRequest.billId !== bill.bill_id) return;
    const container = scrollRef.current;
    if (!container) return;
    const target = container.querySelector(
      `[data-section-id="${CSS.escape(scrollRequest.sectionId)}"]`,
    );
    target?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [scrollRequest, bill.bill_id]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <div className="border-b border-line px-5 py-3">
        <div className="text-xs font-medium tracking-wide text-ink-faint">
          TEXT
        </div>
        <div className="mt-0.5 truncate text-sm text-ink">
          {bill.short_title || bill.title || bill.bill_id}
        </div>
      </div>
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-5 py-5">
        {(!entry || entry.status === "loading") && (
          <p className="text-sm text-ink-faint">Loading bill text…</p>
        )}
        {entry?.status === "error" && (
          <p className="text-sm text-ink-faint">
            Couldn't load this bill — {entry.message}
          </p>
        )}
        {entry?.status === "ready" && (
          // ~70ch measure — legal text must never run full-bleed.
          <div className="max-w-[70ch]">
            {entry.tree.sections.map((s) => (
              <TopSection key={s.section_id} node={s} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
