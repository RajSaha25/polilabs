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

/** A REST-fetched resource cached per bill — definitions, amendments.
 *  Like BillData, entries are immutable in v1. */
export type AsyncResource<T> =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; result: T };

// ---- Decomp panel modes ----
//
// The Decomp panel adapts to the kind of question asked. The mode is
// auto-selected from the tools the agent ran (decomp/selectMode.ts) and
// can be overridden per bill via the mode tabs.

export type DecompMode = "structure" | "definition" | "amendment" | "citation";

// ---- definitions — GET /api/bill/{id}/defined_terms ----
//
// Mirrors api/types.py DefinedTerm / DefinedTermsResult. Only the fields
// the UI renders are mirrored.

export type DefinitionType = "direct" | "by_reference";
export type DefinitionScope =
  | "section_local"
  | "title_local"
  | "bill_local"
  | "statute_global"
  | "jurisdiction_global";

export interface DefinedTerm {
  defined_term_id: string;
  surface_form: string;
  bill_id: string;
  defining_section_id: string;
  defining_section_citation: string;
  scope: DefinitionScope;
  definition_type: DefinitionType;
  /** Verbatim definition text — the synced-highlight anchor string. */
  definition_text: string;
  by_reference_target_id: string | null;
  by_reference_target_citation: string | null;
}

export interface DefinedTermsResult {
  bill_id: string;
  terms: DefinedTerm[];
  coverage_note: string;
}

// ---- amendments — GET /api/bill/{id}/amendments ----
//
// Mirrors api/types.py Amendment / AmendmentsResult. `before_text` is
// often null (insert-only operations); `after_text` is the verbatim
// quoted new-law block.

export type AmendmentOperationType =
  | "strike"
  | "insert"
  | "strike_and_insert"
  | "replace"
  | "add_at_end"
  | "repeal"
  | "redesignate"
  | "other";

export interface Amendment {
  amendment_id: string;
  source_section_id: string;
  source_section_citation: string;
  operation_type: AmendmentOperationType;
  operation_text: string;
  target_statute_section_id: string | null;
  target_canonical_citation: string | null;
  before_text: string | null;
  after_text: string;
  /** True for every operation in v1 — USC text is not yet ingested. */
  target_text_unverified: boolean;
}

export interface AmendmentsResult {
  bill_id: string;
  amendments: Amendment[];
  coverage_note: string;
}

// ---- the synced highlight ----
//
// A Decomp item carries a section id and a verbatim string; clicking it
// highlights that exact span in the Text panel. `seq` is bumped on every
// set so a repeat click of the same item still re-fires the scroll.

export interface ActiveHighlight {
  billId: string;
  /** defined_term_id or amendment_id — the anchored Decomp item. */
  itemId: string;
  /** The anchoring section; may be a nested subsection. */
  sectionId: string;
  /** The verbatim string to locate in the Text panel. */
  text: string;
  seq: number;
}
