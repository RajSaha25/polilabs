import type { RankedBill } from "../api/types";
import { useAppStore } from "../store/useAppStore";
import { StructureMode } from "./StructureMode";

/** The right pane: the structured decomposition. Phase 3 ships the
 *  structure outline; definition / amendment / citation modes and the
 *  mode tabs arrive in Phases 4–5. */
export function DecompPanel({ bill }: { bill: RankedBill }) {
  const entry = useAppStore((s) => s.billData[bill.bill_id]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-paper">
      <div className="border-b border-line px-4 py-3">
        <div className="text-xs font-medium tracking-wide text-ink-faint">
          DECOMPOSITION
        </div>
        <div className="mt-0.5 text-sm text-ink">Structure</div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-1">
        {(!entry || entry.status === "loading") && (
          <p className="px-2 py-3 text-sm text-ink-faint">Loading structure…</p>
        )}
        {entry?.status === "error" && (
          <p className="px-2 py-3 text-sm text-ink-faint">
            Couldn't load — {entry.message}
          </p>
        )}
        {entry?.status === "ready" && (
          <StructureMode billId={bill.bill_id} sections={entry.tree.sections} />
        )}
      </div>
    </div>
  );
}
