import type { DecompMode } from "../api/types";
import { cn } from "../lib/cn";

/** The modes a user can switch to by hand. Citation mode lands in
 *  Phase 5; until then it is not offered as a tab. */
const TABS: { mode: DecompMode; label: string }[] = [
  { mode: "structure", label: "Structure" },
  { mode: "definition", label: "Definitions" },
  { mode: "amendment", label: "Amendments" },
];

/** Manual per-bill override of the Decomp mode — a compact segmented
 *  control. The active segment reflects what the panel is showing,
 *  whether that came from the auto mode or an earlier override. */
export function DecompModeTabs({
  active,
  onSelect,
}: {
  active: DecompMode;
  onSelect: (mode: DecompMode) => void;
}) {
  return (
    <div
      role="tablist"
      aria-label="Decomposition mode"
      className="inline-flex rounded-[4px] border border-line bg-paper p-0.5"
    >
      {TABS.map((tab) => {
        const selected = tab.mode === active;
        return (
          <button
            key={tab.mode}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onSelect(tab.mode)}
            className={cn(
              "rounded-[3px] px-2.5 py-1 text-xs transition-colors",
              selected
                ? "bg-surface font-medium text-ink"
                : "text-ink-faint hover:text-ink-soft",
            )}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
