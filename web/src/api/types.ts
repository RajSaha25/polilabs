/** TypeScript mirrors of the polilabs backend shapes.
 *
 * Phase 1 needs only the /chat SSE event union and a normalized
 * RankedBill. Phase 2+ will expand this with the full api/types.py
 * mirror (Section, DefinedTerm, Amendment, ...). */

// ---- POST /chat — Server-Sent Events ----

export type SSEEvent =
  | { type: "text"; delta: string }
  | { type: "tool_call"; name: string; args: Record<string, unknown> }
  | {
      type: "tool_result";
      name: string;
      args: Record<string, unknown>;
      result: unknown;
    }
  | { type: "done" }
  | { type: "error"; message: string };

export interface ChatHistoryItem {
  role: "user" | "assistant";
  content: string;
}

// ---- captured during a turn ----

export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
}

export interface ToolResult {
  name: string;
  args: Record<string, unknown>;
  result: unknown;
}

// ---- derived: the ranked bill list shown in the left rail ----
//
// Every polilabs query naturally produces a set of source bills. The
// agent path surfaces them inside tool_result payloads; `RankedBill` is
// the normalized shape the UI renders, regardless of which tool
// produced it (search hits, aggregate matches, a single get_bill).

export interface RankedBill {
  bill_id: string;
  title: string;
  short_title: string | null;
  sponsor: string | null;
  congress: number | null;
  tier: string | null;
}

// ---- REST: GET /api/bill/{id}/sections ----
//
// The full nested section tree. A section's `text` is text_full — it
// already contains every descendant's text — so the Text panel renders
// only the top-level sections' text; `children` feeds the structure
// outline (Phase 3), not the body.

export interface SectionNode {
  section_id: string;
  heading: string;
  canonical_citation: string;
  text: string | null;
  children: SectionNode[];
}

export interface BillSectionTree {
  bill_id: string;
  sections: SectionNode[];
}

/** Per-bill REST-fetched state, cached in the store (bill text is
 *  immutable in v1, so an entry never needs invalidation). */
export type BillData =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; tree: BillSectionTree };
