import type { BillSectionTree } from "./types";

/** Typed fetch wrappers for the read-only GET /api/* routes.
 *
 * These are the deterministic data path: navigating between bills hits
 * these endpoints directly — no agent turn, no token cost, no latency.
 * Phase 2 needs only the section tree; Phase 3+ will add defined_terms,
 * amendments, citation_graph. */

async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`backend returned HTTP ${res.status}`);
  return (await res.json()) as T;
}

/** Full nested section tree for a bill — GET /api/bill/{id}/sections. */
export function getBillSections(billId: string): Promise<BillSectionTree> {
  return getJSON<BillSectionTree>(
    `/api/bill/${encodeURIComponent(billId)}/sections`,
  );
}
