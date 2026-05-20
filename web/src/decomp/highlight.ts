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
/** A structural line break inserted for readability — carries no text. */
export interface BreakSegment {
  kind: "break";
}
export type TextSegment = PlainSegment | MarkSegment | BreakSegment;

// Heading / division markers — a structural break goes before each.
const HEADING_MARKERS: RegExp[] = [
  /\b(?:Sec|SEC)\.\s+\d/g,
  /\bTITLE\s+[IVXLC]+/g,
  /\bSubtitle\s+[A-Z]\b/g,
  /\bPART\s+[IVXLC]+/g,
  /\bDIVISION\s+[A-Z]\b/g,
  /\bCHAPTER\s+\d/g,
];

// A lettered / numbered provision opening a new clause: it follows a
// sentence end (. ; or —). The break is placed before the opening "(".
const PROVISION_MARKER = /[.;—]\s+(\((?:\d{1,3}|[A-Za-z]{1,4})\)\s)/g;

/** Offsets in `text` where a structural line break improves readability
 *  — before section headings and new lettered/numbered provisions.
 *  Verbatim-safe: this only places visual breaks, never alters `text`,
 *  so a heuristic miss costs at most a slightly-off break. */
export function formatStructure(text: string): number[] {
  if (!text) return [];
  const offsets = new Set<number>();
  for (const marker of HEADING_MARKERS) {
    for (const m of text.matchAll(marker)) {
      if (m.index !== undefined) offsets.add(m.index);
    }
  }
  for (const m of text.matchAll(PROVISION_MARKER)) {
    // Break before the "(" — skip the leading sentence-end and spaces.
    if (m.index !== undefined && m[1]) {
      offsets.add(m.index + m[0].length - m[1].length);
    }
  }
  return [...offsets]
    .filter((o) => o > 0 && o < text.length)
    .sort((a, b) => a - b);
}

/** Split `text` into rendered segments: plain runs, highlighted marks,
 *  and structural breaks. `spans` are located highlight spans; `breaks`
 *  are structural break offsets from `formatStructure`. Every character
 *  of `text` lands in exactly one plain/mark segment, so offsets — and
 *  therefore the verbatim text — are preserved exactly. */
export function buildSegments(
  text: string,
  spans: LocatedSpan[],
  breaks: number[] = [],
): TextSegment[] {
  // Cut at every span boundary and every break, so each slice falls
  // wholly inside or wholly outside a mark.
  const cuts = new Set<number>([0, text.length]);
  for (const span of spans) {
    if (span.start > 0 && span.start < text.length) cuts.add(span.start);
    if (span.end > 0 && span.end < text.length) cuts.add(span.end);
  }
  const breakSet = new Set<number>();
  for (const b of breaks) {
    if (b > 0 && b < text.length) {
      cuts.add(b);
      breakSet.add(b);
    }
  }
  const sorted = [...cuts].sort((a, b) => a - b);

  const segments: TextSegment[] = [];
  for (let i = 0; i < sorted.length - 1; i++) {
    const start = sorted[i];
    const end = sorted[i + 1];
    if (start > 0 && breakSet.has(start)) segments.push({ kind: "break" });
    const slice = text.slice(start, end);
    if (!slice) continue;
    const span = spans.find((s) => s.start <= start && end <= s.end);
    segments.push(
      span
        ? { kind: "mark", text: slice, itemId: span.itemId }
        : { kind: "plain", text: slice },
    );
  }
  return segments;
}
