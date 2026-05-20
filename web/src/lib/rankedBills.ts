import type { RankedBill, ToolResult } from "../api/types";

/** Normalize one bill-bearing object into a RankedBill.
 *
 * Search hits carry `title` / `short_title` / `sponsor`; the aggregate
 * primitives carry `bill_title` / `bill_short_title` and often no
 * sponsor. This collapses both into one shape. */
function toRankedBill(o: Record<string, unknown>): RankedBill | null {
  const billId = o.bill_id;
  if (typeof billId !== "string" || !billId) return null;
  const str = (v: unknown): string | null =>
    typeof v === "string" && v ? v : null;
  return {
    bill_id: billId,
    title: str(o.title) ?? str(o.bill_title) ?? "",
    short_title: str(o.short_title) ?? str(o.bill_short_title),
    sponsor: str(o.sponsor),
    congress: typeof o.congress === "number" ? o.congress : null,
    tier: str(o.tier),
  };
}

/** Bill-bearing array fields a tool result may carry. */
const LIST_KEYS = ["hits", "matches", "definitions", "bills"] as const;

/** Extract the ranked bill list from a turn's tool results.
 *
 * Scans every tool_result for bill-bearing shapes — a list under one of
 * LIST_KEYS, or a single object with a `bill_id`. Dedupes by bill_id,
 * preserving the order the agent surfaced them in. */
export function extractRankedBills(toolResults: ToolResult[]): RankedBill[] {
  const seen = new Map<string, RankedBill>();

  const consider = (o: unknown) => {
    if (!o || typeof o !== "object") return;
    const bill = toRankedBill(o as Record<string, unknown>);
    if (bill && !seen.has(bill.bill_id)) seen.set(bill.bill_id, bill);
  };

  for (const tr of toolResults) {
    const result = tr.result;
    if (!result || typeof result !== "object") continue;
    const obj = result as Record<string, unknown>;

    let matchedList = false;
    for (const key of LIST_KEYS) {
      const list = obj[key];
      if (Array.isArray(list)) {
        matchedList = true;
        for (const item of list) consider(item);
      }
    }
    // A single-bill result (get_bill / get_amendments / get_defined_terms).
    if (!matchedList) consider(obj);
  }

  return [...seen.values()];
}
