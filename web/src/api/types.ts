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
