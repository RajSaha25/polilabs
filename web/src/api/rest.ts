import type {
  AmendmentsResult,
  BillSectionTree,
  DefinedTermsResult,
} from "./types";

/** Typed fetch wrappers for the read-only GET /api/* routes.
 *
 * These are the deterministic data path: navigating between bills hits
 * these endpoints directly — no agent turn, no token cost, no latency.
 * Phase 4 adds defined_terms and amendments; citation_graph in Phase 5. */

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

/** Defined terms for a bill — GET /api/bill/{id}/defined_terms. */
export function getDefinedTerms(billId: string): Promise<DefinedTermsResult> {
  return getJSON<DefinedTermsResult>(
    `/api/bill/${encodeURIComponent(billId)}/defined_terms`,
  );
}

/** Amendment operations a bill issues — GET /api/bill/{id}/amendments. */
export function getAmendments(billId: string): Promise<AmendmentsResult> {
  return getJSON<AmendmentsResult>(
    `/api/bill/${encodeURIComponent(billId)}/amendments`,
  );
}
