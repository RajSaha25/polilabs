import type { SectionNode } from "../api/types";
import { useAppStore } from "../store/useAppStore";
import { cn } from "../lib/cn";

/** Short locator from a canonical citation:
 *  "Sec. 3(b) of H.R. 1736, 119th Cong." -> "Sec. 3(b)". */
function locator(citation: string): string {
  const head = citation.split(" of ")[0]?.trim();
  return head || "§";
}

/** One outline row + its descendants. Clicking any row scrolls the
 *  Text panel to the row's top-level section (`rootId`) — the Text
 *  panel renders each top-level section as one verbatim block, so
 *  that's the finest anchor available. Span-precise location is the
 *  job of the synced highlight in Phase 4. */
function OutlineRow({
  node,
  depth,
  rootId,
  billId,
}: {
  node: SectionNode;
  depth: number;
  rootId: string;
  billId: string;
}) {
  const requestScroll = useAppStore((s) => s.requestScroll);

  return (
    <>
      <button
        type="button"
        onClick={() => requestScroll(billId, rootId)}
        style={{ paddingLeft: 8 + depth * 14 }}
        className="block w-full rounded-[3px] py-1 pr-2 text-left transition-colors hover:bg-accent-tint"
      >
        <span className="font-mono text-xs text-ink-soft">
          {locator(node.canonical_citation)}
        </span>
        {node.heading && (
          <span
            className={cn(
              "ml-2 text-xs",
              depth === 0 ? "font-medium text-ink" : "text-ink-soft",
            )}
          >
            {node.heading}
          </span>
        )}
      </button>
      {node.children.map((child) => (
        <OutlineRow
          key={child.section_id}
          node={child}
          depth={depth + 1}
          rootId={rootId}
          billId={billId}
        />
      ))}
    </>
  );
}

/** Structure mode — the bill's nested section outline. Reads as
 *  structured data (mono locators, indentation), distinct from the
 *  serif prose of the Text panel. */
export function StructureMode({
  billId,
  sections,
}: {
  billId: string;
  sections: SectionNode[];
}) {
  return (
    <div className="py-1">
      {sections.map((section) => (
        <OutlineRow
          key={section.section_id}
          node={section}
          depth={0}
          rootId={section.section_id}
          billId={billId}
        />
      ))}
    </div>
  );
}
