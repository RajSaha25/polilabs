import type { ReactNode } from "react";
import { activeTurn, useAppStore } from "../store/useAppStore";
import type { RankedBill } from "../api/types";
import { cn } from "../lib/cn";

/** A muted categorical chip — congress / tier. Mono, never neon. */
function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-[3px] bg-badge-bg px-1.5 py-px font-mono text-xs text-badge-ink">
      {children}
    </span>
  );
}

function BillListItem({
  bill,
  selected,
  onSelect,
}: {
  bill: RankedBill;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected}
      className={cn(
        "block w-full border-l-2 px-4 py-2.5 text-left transition-colors",
        selected
          ? "border-accent bg-accent-tint"
          : "border-transparent hover:bg-paper",
      )}
    >
      <div className="text-sm font-medium leading-snug text-ink">
        {bill.short_title || bill.title || bill.bill_id}
      </div>
      {bill.sponsor && (
        <div className="mt-0.5 truncate text-xs text-ink-faint">
          {bill.sponsor}
        </div>
      )}
      <div className="mt-1.5 flex items-center gap-1.5">
        {bill.congress != null && <Badge>{bill.congress}th</Badge>}
        {bill.tier && <Badge>Tier {bill.tier}</Badge>}
        <span className="font-mono text-xs text-ink-faint">{bill.bill_id}</span>
      </div>
    </button>
  );
}

/** The ranked "agent view" — every bill the answer drew on. */
export function BillList() {
  const bills = useAppStore((s) => activeTurn(s).rankedBills);
  const selectedIndex = useAppStore((s) => activeTurn(s).selectedBillIndex);
  const selectBill = useAppStore((s) => s.selectBill);

  if (bills.length === 0) return null;

  return (
    <div className="border-b border-line">
      <div className="px-4 pt-3 pb-1.5 text-xs font-medium tracking-wide text-ink-faint">
        BILLS · {bills.length}
      </div>
      <ul>
        {bills.map((bill, i) => (
          <li key={bill.bill_id}>
            <BillListItem
              bill={bill}
              selected={i === selectedIndex}
              onSelect={() => selectBill(i)}
            />
          </li>
        ))}
      </ul>
    </div>
  );
}
