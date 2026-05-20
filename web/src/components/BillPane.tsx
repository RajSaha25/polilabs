import { useRef, type PointerEvent as ReactPointerEvent } from "react";
import type { RankedBill } from "../api/types";
import { useAppStore } from "../store/useAppStore";
import { TextPanel } from "./TextPanel";
import { DecompPanel } from "./DecompPanel";

/** One bill's pane — verbatim Text alongside the structured Decomp,
 *  separated by a draggable divider (Overleaf-style). The split ratio
 *  lives in the store, so it stays consistent across carousel slides. */
export function BillPane({ bill }: { bill: RankedBill }) {
  const ratio = useAppStore((s) => s.splitRatio);
  const setSplitRatio = useAppStore((s) => s.setSplitRatio);
  const containerRef = useRef<HTMLDivElement>(null);

  const startDrag = (e: ReactPointerEvent) => {
    // Stop embla from reading this as a carousel swipe.
    e.stopPropagation();
    e.preventDefault();
    const container = containerRef.current;
    if (!container) return;

    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";

    const onMove = (ev: PointerEvent) => {
      const rect = container.getBoundingClientRect();
      setSplitRatio((ev.clientX - rect.left) / rect.width);
    };
    const onUp = () => {
      document.body.style.userSelect = "";
      document.body.style.cursor = "";
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
  };

  return (
    <div
      ref={containerRef}
      className="grid h-full min-h-0"
      style={{ gridTemplateColumns: `${ratio}fr 6px ${1 - ratio}fr` }}
    >
      <TextPanel bill={bill} />
      <div
        role="separator"
        aria-orientation="vertical"
        onPointerDown={startDrag}
        style={{ touchAction: "none" }}
        className="cursor-col-resize bg-line transition-colors hover:bg-accent"
      />
      <DecompPanel bill={bill} />
    </div>
  );
}
