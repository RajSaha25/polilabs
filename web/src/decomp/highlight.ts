/** Substring-span matching for the synced highlight.
 *
 * A Decomp card carries a verbatim string; clicking it must highlight
 * that exact span in the Text panel. Legal-text extraction can re-wrap
 * lines, so an exact match is tried first and a whitespace-collapsed
 * match second. If neither finds the span the caller degrades to
 * scroll-only — it must NEVER fabricate a highlight. */

import type { SectionNode } from "../api/types";

export interface Span {
  start: number;
  end: number;
}

/** A located span tagged with the Decomp item it belongs to. */
export interface LocatedSpan extends Span {
  itemId: string;
}

/** Collapse runs of whitespace to single spaces — dropping leading and
 *  trailing whitespace — while keeping a map back to original indices.
 *  `map` has length `collapsed.length + 1`: `map[i]` is the original
 *  index where collapsed character `i` begins, and `map[collapsed.length]`
 *  is the original string length. */
function collapseWhitespace(s: string): { collapsed: string; map: number[] } {
  let collapsed = "";
  const map: number[] = [];
  let i = 0;
  while (i < s.length) {
    if (/\s/.test(s[i])) {
      const runStart = i;
      while (i < s.length && /\s/.test(s[i])) i++;
      // Emit one space only between non-whitespace — never leading/trailing.
      if (collapsed.length > 0 && i < s.length) {
        collapsed += " ";
        map.push(runStart);
      }
    } else {
      collapsed += s[i];
      map.push(i);
      i++;
    }
  }
  map.push(s.length);
  return { collapsed, map };
}

/** Locate `needle` as a verbatim span of `haystack`.
 *
 *  Tier 1 — exact substring match.
 *  Tier 2 — whitespace-collapsed match (extraction may re-wrap lines).
 *  Returns null if neither finds it; the caller then degrades to
 *  scroll-only and never fabricates a highlight. */
export function findSpan(haystack: string, needle: string): Span | null {
  if (!haystack || !needle) return null;

  const exact = haystack.indexOf(needle);
  if (exact !== -1) return { start: exact, end: exact + needle.length };

  const collapsedNeedle = needle.trim().replace(/\s+/g, " ");
  if (collapsedNeedle.length < 3) return null; // too short to anchor reliably

  const { collapsed, map } = collapseWhitespace(haystack);
  const ci = collapsed.indexOf(collapsedNeedle);
  if (ci === -1) return null;
  return { start: map[ci], end: map[ci + collapsedNeedle.length] };
}

/** Map every section_id — including nested subsections — to the id of
 *  its top-level ancestor. The Text panel renders one block per
 *  top-level section (its `text` is text_full, already containing every
 *  descendant), so that block is the finest available highlight anchor. */
export function buildSectionRootIndex(
  sections: SectionNode[],
): Map<string, string> {
  const index = new Map<string, string>();
  const walk = (node: SectionNode, rootId: string) => {
    index.set(node.section_id, rootId);
    for (const child of node.children) walk(child, rootId);
  };
  for (const root of sections) walk(root, root.section_id);
  return index;
}

export interface PlainSegment {
  kind: "plain";
  text: string;
}
export interface MarkSegment {
  kind: "mark";
  text: string;
  itemId: string;
}
export type TextSegment = PlainSegment | MarkSegment;

/** Split `text` into plain and marked segments given located spans.
 *  Overlapping spans are resolved by keeping the earlier-starting one —
 *  the later span is dropped rather than rendered partially. */
export function segmentText(
  text: string,
  spans: LocatedSpan[],
): TextSegment[] {
  if (spans.length === 0) return [{ kind: "plain", text }];

  const sorted = [...spans].sort((a, b) => a.start - b.start);
  const segments: TextSegment[] = [];
  let cursor = 0;

  for (const span of sorted) {
    if (span.start < cursor) continue; // overlaps an earlier mark — skip
    if (span.start > cursor) {
      segments.push({ kind: "plain", text: text.slice(cursor, span.start) });
    }
    segments.push({
      kind: "mark",
      text: text.slice(span.start, span.end),
      itemId: span.itemId,
    });
    cursor = span.end;
  }
  if (cursor < text.length) {
    segments.push({ kind: "plain", text: text.slice(cursor) });
  }
  return segments;
}
