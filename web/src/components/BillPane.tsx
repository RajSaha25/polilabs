import type { RankedBill } from "../api/types";
import { TextPanel } from "./TextPanel";
import { DecompPanel } from "./DecompPanel";

/** One bill's full pane — verbatim Text alongside the structured
 *  Decomp. One BillPane per carousel slide. */
export function BillPane({ bill }: { bill: RankedBill }) {
  return (
    <div
      className="grid h-full min-h-0"
      style={{ gridTemplateColumns: "minmax(0, 1fr) 380px" }}
    >
      <TextPanel bill={bill} />
      <DecompPanel />
    </div>
  );
}
