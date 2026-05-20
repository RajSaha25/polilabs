import { useEffect, useMemo, useRef } from "react";
import { useAppStore } from "../store/useAppStore";
import type { RankedBill, SectionNode } from "../api/types";
import { useEffectiveMode } from "../decomp/selectMode";
import {
  buildSectionRootIndex,
  buildSegments,
  findSpan,
  formatStructure,
  type LocatedSpan,
  type TextSegment,
} from "../decomp/highlight";
import {
  amendmentAnchors,
  definitionAnchors,
  type DecompAnchor,
} from "../decomp/anchors";
import { HighlightSpan } from "./HighlightSpan";

/** One top-level section. Its `text` is text_full — already the
 *  complete verbatim text of the section and all its subsections — so
 *  we render it as a single block and do not recurse. The text is split
 *  into plain and marked segments: every Decomp-anchored span becomes a
 *  clickable <HighlightSpan>. data-section-id anchors it for
 *  click-to-scroll from the outline. */
function TopSection({
  node,
  segments,
  activeItemId,
  onActivateMark,
}: {
  node: SectionNode;
  segments: TextSegment[];
  activeItemId: string | null;
  onActivateMark: (itemId: string) => void;
}) {
  return (
    <section data-section-id={node.section_id} className="mb-7 scroll-mt-4">
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
        <div className="whitespace-pre-wrap font-serif text-base leading-relaxed text-ink">
          {segments.map((seg, i) => {
            if (seg.kind === "break") {
              return <span key={i} aria-hidden className="block h-2.5" />;
            }
            if (seg.kind === "plain") {
              return <span key={i}>{seg.text}</span>;
            }
            return (
              <HighlightSpan
                key={i}
                itemId={seg.itemId}
                active={seg.itemId === activeItemId}
                onActivate={onActivateMark}
              >
                {seg.text}
              </HighlightSpan>
            );
          })}
        </div>
      )}
    </section>
  );
}

/** The center pane: the bill's verbatim text, set in serif so it reads
 *  as the source document rather than app content (web/DESIGN.md).
 *
 *  It carries both halves of the synced highlight: every Decomp-anchored
 *  span is marked, the active one in highlighter-yellow; clicking a span
 *  drives the Decomp panel. It also listens for scroll requests from the
 *  structure outline. */
export function TextPanel({ bill }: { bill: RankedBill }) {
  const billId = bill.bill_id;
  const entry = useAppStore((s) => s.billData[billId]);
  const scrollRequest = useAppStore((s) => s.scrollRequest);
  const activeHighlight = useAppStore((s) => s.activeHighlight);
  const setHighlight = useAppStore((s) => s.setHighlight);
  const clearHighlight = useAppStore((s) => s.clearHighlight);
  const mode = useEffectiveMode(billId);
  const definedTerms = useAppStore((s) => s.definedTerms[billId]);
  const amendments = useAppStore((s) => s.amendments[billId]);
  const scrollRef = useRef<HTMLDivElement>(null);

  const tree = entry?.status === "ready" ? entry.tree : null;

  // The Decomp items the current mode anchors into this bill's text.
  const anchors = useMemo<DecompAnchor[]>(() => {
    if (mode === "definition" && definedTerms?.status === "ready") {
      return definitionAnchors(definedTerms.result);
    }
    if (mode === "amendment" && amendments?.status === "ready") {
      return amendmentAnchors(amendments.result);
    }
    return [];
  }, [mode, definedTerms, amendments]);

  // sectionId (any depth) -> id of its top-level section.
  const rootIndex = useMemo(
    () =>
      tree
        ? buildSectionRootIndex(tree.sections)
        : new Map<string, string>(),
    [tree],
  );

  // Structural break offsets per top-level section. Depends only on the
  // bill text, so switching Decomp mode never re-scans it.
  const sectionBreaks = useMemo(() => {
    const result = new Map<string, number[]>();
    if (tree) {
      for (const section of tree.sections) {
        result.set(section.section_id, formatStructure(section.text ?? ""));
      }
    }
    return result;
  }, [tree]);

  // Each top-level section's text, pre-split into plain / marked /
  // break segments. An anchor whose verbatim string cannot be located
  // is simply dropped — the highlight degrades, it is never fabricated.
  const sectionSegments = useMemo(() => {
    const result = new Map<string, TextSegment[]>();
    if (!tree) return result;

    const anchorsByRoot = new Map<string, DecompAnchor[]>();
    for (const anchor of anchors) {
      const root = rootIndex.get(anchor.sectionId);
      if (!root) continue;
      const list = anchorsByRoot.get(root) ?? [];
      list.push(anchor);
      anchorsByRoot.set(root, list);
    }

    for (const section of tree.sections) {
      const text = section.text ?? "";
      const spans: LocatedSpan[] = [];
      for (const anchor of anchorsByRoot.get(section.section_id) ?? []) {
        const span = findSpan(text, anchor.text);
        if (span) spans.push({ ...span, itemId: anchor.itemId });
      }
      result.set(
        section.section_id,
        buildSegments(text, spans, sectionBreaks.get(section.section_id) ?? []),
      );
    }
    return result;
  }, [tree, anchors, rootIndex, sectionBreaks]);

  const activeItemId =
    activeHighlight?.billId === billId ? activeHighlight.itemId : null;

  // Outline click-to-scroll (Phase 3).
  useEffect(() => {
    if (!scrollRequest || scrollRequest.billId !== billId) return;
    const container = scrollRef.current;
    if (!container) return;
    container
      .querySelector(`[data-section-id="${CSS.escape(scrollRequest.sectionId)}"]`)
      ?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [scrollRequest, billId]);

  // A Decomp card was clicked — scroll its span into view. If the span
  // could not be located, degrade to scrolling the anchoring section.
  useEffect(() => {
    if (!activeHighlight || activeHighlight.billId !== billId) return;
    const container = scrollRef.current;
    if (!container) return;
    const mark = container.querySelector(
      `[data-mark-id="${CSS.escape(activeHighlight.itemId)}"]`,
    );
    if (mark) {
      mark.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    const rootId = rootIndex.get(activeHighlight.sectionId);
    if (rootId) {
      container
        .querySelector(`[data-section-id="${CSS.escape(rootId)}"]`)
        ?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [activeHighlight, billId, rootIndex]);

  // Clicking a marked span: toggle it as the active highlight.
  const onActivateMark = (itemId: string) => {
    if (activeItemId === itemId) {
      clearHighlight();
      return;
    }
    const anchor = anchors.find((a) => a.itemId === itemId);
    if (!anchor) return;
    setHighlight({
      billId,
      itemId,
      sectionId: anchor.sectionId,
      text: anchor.text,
    });
  };

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
            {entry.tree.sections.map((section) => (
              <TopSection
                key={section.section_id}
                node={section}
                segments={
                  sectionSegments.get(section.section_id) ?? [
                    { kind: "plain", text: section.text ?? "" },
                  ]
                }
                activeItemId={activeItemId}
                onActivateMark={onActivateMark}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
