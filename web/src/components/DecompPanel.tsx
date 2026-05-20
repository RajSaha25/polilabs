import { useEffect, useRef } from "react";
import type { DecompMode, RankedBill } from "../api/types";
import { useAppStore } from "../store/useAppStore";
import { useEffectiveMode } from "../decomp/selectMode";
import { DecompModeTabs } from "./DecompModeTabs";
import { StructureMode } from "./StructureMode";
import { DefinitionMode } from "./DefinitionMode";
import { AmendmentMode } from "./AmendmentMode";

/** The right pane: the structured decomposition. The mode adapts to the
 *  kind of question asked and can be overridden via the tabs. Clicking
 *  a verbatim span in the Text panel scrolls the matching card here into
 *  view — the reverse half of the synced highlight. */
export function DecompPanel({ bill }: { bill: RankedBill }) {
  const billId = bill.bill_id;
  const entry = useAppStore((s) => s.billData[billId]);
  const setDecompMode = useAppStore((s) => s.setDecompMode);
  const activeHighlight = useAppStore((s) => s.activeHighlight);
  const mode = useEffectiveMode(billId);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Citation mode lands in Phase 5; until then it renders as structure.
  const renderMode: DecompMode = mode === "citation" ? "structure" : mode;

  // A Text-panel span was clicked — bring its card into view.
  useEffect(() => {
    if (!activeHighlight || activeHighlight.billId !== billId) return;
    const card = scrollRef.current?.querySelector(
      `[data-card-id="${CSS.escape(activeHighlight.itemId)}"]`,
    );
    card?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [activeHighlight, billId]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-paper">
      <div className="border-b border-line px-4 py-3">
        <div className="text-xs font-medium tracking-wide text-ink-faint">
          DECOMPOSITION
        </div>
        <div className="mt-1.5">
          <DecompModeTabs
            active={renderMode}
            onSelect={(m) => setDecompMode(billId, m)}
          />
        </div>
      </div>
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto">
        {renderMode === "structure" && (
          <div className="px-2 py-1">
            {(!entry || entry.status === "loading") && (
              <p className="px-2 py-3 text-sm text-ink-faint">
                Loading structure…
              </p>
            )}
            {entry?.status === "error" && (
              <p className="px-2 py-3 text-sm text-ink-faint">
                Couldn't load — {entry.message}
              </p>
            )}
            {entry?.status === "ready" && (
              <StructureMode billId={billId} sections={entry.tree.sections} />
            )}
          </div>
        )}
        {renderMode === "definition" && <DefinitionMode billId={billId} />}
        {renderMode === "amendment" && <AmendmentMode billId={billId} />}
      </div>
    </div>
  );
}
