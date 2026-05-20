import { useAppStore } from "../store/useAppStore";
import { cn } from "../lib/cn";

/** Placeholder for the Text and Decomp panes. Phase 1 ships the agent
 *  path (left rail) only; Phase 2 builds the verbatim Text panel and
 *  Phases 3-4 the structured Decomp panel. This keeps the three-pane
 *  shell visible and confirms bill selection is wired end-to-end. */
export function ViewerStub({ kind }: { kind: "text" | "decomp" }) {
  const bills = useAppStore((s) => s.rankedBills);
  const selectedIndex = useAppStore((s) => s.selectedBillIndex);
  const selected = selectedIndex >= 0 ? bills[selectedIndex] : null;

  const label = kind === "text" ? "Text" : "Decomposition";
  const phase = kind === "text" ? "Phase 2" : "Phases 3–4";

  return (
    <div
      className={cn(
        "flex h-full min-h-0 flex-col bg-paper",
        kind === "text" && "border-r border-line",
      )}
    >
      <div className="border-b border-line px-4 py-3">
        <span className="text-xs font-medium tracking-wide text-ink-faint">
          {label.toUpperCase()}
        </span>
      </div>
      <div className="flex flex-1 items-center justify-center p-8">
        <div className="max-w-xs text-center">
          {selected ? (
            <>
              <div className="font-mono text-sm text-ink-soft">
                {selected.bill_id}
              </div>
              <div className="mt-1 text-sm text-ink-faint">
                {selected.short_title || selected.title}
              </div>
              <div className="mt-3 text-xs text-ink-faint">
                {label} panel — arriving in {phase}.
              </div>
            </>
          ) : (
            <div className="text-sm text-ink-faint">
              {kind === "text"
                ? "Ask a question, then pick a bill to read it here."
                : "The structured decomposition appears here."}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
