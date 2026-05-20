import type { ReactNode } from "react";
import { cn } from "../lib/cn";

/** A small categorical tag for Decomp cards — definition type / scope,
 *  amendment operation. Muted, never neon (web/DESIGN.md). */
export function Tag({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "accent";
}) {
  return (
    <span
      className={cn(
        "rounded-[3px] px-1.5 py-px text-xs",
        tone === "accent"
          ? "bg-accent-tint text-accent"
          : "bg-badge-bg text-badge-ink",
      )}
    >
      {children}
    </span>
  );
}
